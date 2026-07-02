"""GuideLLM runner（可选路径，best-effort）。

本机共享 3.11 环境里 guidellm 需要 datasets>=4.1.0，与 aisbench 的 datasets<=3.6.0
冲突，可能无法干净导入。因此本 runner 用 guarded import，导入失败时 available()=False，
runner 分发自动回落到 custom_http_runner。MVP 不强依赖 guidellm 能跑通。
"""

from __future__ import annotations


def available() -> tuple[bool, str]:
    """探测 guidellm 是否可用。返回 (ok, reason)。"""
    try:
        import guidellm  # noqa: F401
        from guidellm.benchmark import benchmark_generative_text  # noqa: F401

        return True, getattr(__import__("guidellm"), "__version__", "unknown")
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# MVP：guidellm 直跑接口预留位。当前以 custom_http_runner 为主路径，
# 这里只暴露可用性探测，供 runner.py 决策与 /jobs 详情展示。
