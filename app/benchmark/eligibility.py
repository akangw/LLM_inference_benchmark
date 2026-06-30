"""leaderboard_eligible 判定（正式榜单准入）。

严格按 spec：只有 public_leaderboard 且配置完全等于固定方案、stream 真生效、
benchmark 完整结束、错误率/成功率达标，才允许进入正式榜单。
任何不满足项都给出明确 ineligible_reason（不静默淘汰）。
只依赖标准库。
"""
from __future__ import annotations

from ..config import LEADERBOARD_MODE, PUBLIC_LEADERBOARD_CONFIG
from .metrics import Metrics
from .slo import MAX_ERROR_RATE, MIN_SUCCESS_RATE


def evaluate_eligibility(
    *,
    benchmark_mode: str,
    endpoint_type: str,
    dataset_profile: str,
    total_requests: int,
    concurrency: int,
    max_output_tokens: int,
    temperature: float,
    top_p: float,
    stream_supported: bool,
    completed: bool,
    metrics: Metrics,
    usage_available: bool,
) -> tuple[bool, str | None]:
    """返回 (eligible, reason)。eligible=True 时 reason=None。"""
    reasons: list[str] = []

    if benchmark_mode != LEADERBOARD_MODE:
        reasons.append(f"benchmark_mode={benchmark_mode} 非 {LEADERBOARD_MODE}")

    cfg = PUBLIC_LEADERBOARD_CONFIG
    if dataset_profile != cfg["dataset_profile"]:
        reasons.append(f"dataset_profile={dataset_profile} 非 {cfg['dataset_profile']}")
    if total_requests != cfg["total_requests"]:
        reasons.append(f"total_requests={total_requests} 非 {cfg['total_requests']}")
    if concurrency != cfg["concurrency"]:
        reasons.append(f"concurrency={concurrency} 非 {cfg['concurrency']}")
    if max_output_tokens != cfg["max_output_tokens"]:
        reasons.append(f"max_output_tokens={max_output_tokens} 非 {cfg['max_output_tokens']}")
    if float(temperature) != float(cfg["temperature"]):
        reasons.append(f"temperature={temperature} 非 {cfg['temperature']}")
    if float(top_p) != float(cfg["top_p"]):
        reasons.append(f"top_p={top_p} 非 {cfg['top_p']}")

    if endpoint_type not in ("chat_completions", "completions"):
        reasons.append(f"endpoint_type={endpoint_type} 不支持")
    if not stream_supported:
        reasons.append("stream_supported=false")
    if not completed:
        reasons.append("benchmark 未完整结束")
    if not usage_available:
        reasons.append("usage/本地 token 统计不可用")

    if metrics.error_rate > MAX_ERROR_RATE:
        reasons.append(f"error_rate={metrics.error_rate:.4f} > {MAX_ERROR_RATE}")
    if metrics.success_rate < MIN_SUCCESS_RATE:
        reasons.append(f"success_rate={metrics.success_rate:.4f} < {MIN_SUCCESS_RATE}")

    if reasons:
        return False, "; ".join(reasons)
    return True, None
