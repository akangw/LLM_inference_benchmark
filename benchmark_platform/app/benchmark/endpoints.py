"""endpoint 规范化、端口转换、base_url 脱敏与校验。

只依赖标准库。被 Web、CLI、runner 共享。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


class EndpointError(ValueError):
    pass


def normalize_base_url(base_url: str | None, port: int | str | None = None) -> str:
    """把用户输入规范化成 http://host:port/v1。

    规则：
    - 只给 port -> http://127.0.0.1:<port>/v1
    - 给完整 base_url -> 校验 scheme/host，补 /v1（若结尾不是 /v1 也不报错，尊重用户路径）
    """
    if not base_url and port is None:
        raise EndpointError("必须提供 base_url 或 port 其中之一")

    if not base_url and port is not None:
        p = _validate_port(port)
        return f"http://127.0.0.1:{p}/v1"

    base_url = base_url.strip()
    # 用户可能直接填了纯数字端口到 base_url 字段
    if re.fullmatch(r"\d+", base_url):
        p = _validate_port(base_url)
        return f"http://127.0.0.1:{p}/v1"

    if not re.match(r"^https?://", base_url):
        base_url = "http://" + base_url

    parsed = urlparse(base_url)
    if not parsed.hostname:
        raise EndpointError(f"无法解析 base_url 的 host: {base_url}")
    if parsed.scheme not in ("http", "https"):
        raise EndpointError(f"base_url scheme 必须是 http/https: {base_url}")

    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")


def _validate_port(port: int | str) -> int:
    try:
        p = int(port)
    except (TypeError, ValueError):
        raise EndpointError(f"端口必须是整数: {port!r}")
    if not (1 <= p <= 65535):
        raise EndpointError(f"端口越界 [1,65535]: {p}")
    return p


def mask_base_url(base_url: str) -> str:
    """脱敏：保留 scheme+host+port+path，去掉任何 userinfo/query/敏感片段。

    本平台 base_url 不含密钥（api_key 单独传），这里主要是统一展示形态。
    """
    try:
        parsed = urlparse(base_url)
    except Exception:
        return base_url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def models_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/models"
