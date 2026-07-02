"""构造 OpenAI 兼容请求体。chat_completions 与 completions 严格区分。

只依赖标准库。预留音频接口扩展位（不实现）。
"""

from __future__ import annotations


def build_chat_payload(
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    stream: bool,
) -> dict:
    """/v1/chat/completions 请求体。"""
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": stream,
    }
    if stream:
        # 要求服务在流式结束帧带 usage（vLLM/OpenAI 支持），用于精确 token 统计
        payload["stream_options"] = {"include_usage": True}
    return payload


def build_completions_payload(
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    stream: bool,
) -> dict:
    """/v1/completions 请求体。"""
    payload = {
        "model": model_name,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def endpoint_path(endpoint_type: str) -> str:
    """endpoint_type -> 相对路径（拼到 base_url 之后）。"""
    if endpoint_type == "chat_completions":
        return "/chat/completions"
    if endpoint_type == "completions":
        return "/completions"
    # 预留：audio_transcriptions / audio_translations 在此扩展
    raise ValueError(f"MVP 不支持的 endpoint_type: {endpoint_type}")


def build_payload(
    endpoint_type: str,
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    stream: bool,
) -> dict:
    if endpoint_type == "chat_completions":
        return build_chat_payload(
            model_name, prompt, max_tokens, temperature, top_p, stream
        )
    if endpoint_type == "completions":
        return build_completions_payload(
            model_name, prompt, max_tokens, temperature, top_p, stream
        )
    raise ValueError(f"MVP 不支持的 endpoint_type: {endpoint_type}")
