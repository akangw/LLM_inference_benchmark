"""LLMPerf-style 固定合成数据集的加载与（必要时）生成。

正式榜单只用固定文件 benchmark_assets/text/llmperf_550_150.jsonl。
本模块负责加载；真正的离线生成在 benchmark_assets/scripts/build_llmperf_550_150.py。
只依赖标准库。
"""

from __future__ import annotations

import json
import os

from ..config import (
    DATASET_FILE,
    DATASET_MAX_OUTPUT_TOKENS,
    DATASET_PROFILE,
)


class DatasetError(RuntimeError):
    pass


def load_dataset(
    profile: str = DATASET_PROFILE, limit: int | None = None
) -> list[dict]:
    """加载固定 jsonl 数据集，返回 [{id, prompt, max_tokens}, ...]。

    profile 当前只支持 llmperf_550_150。文件缺失时报清晰错误（提示先运行 build 脚本）。
    """
    if profile != DATASET_PROFILE:
        raise DatasetError(
            f"未知 dataset_profile: {profile}，MVP 仅支持 {DATASET_PROFILE}"
        )
    if not os.path.exists(DATASET_FILE):
        raise DatasetError(
            f"数据集文件不存在: {DATASET_FILE}\n"
            f"请先运行: python benchmark_assets/scripts/build_llmperf_550_150.py"
        )
    items: list[dict] = []
    with open(DATASET_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "prompt" not in obj:
                raise DatasetError(f"数据集行缺少 prompt 字段: {obj}")
            obj.setdefault("max_tokens", DATASET_MAX_OUTPUT_TOKENS)
            items.append(obj)
    if not items:
        raise DatasetError(f"数据集文件为空: {DATASET_FILE}")
    if limit is not None:
        items = items[:limit]
    return items
