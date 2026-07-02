"""任务编排：健康检查 -> stream 探测 -> benchmark -> 解析 -> 报告 -> 入库。

被 Web 后台线程和 CLI 共同调用。runner 分发：优先 guidellm（若可用且支持），
否则回落 custom_http_runner（主路径）。api_key 只在内存使用，不写日志/不入库。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import traceback

from . import db, reports
from .benchmark import custom_http_runner, datasets, guidellm_runner
from .benchmark.endpoints import mask_base_url
from .config import RUNS_DIR, mode_config
from .models import RunStatus, Status
from .parser import build_parsed_result, to_results_row


class _Tee:
    """同时写文件与内存（用于 stdout/stderr 落盘）。"""

    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.f.write(line + "\n")
        self.f.flush()

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


def _decide_runner(endpoint_type: str) -> tuple[str, str]:
    """选择 runner。返回 (runner_name, reason)。"""
    ok, info = guidellm_runner.available()
    if ok:
        # MVP：guidellm 可用也优先用 custom_http 以保证精确 per-request 指标与一致性。
        # 仍记录 guidellm 可用信息，便于后续切换。
        return (
            "custom_http",
            f"guidellm 可用({info})，MVP 默认用 custom_http 保证精确逐请求指标",
        )
    return "custom_http", f"guidellm 不可用({info})，回落 custom_http"


def execute_job(job: dict, api_key: str | None) -> dict:
    """同步执行一个 job（在后台线程里跑）。job 为 jobs 表 dict。

    返回最终的 parsed_result（含 run_status / eligibility）。
    任何阶段失败都会落盘错误并把 job 标记 failed，不抛到调用方。
    """
    job_id = job["id"]
    run_dir = os.path.join(RUNS_DIR, job_id)
    os.makedirs(run_dir, exist_ok=True)
    stdout = _Tee(os.path.join(run_dir, "stdout.log"))
    stderr = _Tee(os.path.join(run_dir, "stderr.log"))

    endpoint_type = job["endpoint_type"]
    base_url = job["base_url"]
    model_name = job["model_name"]
    mode = job["benchmark_mode"]
    cfg = mode_config(mode)
    total_requests = job["total_requests"]
    concurrency = job["concurrency"]
    max_output_tokens = job["max_output_tokens"]
    temperature = job["temperature"]
    top_p = job["top_p"]
    request_timeout = job["request_timeout"]
    dataset_profile = job["dataset_profile"]

    db.update_job(
        job_id, status=Status.RUNNING, run_status=RunStatus.RUNNING, started_at=db.now()
    )

    # config.json（不含 api_key）
    config_dump = {
        "job_id": job_id,
        "endpoint_type": endpoint_type,
        "base_url_masked": mask_base_url(base_url),
        "model_name": model_name,
        "benchmark_mode": mode,
        "dataset_profile": dataset_profile,
        "total_requests": total_requests,
        "concurrency": concurrency,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": True,
        "request_timeout": request_timeout,
        "api_key_provided": bool(api_key),
    }
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config_dump, f, ensure_ascii=False, indent=2)

    runner_name, runner_reason = _decide_runner(endpoint_type)
    stdout.log(f"runner 选择: {runner_name} — {runner_reason}")

    raw_payload = {"runner": runner_name, "runner_reason": runner_reason}

    try:
        # ── 1. 健康检查 /models ──
        models = asyncio.run(custom_http_runner.check_models(base_url, api_key))
        raw_payload["models_check"] = models
        stdout.log(
            f"/models 检查: status={models['status']} http={models['http_status']} "
            f"models={models.get('models')}"
        )
        if models["status"] != "success":
            stdout.log(f"/models 不可访问（{models.get('error')}），仍尝试 smoke 探测")

        # ── 2. 加载数据集 ──
        n = total_requests
        prompts = datasets.load_dataset(dataset_profile, limit=n)
        if len(prompts) < n:
            stdout.log(f"警告: 数据集仅 {len(prompts)} 条 < 请求数 {n}，将循环复用")
            # 循环填充到 n 条
            prompts = [prompts[i % len(prompts)] for i in range(n)]
        stdout.log(f"数据集加载: profile={dataset_profile} 使用 {len(prompts)} 条")

        # ── 3. stream 探测 ──
        smoke = asyncio.run(
            custom_http_runner.smoke_request(
                base_url,
                endpoint_type,
                model_name,
                prompts[0]["prompt"],
                api_key,
                max_tokens=16,
                timeout=min(request_timeout, 60),
            )
        )
        stream_supported = bool(smoke.streamed and smoke.success)
        raw_payload["smoke"] = smoke.to_dict()
        stdout.log(
            f"stream 探测: success={smoke.success} streamed={smoke.streamed} "
            f"status={smoke.status_code} err={smoke.error_message}"
        )

        if not smoke.success:
            # smoke 直接失败 -> 任务 failed，记录明确原因，不伪造成功
            msg = smoke.error_message or "smoke 请求失败"
            raise RuntimeError(f"smoke 请求失败: {msg}")

        # ── 4. 正式 benchmark ──
        stdout.log(
            f"开始 benchmark: requests={n} concurrency={concurrency} stream_supported={stream_supported}"
        )
        result = custom_http_runner.run_benchmark(
            base_url=base_url,
            endpoint_type=endpoint_type,
            model_name=model_name,
            prompts=prompts,
            concurrency=concurrency,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
            request_timeout=float(request_timeout),
            api_key=api_key,
            stream_supported=stream_supported,
        )
        result.runner_name = runner_name
        n_ok = sum(1 for r in result.records if r.success)
        stdout.log(
            f"benchmark 完成: {n_ok}/{len(result.records)} 成功, "
            f"有效时长={result.effective_duration:.2f}s"
        )

        # ── 5. 落盘 raw + per-request ──
        with open(os.path.join(run_dir, "raw_result.json"), "w", encoding="utf-8") as f:
            json.dump(raw_payload, f, ensure_ascii=False, indent=2)
        reports.write_per_request(run_dir, result)

        # ── 6. 解析 + eligibility ──
        parsed = build_parsed_result(
            job_id=job_id,
            endpoint_type=endpoint_type,
            model_name=model_name,
            base_url_masked=mask_base_url(base_url),
            benchmark_mode=mode,
            dataset_profile=dataset_profile,
            total_requests=total_requests,
            concurrency=concurrency,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
            result=result,
            completed=True,
        )
        parsed["created_at"] = db.now()

        # ── 7. 报告 ──
        json_path = reports.write_parsed_json(run_dir, parsed)
        csv_path = reports.write_csv(run_dir, parsed)
        html_path = reports.write_report_html(run_dir, parsed, job)
        paths = {
            "json": json_path,
            "csv": csv_path,
            "html": html_path,
            "raw": os.path.join(run_dir, "raw_result.json"),
        }

        # ── 8. 入库 ──
        row = to_results_row(parsed, paths)
        db.insert_result(row)
        db.update_job(
            job_id,
            status=Status.SUCCESS,
            run_status=parsed["run_status"],
            finished_at=db.now(),
            leaderboard_eligible=1 if parsed["leaderboard_eligible"] else 0,
            ineligible_reason=parsed["ineligible_reason"],
        )
        stdout.log(
            f"任务完成: run_status={parsed['run_status']} "
            f"eligible={parsed['leaderboard_eligible']}"
        )
        stdout.close()
        stderr.close()
        return parsed

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        stderr.log(f"任务失败: {type(e).__name__}: {e}")
        stderr.log(tb)
        # 落盘已有 raw_payload，便于排查
        try:
            with open(
                os.path.join(run_dir, "raw_result.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(raw_payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        db.update_job(
            job_id,
            status=Status.FAILED,
            run_status=RunStatus.FAILED,
            finished_at=db.now(),
            error_message=f"{type(e).__name__}: {e}",
            leaderboard_eligible=0,
            ineligible_reason=f"任务失败: {e}",
        )
        stdout.close()
        stderr.close()
        return {"job_id": job_id, "run_status": RunStatus.FAILED, "error": str(e)}
