"""自定义 HTTP runner（主用路径，仅依赖 httpx）。

为什么是主路径：本机共享 3.11 环境里 guidellm 需要 datasets>=4.1.0，与 aisbench 的
datasets<=3.6.0 冲突，guidellm 可能无法干净导入。自定义 runner 仅依赖 httpx
（httpx 是 guidellm 的依赖，必然存在），且能精确记录每请求 TTFT/TPOT，故作为主路径。

职责：
- 健康检查（GET /models）
- 单次 smoke streaming 请求（探测 stream 是否真生效）
- 并发跑完整 benchmark，逐请求记录观测值
- 统一返回 BenchmarkResult
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from .endpoints import models_url
from .metrics import BenchmarkResult
from .payloads import build_payload, endpoint_path
from .slo import RequestRecord


def _approx_tokens(text: str) -> int:
    """无 usage 时的近似 token 数：约 4 字符/token，至少按词数兜底。"""
    if not text:
        return 0
    by_char = max(1, len(text) // 4)
    by_word = max(1, len(text.split()))
    return max(by_char, by_word)


async def check_models(
    base_url: str, api_key: str | None, timeout: float = 10.0
) -> dict:
    """GET {base_url}/models。返回 {status, http_status, models, error}。"""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    out = {"status": "failed", "http_status": None, "models": [], "error": None}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(models_url(base_url), headers=headers)
            out["http_status"] = resp.status_code
            if resp.status_code == 200:
                out["status"] = "success"
                try:
                    data = resp.json()
                    out["models"] = [
                        m.get("id") for m in data.get("data", []) if isinstance(m, dict)
                    ]
                except Exception:
                    pass
            else:
                out["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _parse_stream_line(line: str) -> dict | None:
    """解析 SSE 行：返回 JSON 对象，或 None（[DONE]/空行/非 data 行）。"""
    if not line:
        return None
    if line.startswith("data:"):
        line = line[len("data:") :].strip()
    else:
        return None
    if line == "[DONE]" or not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _extract_delta_text(obj: dict, endpoint_type: str) -> str:
    """从一帧 SSE chunk 抽取本帧新增文本。"""
    choices = obj.get("choices") or []
    if not choices:
        return ""
    ch = choices[0]
    if endpoint_type == "chat_completions":
        delta = ch.get("delta") or {}
        return delta.get("content") or ""
    # completions
    return ch.get("text") or ""


def _extract_usage(obj: dict) -> dict | None:
    u = obj.get("usage")
    if isinstance(u, dict) and (
        u.get("completion_tokens") is not None or u.get("prompt_tokens") is not None
    ):
        return u
    return None


async def _one_request(
    client: httpx.AsyncClient,
    request_id: str,
    url: str,
    headers: dict,
    payload: dict,
    endpoint_type: str,
    timeout: float,
) -> RequestRecord:
    """发一条 streaming 请求，逐分片记录 TTFT/TPOT/E2E。"""
    rec = RequestRecord(request_id=request_id)
    rec.start_time = time.monotonic()
    text_parts: list[str] = []
    n_chunks = 0
    usage = None
    try:
        async with client.stream(
            "POST", url, headers=headers, json=payload, timeout=timeout
        ) as resp:
            rec.status_code = resp.status_code
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "replace")[:300]
                rec.error = True
                rec.success = False
                rec.error_message = f"HTTP {resp.status_code}: {body}"
                rec.end_time = time.monotonic()
                rec.e2e_latency = rec.end_time - rec.start_time
                return rec
            async for raw in resp.aiter_lines():
                obj = _parse_stream_line(raw)
                if obj is None:
                    continue
                u = _extract_usage(obj)
                if u:
                    usage = u
                delta = _extract_delta_text(obj, endpoint_type)
                if delta:
                    if rec.first_token_time is None:
                        rec.first_token_time = time.monotonic()
                        rec.streamed = True
                    text_parts.append(delta)
                    n_chunks += 1
        rec.end_time = time.monotonic()
        rec.e2e_latency = rec.end_time - rec.start_time

        full_text = "".join(text_parts)
        # token 统计：优先 usage，否则近似
        if usage:
            rec.output_tokens = int(
                usage.get("completion_tokens") or 0
            ) or _approx_tokens(full_text)
            rec.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        else:
            rec.output_tokens = _approx_tokens(full_text)
            rec.prompt_tokens = 0

        if rec.first_token_time is not None:
            rec.ttft = rec.first_token_time - rec.start_time
            # TPOT：首 token 之后的平均每 token 间隔
            gen_time = rec.end_time - rec.first_token_time
            denom = max(rec.output_tokens - 1, 1)
            rec.tpot = gen_time / denom if rec.output_tokens > 1 else gen_time
            rec.success = True
            rec.error = False
        else:
            # 200 但没有任何分片（可能 stream=false 被忽略 / 空响应）
            rec.success = rec.output_tokens > 0
            rec.error = not rec.success
            if rec.error:
                rec.error_message = "无流式分片且无内容"
    except (httpx.TimeoutException, asyncio.TimeoutError):
        rec.timeout = True
        rec.error = True
        rec.success = False
        rec.error_message = f"请求超时 (>{timeout}s)"
        rec.end_time = time.monotonic()
        rec.e2e_latency = rec.end_time - rec.start_time
    except Exception as e:  # noqa: BLE001
        rec.error = True
        rec.success = False
        rec.error_message = f"{type(e).__name__}: {e}"
        rec.end_time = time.monotonic()
        rec.e2e_latency = rec.end_time - rec.start_time
    return rec


async def smoke_request(
    base_url: str,
    endpoint_type: str,
    model_name: str,
    prompt: str,
    api_key: str | None,
    max_tokens: int = 16,
    timeout: float = 60.0,
) -> RequestRecord:
    """单条 streaming smoke 请求，用于探测 stream 是否真生效。"""
    url = base_url.rstrip("/") + endpoint_path(endpoint_type)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = build_payload(
        endpoint_type, model_name, prompt, max_tokens, 0.0, 1.0, True
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await _one_request(
            client, "smoke", url, headers, payload, endpoint_type, timeout
        )


async def run_benchmark_async(
    base_url: str,
    endpoint_type: str,
    model_name: str,
    prompts: list[dict],
    concurrency: int,
    max_output_tokens: int,
    temperature: float,
    top_p: float,
    request_timeout: float,
    api_key: str | None,
    stream_supported: bool,
) -> BenchmarkResult:
    """并发执行 benchmark。prompts 为 [{id, prompt, max_tokens}, ...]。"""
    url = base_url.rstrip("/") + endpoint_path(endpoint_type)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    sem = asyncio.Semaphore(max(1, concurrency))
    records: list[RequestRecord] = []
    limits = httpx.Limits(
        max_connections=concurrency + 5, max_keepalive_connections=concurrency + 5
    )

    async with httpx.AsyncClient(timeout=request_timeout, limits=limits) as client:

        async def worker(idx: int, item: dict) -> RequestRecord:
            async with sem:
                payload = build_payload(
                    endpoint_type,
                    model_name,
                    item["prompt"],
                    item.get("max_tokens", max_output_tokens),
                    temperature,
                    top_p,
                    True,
                )
                rid = item.get("id", f"req_{idx:06d}")
                return await _one_request(
                    client, rid, url, headers, payload, endpoint_type, request_timeout
                )

        wall_start = time.monotonic()
        tasks = [asyncio.create_task(worker(i, it)) for i, it in enumerate(prompts)]
        records = await asyncio.gather(*tasks)
        wall_end = time.monotonic()

    # 有效运行时间：墙钟（首请求开始到末请求结束）
    starts = [r.start_time for r in records if r.start_time]
    ends = [r.end_time for r in records if r.end_time]
    if starts and ends:
        effective = max(ends) - min(starts)
    else:
        effective = wall_end - wall_start

    usage_available = any(r.prompt_tokens > 0 for r in records)
    result = BenchmarkResult(
        records=list(records),
        effective_duration=effective,
        stream_supported=stream_supported,
        usage_available=usage_available,
        prompt_tokens_count_source="usage" if usage_available else "none",
        output_tokens_count_source="usage" if usage_available else "approximate",
        runner_name="custom_http",
    )
    return result


def run_benchmark(**kwargs) -> BenchmarkResult:
    """同步包装。"""
    return asyncio.run(run_benchmark_async(**kwargs))
