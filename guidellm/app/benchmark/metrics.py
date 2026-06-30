"""从 per-request 观测值聚合出榜单指标。

不使用任何自创加权综合分。主指标是 goodput_output_tokens_per_second，
同时保留全部原始指标（raw throughput / 各分位延迟 / 成功率等）。
只依赖标准库。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .slo import (
    MAX_ERROR_RATE,
    MIN_SUCCESS_RATE,
    RequestRecord,
    meets_slo,
)


def _percentile(values: list[float], pct: float) -> float:
    """线性插值分位数。values 已可乱序；pct ∈ [0,100]。空列表返回 0。"""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    rank = (pct / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return float(s[lo] + (s[hi] - s[lo]) * frac)


@dataclass
class BenchmarkResult:
    """所有 runner 的统一返回。runner -> parser/metrics -> reports/db。"""
    records: list[RequestRecord] = field(default_factory=list)
    # 有效运行时间（秒）：第一条请求开始到最后一条请求结束的墙钟时间
    effective_duration: float = 0.0
    stream_supported: bool = False
    usage_available: bool = False
    prompt_tokens_count_source: str = "unknown"   # usage / approximate / tokenizer
    output_tokens_count_source: str = "unknown"
    runner_name: str = "custom_http"
    notes: str | None = None

    def to_metrics(self) -> "Metrics":
        return compute_metrics(self)


@dataclass
class Metrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_requests: int = 0
    slo_pass_requests: int = 0

    goodput_output_tokens_per_second: float = 0.0
    goodput_requests_per_second: float = 0.0
    raw_output_tokens_per_second: float = 0.0
    raw_request_throughput: float = 0.0
    raw_total_tokens_per_second: float = 0.0

    slo_pass_rate: float = 0.0
    success_rate: float = 0.0
    error_rate: float = 0.0
    timeout_rate: float = 0.0

    p50_ttft: float = 0.0
    p95_ttft: float = 0.0
    p99_ttft: float = 0.0
    p50_tpot: float = 0.0
    p95_tpot: float = 0.0
    p99_tpot: float = 0.0
    p50_e2e_latency: float = 0.0
    p95_e2e_latency: float = 0.0
    p99_e2e_latency: float = 0.0

    effective_duration: float = 0.0

    def to_dict(self) -> dict:
        return {
            "goodput_output_tokens_per_second": round(self.goodput_output_tokens_per_second, 4),
            "goodput_requests_per_second": round(self.goodput_requests_per_second, 4),
            "raw_output_tokens_per_second": round(self.raw_output_tokens_per_second, 4),
            "raw_request_throughput": round(self.raw_request_throughput, 4),
            "raw_total_tokens_per_second": round(self.raw_total_tokens_per_second, 4),
            "slo_pass_rate": round(self.slo_pass_rate, 4),
            "p50_ttft": round(self.p50_ttft, 4),
            "p95_ttft": round(self.p95_ttft, 4),
            "p99_ttft": round(self.p99_ttft, 4),
            "p50_tpot": round(self.p50_tpot, 4),
            "p95_tpot": round(self.p95_tpot, 4),
            "p99_tpot": round(self.p99_tpot, 4),
            "p50_e2e_latency": round(self.p50_e2e_latency, 4),
            "p95_e2e_latency": round(self.p95_e2e_latency, 4),
            "p99_e2e_latency": round(self.p99_e2e_latency, 4),
            "success_rate": round(self.success_rate, 4),
            "error_rate": round(self.error_rate, 4),
            "timeout_rate": round(self.timeout_rate, 4),
        }


def compute_metrics(result: BenchmarkResult) -> Metrics:
    recs = result.records
    m = Metrics()
    m.total_requests = len(recs)
    m.effective_duration = result.effective_duration
    if not recs:
        return m

    successful = [r for r in recs if r.success and not r.error]
    failed = [r for r in recs if r.error or not r.success]
    timed_out = [r for r in recs if r.timeout]
    slo_ok = [r for r in recs if meets_slo(r, result.stream_supported)]

    m.successful_requests = len(successful)
    m.failed_requests = len(failed)
    m.timeout_requests = len(timed_out)
    m.slo_pass_requests = len(slo_ok)

    dur = result.effective_duration if result.effective_duration > 0 else 1e-9

    # ── goodput：仅 SLO 达标请求 ──
    goodput_out_tokens = sum(r.output_tokens for r in slo_ok)
    m.goodput_output_tokens_per_second = goodput_out_tokens / dur
    m.goodput_requests_per_second = len(slo_ok) / dur

    # ── raw：所有成功请求 ──
    raw_out_tokens = sum(r.output_tokens for r in successful)
    raw_in_tokens = sum(r.prompt_tokens for r in successful)
    m.raw_output_tokens_per_second = raw_out_tokens / dur
    m.raw_request_throughput = len(successful) / dur
    m.raw_total_tokens_per_second = (raw_out_tokens + raw_in_tokens) / dur

    # ── 比率（分母为 total_requests）──
    m.slo_pass_rate = len(slo_ok) / m.total_requests
    m.success_rate = len(successful) / m.total_requests
    m.error_rate = len(failed) / m.total_requests
    m.timeout_rate = len(timed_out) / m.total_requests

    # ── 分位延迟（仅成功请求且字段非空）──
    ttfts = [r.ttft for r in successful if r.ttft is not None]
    tpots = [r.tpot for r in successful if r.tpot is not None]
    e2es = [r.e2e_latency for r in successful if r.e2e_latency is not None]

    m.p50_ttft = _percentile(ttfts, 50)
    m.p95_ttft = _percentile(ttfts, 95)
    m.p99_ttft = _percentile(ttfts, 99)
    m.p50_tpot = _percentile(tpots, 50)
    m.p95_tpot = _percentile(tpots, 95)
    m.p99_tpot = _percentile(tpots, 99)
    m.p50_e2e_latency = _percentile(e2es, 50)
    m.p95_e2e_latency = _percentile(e2es, 95)
    m.p99_e2e_latency = _percentile(e2es, 99)
    return m


def slo_gate_pass(m: Metrics) -> bool:
    """整体 SLO 闸门：错误率 & 成功率达标（榜单准入的一部分）。"""
    return m.error_rate <= MAX_ERROR_RATE and m.success_rate >= MIN_SUCCESS_RATE
