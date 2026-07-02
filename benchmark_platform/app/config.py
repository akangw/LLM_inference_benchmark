"""平台级常量与运行配置（单一事实源）。

只依赖标准库，方便被 CLI / Web / runner 共享导入而不引入重依赖。
"""

from __future__ import annotations

import os

# ───────── 路径 ─────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
RUNS_DIR = os.path.join(ROOT_DIR, "runs")
ASSETS_DIR = os.path.join(ROOT_DIR, "benchmark_assets")
DATASET_DIR = os.path.join(ASSETS_DIR, "text")
DB_PATH = os.path.join(ROOT_DIR, "benchmark_platform.db")
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")

# ───────── 端点类型 ─────────
ENDPOINT_TYPES = ("chat_completions", "completions")
# 预留：音频接口在此扩展，但 MVP 不实现
RESERVED_ENDPOINT_TYPES = ("audio_transcriptions", "audio_translations")

# ───────── benchmark 模式 ─────────
BENCHMARK_MODES = ("smoke", "public_leaderboard", "stress")

# ───────── 数据集 ─────────
DATASET_PROFILE = "llmperf_550_150"
DATASET_FILE = os.path.join(DATASET_DIR, f"{DATASET_PROFILE}.jsonl")
DATASET_INPUT_TOKENS = 550
DATASET_MAX_OUTPUT_TOKENS = 150
DATASET_SIZE = 150
DATASET_SEED = 0

# ───────── 正式榜单固定配置 ─────────
# leaderboard_eligible 强校验依据，任何偏离都不允许进入正式榜单。
PUBLIC_LEADERBOARD_CONFIG = {
    "dataset_profile": DATASET_PROFILE,
    "total_requests": 150,
    "concurrency": 5,
    "max_output_tokens": 150,
    "temperature": 0.0,
    "top_p": 1.0,
    "stream": True,
    "request_timeout": 120,
}

# ───────── 各模式默认配置 ─────────
MODE_CONFIGS = {
    "smoke": {
        "total_requests": 3,
        "concurrency": 1,
        "max_output_tokens": DATASET_MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "top_p": 1.0,
        "stream": True,
        "request_timeout": 120,
        "dataset_profile": DATASET_PROFILE,
    },
    "public_leaderboard": {
        "total_requests": 150,
        "concurrency": 5,
        "max_output_tokens": DATASET_MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "top_p": 1.0,
        "stream": True,
        "request_timeout": 120,
        "dataset_profile": DATASET_PROFILE,
    },
    "stress": {
        # MVP 阶段先复用 llmperf_550_150，后续可扩 total_requests / concurrency
        "total_requests": 150,
        "concurrency": 10,
        "max_output_tokens": DATASET_MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "top_p": 1.0,
        "stream": True,
        "request_timeout": 120,
        "dataset_profile": DATASET_PROFILE,
    },
}

# 只有该模式产物可进入正式排行榜
LEADERBOARD_MODE = "public_leaderboard"


def mode_config(mode: str) -> dict:
    if mode not in MODE_CONFIGS:
        raise ValueError(f"未知 benchmark_mode: {mode}，可选 {BENCHMARK_MODES}")
    return dict(MODE_CONFIGS[mode])
