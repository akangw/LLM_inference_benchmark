"""runner 抽象基类。所有 runner 统一返回 BenchmarkResult。"""
from __future__ import annotations

from ..config import mode_config
from .metrics import BenchmarkResult


class BaseRunner:
    name = "base"

    def supports(self, endpoint_type: str) -> bool:
        raise NotImplementedError

    def run(self, **kwargs) -> BenchmarkResult:
        raise NotImplementedError


def resolve_run_config(mode: str, dataset_profile: str | None = None) -> dict:
    cfg = mode_config(mode)
    if dataset_profile:
        cfg["dataset_profile"] = dataset_profile
    return cfg
