# benchmark_assets — 固定合成数据集

本目录存放正式榜单使用的 **LLMPerf-style 固定长度合成数据集**。

## 为什么用固定合成数据

- 只评估**服务性能**，不评估模型知识能力，故不用 MMLU/GSM8K/HumanEval。
- 不用 ShareGPT、不每次随机：固定 prompt 分布消除数据方差，保证不同引擎/硬件/量化方式之间可比。

## 文件

- `text/llmperf_550_150.jsonl` — 正式榜单数据集（150 条，每条约 550 input tokens，max_tokens=150）。
- `scripts/build_llmperf_550_150.py` — 离线生成脚本（seed=0，确定性，重复运行结果一致）。

## 数据格式

```json
{"id": "llmperf_000001", "prompt": "... ~550 input tokens ...", "max_tokens": 150, "input_token_control": "approximate"}
```

- `input_token_control = tokenizer`：用真实 tokenizer 精确控制到 550 tokens。
- `input_token_control = approximate`：无 tokenizer，按英文词数近似（约 0.75 词/token）。

## 生成

```bash
# 默认（无 tokenizer 时近似）
/usr/local/python3.11.14/bin/python3.11 benchmark_assets/scripts/build_llmperf_550_150.py

# 用真实 tokenizer 精确控制 token 长度
TOKENIZER=/path/to/Qwen3-32B-W8A8 /usr/local/python3.11.14/bin/python3.11 \
  benchmark_assets/scripts/build_llmperf_550_150.py --force
```

生成后**固化复用**，正式 benchmark 不再重新随机生成。
