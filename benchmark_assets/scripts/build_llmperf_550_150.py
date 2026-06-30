#!/usr/bin/env python3.11
"""离线生成固定 LLMPerf-style 合成数据集 llmperf_550_150.jsonl。

要求（spec）：
- 固定 seed=0，生成 150 条固定英文 prompt，每条约 550 input tokens，max_tokens=150。
- 若本地能加载 tokenizer，则用 tokenizer 精确控制到 ~550 tokens，标记 control=tokenizer。
- 否则用固定英文段落模板按词数近似，标记 control=approximate。
- 一旦生成即固化复用，不每次随机。重复运行结果完全一致（确定性）。

用法：
  python benchmark_assets/scripts/build_llmperf_550_150.py            # 默认
  python benchmark_assets/scripts/build_llmperf_550_150.py --force    # 覆盖已存在文件
  TOKENIZER=/path/to/model python ...build_llmperf_550_150.py         # 指定 tokenizer
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

SEED = 0
N = 150
TARGET_TOKENS = 550
MAX_OUTPUT_TOKENS = 150

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.dirname(HERE)                 # benchmark_assets/
ROOT = os.path.dirname(ASSETS)                 # guidellm/
OUT_DIR = os.path.join(ASSETS, "text")
OUT_FILE = os.path.join(OUT_DIR, "llmperf_550_150.jsonl")

# 固定英文词库（中性、与模型知识无关，纯长度填充用）
WORD_BANK = (
    "the system processes requests across many concurrent streams while the scheduler "
    "balances throughput and latency under a fixed service level objective the inference "
    "engine batches tokens and emits them incrementally so that downstream consumers can "
    "measure time to first token and inter token latency for every individual request the "
    "benchmark harness records start time first token time and end time then derives end to "
    "end latency from these observations the workload is synthetic and fixed length to keep "
    "comparisons fair across different engines hardware platforms and quantization schemes a "
    "stable prompt distribution removes data variance so that observed differences reflect "
    "serving performance rather than prompt content the platform never evaluates model "
    "knowledge it only measures how fast a deployed endpoint can serve a known load profile"
).split()

# 固定主题前缀，让 150 条彼此不同但完全确定
TOPICS = [
    "throughput analysis", "latency profiling", "concurrency scaling", "token streaming",
    "scheduler behavior", "memory utilization", "queue dynamics", "batch formation",
    "tail latency", "service objectives",
]


def try_load_tokenizer():
    path = os.environ.get("TOKENIZER")
    if not path:
        return None, "approximate"
    try:
        from transformers import AutoTokenizer  # type: ignore
        tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        return tok, "tokenizer"
    except Exception as e:  # noqa: BLE001
        print(f"[build] tokenizer 加载失败，回落近似: {e}", file=sys.stderr)
        return None, "approximate"


def make_prompt_words(rng: random.Random, idx: int, n_words: int) -> str:
    topic = TOPICS[idx % len(TOPICS)]
    head = f"Request {idx:06d} about {topic}. "
    words = [rng.choice(WORD_BANK) for _ in range(n_words)]
    return head + " ".join(words) + "."


def build_with_tokenizer(tok, rng: random.Random, idx: int) -> str:
    # 先估词数，再按 token 微调到 ~TARGET_TOKENS
    text = make_prompt_words(rng, idx, int(TARGET_TOKENS * 0.8))
    for _ in range(40):
        n = len(tok.encode(text))
        if n >= TARGET_TOKENS:
            break
        text += " " + " ".join(rng.choice(WORD_BANK) for _ in range(max(1, (TARGET_TOKENS - n))))
    # 截断到恰好 TARGET_TOKENS
    ids = tok.encode(text)[:TARGET_TOKENS]
    return tok.decode(ids)


def build_approximate(rng: random.Random, idx: int) -> str:
    # 经验：英文约 0.75 词/token -> 550 token ≈ 410 词，取 412 稳定偏上
    n_words = int(TARGET_TOKENS * 0.75)
    return make_prompt_words(rng, idx, n_words)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(OUT_FILE) and not args.force:
        print(f"[build] 已存在 {OUT_FILE}（{_count_lines(OUT_FILE)} 行）。--force 可覆盖。")
        return 0

    tok, control = try_load_tokenizer()
    rng = random.Random(SEED)

    rows = []
    for i in range(1, N + 1):
        if tok is not None:
            prompt = build_with_tokenizer(tok, rng, i)
        else:
            prompt = build_approximate(rng, i)
        rows.append({
            "id": f"llmperf_{i:06d}",
            "prompt": prompt,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "input_token_control": control,
        })

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    approx_tokens = sum(len(r["prompt"].split()) for r in rows) / len(rows)
    print(f"[build] 写入 {OUT_FILE}")
    print(f"[build] {N} 条 prompt，control={control}，平均词数≈{approx_tokens:.0f}，seed={SEED}")
    if control == "approximate":
        print("[build] 注意：无 tokenizer，input_token_control=approximate（按词数近似 550 tokens）")
    return 0


def _count_lines(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


if __name__ == "__main__":
    raise SystemExit(main())
