"""benchmark 子包：数据集、runner、指标、SLO。

核心原则：除 guidellm_runner 外，本子包只依赖标准库 + httpx，
保证在 guidellm/datasets 依赖冲突时仍可独立运行。
"""
