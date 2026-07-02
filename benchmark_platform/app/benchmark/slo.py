"""SLO 阈值与 goodput 判定（正式榜单固定 SLO）。

只依赖标准库。一个请求是否计入 goodput、是否满足 SLO，全部在此判定，
确保 metrics / runner / report 用同一套规则。
"""
from __future__ import annotations

from dataclasses import dataclass

# ───────── 正式 SLO（固定，不可被任务覆盖）─────────
SLO_TTFT = 2.0      # 秒，Time To First Token
SLO_TPOT = 0.2      # 秒，Time Per Output Token (== ITL)
SLO_E2E = 60.0      # 秒，End-to-End latency（工程保护阈值）
MAX_ERROR_RATE = 0.01     # 1%
MIN_SUCCESS_RATE = 0.99   # 99%


@dataclass
class RequestRecord:
    """单请求观测值。runner 产出，metrics / slo 消费。"""
    request_id: str
    start_time: float = 0.0
    first_token_time: float | None = None
    end_time: float | None = None
    ttft: float | None = None          # 秒
    tpot: float | None = None          # 秒/token
    e2e_latency: float | None = None   # 秒
    prompt_tokens: int = 0
    output_tokens: int = 0
    success: bool = False
    error: bool = True
    timeout: bool = False
    status_code: int | None = None
    error_message: str | None = None
    streamed: bool = False  # 该请求是否真的收到流式分片

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "start_time": self.start_time,
            "first_token_time": self.first_token_time,
            "end_time": self.end_time,
            "ttft": self.ttft,
            "tpot": self.tpot,
            "e2e_latency": self.e2e_latency,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "success": self.success,
            "error": self.error,
            "timeout": self.timeout,
            "status_code": self.status_code,
            "error_message": self.error_message,
            "streamed": self.streamed,
        }


def meets_slo(rec: RequestRecord, stream_supported: bool) -> bool:
    """单请求是否计入 goodput（必须同时满足全部条件）。"""
    if not rec.success or rec.error or rec.timeout:
        return False
    if not stream_supported:
        return False
    if rec.ttft is None or rec.tpot is None or rec.e2e_latency is None:
        return False
    return (
        rec.ttft <= SLO_TTFT
        and rec.tpot <= SLO_TPOT
        and rec.e2e_latency <= SLO_E2E
    )


def slo_summary() -> dict:
    return {
        "slo_ttft": SLO_TTFT,
        "slo_tpot": SLO_TPOT,
        "slo_e2e": SLO_E2E,
        "max_error_rate": MAX_ERROR_RATE,
        "min_success_rate": MIN_SUCCESS_RATE,
    }
