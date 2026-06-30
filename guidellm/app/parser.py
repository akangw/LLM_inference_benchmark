"""把 runner 的 BenchmarkResult 解析成 parsed_result.json 结构 + results 表行。

负责：计算 metrics、判定 SLO 闸门与 leaderboard_eligible、确定 run_status。
只依赖标准库 + 本包内模块。
"""
from __future__ import annotations

from .benchmark.eligibility import evaluate_eligibility
from .benchmark.metrics import BenchmarkResult, Metrics, slo_gate_pass
from .models import RunStatus


def build_parsed_result(
    *,
    job_id: str,
    endpoint_type: str,
    model_name: str,
    base_url_masked: str,
    benchmark_mode: str,
    dataset_profile: str,
    total_requests: int,
    concurrency: int,
    max_output_tokens: int,
    temperature: float,
    top_p: float,
    result: BenchmarkResult,
    completed: bool,
) -> dict:
    """返回 parsed_result.json 的完整 dict（含 metrics + eligibility + run_status）。"""
    metrics: Metrics = result.to_metrics()

    eligible, reason = evaluate_eligibility(
        benchmark_mode=benchmark_mode,
        endpoint_type=endpoint_type,
        dataset_profile=dataset_profile,
        total_requests=total_requests,
        concurrency=concurrency,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        top_p=top_p,
        stream_supported=result.stream_supported,
        completed=completed,
        metrics=metrics,
        usage_available=result.usage_available,
    )

    gate = slo_gate_pass(metrics)
    # run_status 语义
    if not completed:
        run_status = RunStatus.FAILED
    elif eligible:
        run_status = RunStatus.SLO_PASS
    elif benchmark_mode == "public_leaderboard":
        # 完成但没进榜：区分 SLO 不达标 vs 其他准入不满足
        run_status = RunStatus.SLO_FAIL if not gate else RunStatus.NOT_LEADERBOARD_ELIGIBLE
    else:
        run_status = RunStatus.NOT_LEADERBOARD_ELIGIBLE

    parsed = {
        "job_id": job_id,
        "endpoint_type": endpoint_type,
        "model_name": model_name,
        "base_url_masked": base_url_masked,
        "benchmark_mode": benchmark_mode,
        "dataset_profile": dataset_profile,
        "total_requests": total_requests,
        "concurrency": concurrency,
        "max_output_tokens": max_output_tokens,
        "stream_supported": result.stream_supported,
        "usage_available": result.usage_available,
        "prompt_tokens_count_source": result.prompt_tokens_count_source,
        "output_tokens_count_source": result.output_tokens_count_source,
        "runner_name": result.runner_name,
        "effective_duration": round(result.effective_duration, 4),
        "leaderboard_eligible": eligible,
        "ineligible_reason": reason,
        "run_status": run_status,
        "slo_gate_pass": gate,
        "metrics": metrics.to_dict(),
        "_metrics_obj": metrics,  # 内部用，序列化前剔除
    }
    return parsed


def to_results_row(parsed: dict, paths: dict) -> dict:
    """parsed_result -> results 表行。"""
    m = parsed["metrics"]
    return {
        "job_id": parsed["job_id"],
        "endpoint_type": parsed["endpoint_type"],
        "model_name": parsed["model_name"],
        "benchmark_mode": parsed["benchmark_mode"],
        "dataset_profile": parsed["dataset_profile"],
        "total_requests": parsed["total_requests"],
        "concurrency": parsed["concurrency"],
        "max_output_tokens": parsed["max_output_tokens"],
        "raw_request_throughput": m["raw_request_throughput"],
        "raw_output_tokens_per_second": m["raw_output_tokens_per_second"],
        "raw_total_tokens_per_second": m["raw_total_tokens_per_second"],
        "goodput_requests_per_second": m["goodput_requests_per_second"],
        "goodput_output_tokens_per_second": m["goodput_output_tokens_per_second"],
        "p50_ttft": m["p50_ttft"], "p95_ttft": m["p95_ttft"], "p99_ttft": m["p99_ttft"],
        "p50_tpot": m["p50_tpot"], "p95_tpot": m["p95_tpot"], "p99_tpot": m["p99_tpot"],
        "p50_e2e_latency": m["p50_e2e_latency"],
        "p95_e2e_latency": m["p95_e2e_latency"],
        "p99_e2e_latency": m["p99_e2e_latency"],
        "success_rate": m["success_rate"],
        "error_rate": m["error_rate"],
        "timeout_rate": m["timeout_rate"],
        "slo_pass_rate": m["slo_pass_rate"],
        "stream_supported": 1 if parsed["stream_supported"] else 0,
        "usage_available": 1 if parsed["usage_available"] else 0,
        "prompt_tokens_count_source": parsed["prompt_tokens_count_source"],
        "output_tokens_count_source": parsed["output_tokens_count_source"],
        "leaderboard_eligible": 1 if parsed["leaderboard_eligible"] else 0,
        "ineligible_reason": parsed["ineligible_reason"],
        "json_report_path": paths.get("json"),
        "html_report_path": paths.get("html"),
        "csv_report_path": paths.get("csv"),
        "raw_report_path": paths.get("raw"),
        "created_at": parsed.get("created_at"),
    }
