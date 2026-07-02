"""提交与执行 job 的共享服务层。被 Web 与 CLI 复用，避免逻辑漂移。"""

from __future__ import annotations

import threading

from . import db
from .benchmark.endpoints import EndpointError, mask_base_url, normalize_base_url
from .config import BENCHMARK_MODES, ENDPOINT_TYPES, mode_config
from .models import RunStatus, Status, new_job_id
from .runner import execute_job


class SubmitError(ValueError):
    pass


def build_job(
    *,
    endpoint_type: str,
    model_name: str,
    base_url: str | None = None,
    port: int | str | None = None,
    benchmark_mode: str = "smoke",
    dataset_profile: str | None = None,
    notes: str | None = None,
) -> dict:
    """校验入参并构造 jobs 行（不入库）。"""
    if endpoint_type not in ENDPOINT_TYPES:
        raise SubmitError(
            f"endpoint_type 必须是 {ENDPOINT_TYPES}，收到 {endpoint_type}"
        )
    if benchmark_mode not in BENCHMARK_MODES:
        raise SubmitError(
            f"benchmark_mode 必须是 {BENCHMARK_MODES}，收到 {benchmark_mode}"
        )
    if not model_name or not model_name.strip():
        raise SubmitError("model_name 不能为空")

    try:
        norm_url = normalize_base_url(base_url, port)
    except EndpointError as e:
        raise SubmitError(str(e))

    cfg = mode_config(benchmark_mode)
    if dataset_profile:
        cfg["dataset_profile"] = dataset_profile

    job_id = new_job_id()
    now = db.now()
    job = {
        "id": job_id,
        "endpoint_type": endpoint_type,
        "model_name": model_name.strip(),
        "base_url": norm_url,
        "base_url_masked": mask_base_url(norm_url),
        "status": Status.QUEUED,
        "benchmark_mode": benchmark_mode,
        "dataset_profile": cfg["dataset_profile"],
        "total_requests": cfg["total_requests"],
        "concurrency": cfg["concurrency"],
        "max_output_tokens": cfg["max_output_tokens"],
        "temperature": cfg["temperature"],
        "top_p": cfg["top_p"],
        "stream": 1 if cfg["stream"] else 0,
        "request_timeout": cfg["request_timeout"],
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "error_message": None,
        "run_dir": None,
        "leaderboard_eligible": 0,
        "ineligible_reason": None,
        "notes": notes,
        "run_status": RunStatus.QUEUED,
    }
    return job


def submit_job(
    *, api_key: str | None = None, background: bool = True, **kwargs
) -> dict:
    """构造 + 入库 + （可选）后台执行。返回 job dict。

    同一 base_url + endpoint_type 同时只允许一个 running/queued job。
    api_key 只在内存传递，不入库。
    """
    job = build_job(**kwargs)

    if db.has_running_job_for_endpoint(job["base_url"], job["endpoint_type"]):
        raise SubmitError(
            f"该 endpoint ({job['base_url_masked']} / {job['endpoint_type']}) "
            f"已有运行中的任务，请等待其完成"
        )

    db.insert_job(job)

    if background:
        t = threading.Thread(target=execute_job, args=(job, api_key), daemon=True)
        t.start()
    else:
        execute_job(job, api_key)
    return job


def run_job_sync(job_id: str, api_key: str | None = None) -> dict:
    job = db.get_job(job_id)
    if not job:
        raise SubmitError(f"job 不存在: {job_id}")
    return execute_job(job, api_key)
