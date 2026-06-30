"""自带端点的大模型服务 benchmark 平台 (MVP)。

本平台不托管、不启动模型。测试对象是用户已部署好的 OpenAI 兼容推理服务。
平台负责：接收 endpoint -> 健康检查 -> 跑 benchmark -> 解析 -> 出 JSON/HTML/CSV -> 排行榜。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
