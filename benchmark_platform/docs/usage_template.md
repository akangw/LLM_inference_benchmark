# LLM 服务 Benchmark 平台 · 使用模板

> 一步步照抄即可。平台只测**已启动的 OpenAI 兼容服务**,不托管模型、不要权重/路径。 代码在仓库的 `benchmark_platform/` 目录,详版文档见 `benchmark_platform/docs/README.md`。

环境:`/usr/local/python3.11.14/bin/python3.11`(下文简称 `PY`)。

**所有命令均在 `benchmark_platform/` 目录下执行**：

```bash
export PY=/usr/local/python3.11.14/bin/python3.11
cd benchmark_platform  # 进入平台目录
```

______________________________________________________________________

## 模板 0 · 一次性准备:生成固定数据集

```bash
$PY benchmark_assets/scripts/build_llmperf_550_150.py
# 输出: benchmark_assets/text/llmperf_550_150.jsonl (150 条, seed=0, 固定复用)
# 有真实 tokenizer 时(精确 550 tokens):
# TOKENIZER=/path/to/Qwen3-32B-W8A8 $PY benchmark_assets/scripts/build_llmperf_550_150.py --force
```

______________________________________________________________________

## 模板 1 · 启动网页服务

```bash
$PY -m uvicorn app.main:app --host 0.0.0.0 --port 8088
# 浏览器打开 http://<本机IP>:8088/submit
```

页面导航:`/submit` 提交 · `/jobs` 列表 · `/jobs/{id}` 详情 · `/leaderboard` · `/leaderboard/chat_completions` · `/leaderboard/completions`。

______________________________________________________________________

## 模板 2 · 网页提交(以本地 qwen32b + 910B 为例)

1. 确保推理服务已在跑,例如 `http://127.0.0.1:8010/v1`。

2. 打开 `/submit`,填写:

   | 字段           | 值                                                   |
   | -------------- | ---------------------------------------------------- |
   | Endpoint 类型  | `chat_completions`                                   |
   | model_name     | `qwen32b`(实际 served name)                          |
   | Base URL       | `http://127.0.0.1:8010/v1` **或**只填端口 `8010`     |
   | Benchmark 模式 | `smoke`(先验证)/ `public_leaderboard`(进榜)          |
   | 数据集         | `llmperf_550_150`                                    |
   | Notes          | `engine: vLLM; hardware: 4x910B; quantization: W8A8` |

3. 提交后自动跳到 `/jobs/{job_id}`,刷新看状态与指标。

______________________________________________________________________

## 模板 3 · CLI 提交

```bash
# A) 只填端口的 chat smoke(快速验证 endpoint)
$PY benchmark_cli.py submit \
  --endpoint-type chat_completions --port 8010 --model-name qwen32b --mode smoke

# B) 完整 base_url 的正式榜单(150 请求 / 并发 5)
$PY benchmark_cli.py submit \
  --endpoint-type chat_completions --base-url http://127.0.0.1:8010/v1 \
  --model-name qwen32b --mode public_leaderboard \
  --notes "engine: vLLM; hardware: 4x910B; quantization: W8A8"

# C) completions 接口
$PY benchmark_cli.py submit \
  --endpoint-type completions --port 8010 --model-name qwen32b --mode smoke
```

API key(可选,绝不入库/日志):加 `--api-key sk-...` 或设 `BENCH_API_KEY` 环境变量。

______________________________________________________________________

## 模板 4 · 查询 / 导出 / 排行榜

```bash
# 查询任务状态(完整 JSON)
$PY benchmark_cli.py status --job-id <job_id>

# 导出结果(写到 stdout,可重定向)
$PY benchmark_cli.py export --job-id <job_id> --format json   > result.json
$PY benchmark_cli.py export --job-id <job_id> --format csv    > result.csv
$PY benchmark_cli.py export --job-id <job_id> --format html   > report.html

# 排行榜(分端点类型)
$PY benchmark_cli.py leaderboard --endpoint-type chat_completions --format table
$PY benchmark_cli.py leaderboard --endpoint-type completions      --format json
$PY benchmark_cli.py leaderboard --endpoint-type chat_completions --format csv
```

网页/HTTP 等价入口:

```
GET /reports/{job_id}.json   /reports/{job_id}.html   /reports/{job_id}.csv
GET /api/jobs/{job_id}
GET /api/leaderboard/chat_completions.json   .../completions.json
GET /api/leaderboard/chat_completions.csv    .../completions.csv
```

______________________________________________________________________

## 模板 5 · 没有真实服务时,用 mock 跑通全流程(自检)

```bash
# 启 guidellm 自带 mock OpenAI 服务(可调 TTFT/ITL/输出长度)
$PY -m guidellm mock-server --host 127.0.0.1 --port 8011 \
  --model qwen32b-mock --ttft-ms 120 --itl-ms 15 --output-tokens 150 &

# 对它跑正式榜单
$PY benchmark_cli.py submit --endpoint-type chat_completions \
  --port 8011 --model-name qwen32b-mock --mode public_leaderboard
```

______________________________________________________________________

## 评分速查

- **主排名**:`goodput_output_tokens_per_second` = 满足 SLO 的成功请求 output tokens / 有效运行时间。无任何自创加权综合分。
- **SLO**:TTFT ≤ 2s,TPOT ≤ 0.2s,E2E ≤ 60s,error ≤ 1%,success ≥ 99%。
- **排序**:goodput_out ↓ → goodput_req ↓ → p95_ttft ↑ → p95_tpot ↑ → error_rate ↑。
- **进榜条件**(全满足):`public_leaderboard` + `llmperf_550_150` + 150 请求 + 并发 5 + max_tokens 150 + temp 0 + top_p 1 + stream 真生效 + 完整结束 + err≤1% + succ≥99%。 smoke / stress 永不进榜,但仍出全套 JSON/HTML/CSV 报告并可在 `/jobs/{id}` 查看。

______________________________________________________________________

## 产物位置

每个任务在 `runs/<job_id>/`:`config.json`、`stdout.log`、`stderr.log`、 `raw_result.json`、`parsed_result.json`、`per_request_metrics.jsonl`、 `result.csv`、`report.html`。
