# LLM 服务 Benchmark 平台

面向 **OpenAI 兼容推理服务**的 SLO 感知 benchmark 平台。测量已部署服务的真实性能（TTFT / TPOT / E2E 延迟、goodput 吞吐），产出 JSON / CSV / HTML 报告，并按固定方案维护可比排行榜。

> 平台**只测已启动的服务**，不托管模型、不加载权重、不要模型路径 —— 你把服务跑起来，平台去压测它。

技术栈：FastAPI + SQLite + Jinja2 + 自定义 httpx 流式 runner。除可选的 guidellm 探测外，核心仅依赖标准库 + httpx。

______________________________________________________________________

## 目录结构

```
benchmark_platform/
├── app/                  # FastAPI 应用（Web + 核心逻辑）
│   ├── benchmark/        # runner / metrics / slo / eligibility / datasets
│   └── templates/        # 网页模板
├── benchmark_assets/     # 固定合成数据集 + 生成脚本
├── benchmark_cli.py      # 命令行入口
├── scripts/              # 多场景编排脚本
├── docs/                 # 文档（本文件）
├── runs/<job_id>/        # 每个任务的产物（运行时生成）
└── benchmark_platform.db # SQLite 库（运行时生成）
```

______________________________________________________________________

## 环境准备

平台运行在 vLLM/aisbench 所在的 Python 3.11 解释器下（不使用 `uv`）：

```bash
export PY=/usr/local/python3.11.14/bin/python3.11
cd benchmark_platform     # 所有命令均在此目录下执行
```

依赖：`fastapi`、`uvicorn`、`jinja2`、`httpx`（httpx 由 guidellm 传递保证一定存在）。

### 一次性准备：生成固定数据集

```bash
# 默认（无 tokenizer 时按词数近似 ~550 tokens）
$PY benchmark_assets/scripts/build_llmperf_550_150.py

# 有真实 tokenizer 时精确控制到 550 tokens
TOKENIZER=/path/to/Qwen3-32B-W8A8 $PY benchmark_assets/scripts/build_llmperf_550_150.py --force
```

生成 `benchmark_assets/text/llmperf_550_150.jsonl`（150 条，seed=0，确定性，固化复用）。

______________________________________________________________________

## 使用方式一：网页

```bash
$PY -m uvicorn app.main:app --host 0.0.0.0 --port 8088
# 浏览器打开 http://<本机IP>:8088/submit
```

| 页面                            | 说明                                      |
| ------------------------------- | ----------------------------------------- |
| `/submit`                       | 提交 benchmark 任务                       |
| `/jobs`                         | 任务列表                                  |
| `/jobs/{id}`                    | 任务详情（配置、指标、SLO、产物下载链接） |
| `/leaderboard`                  | 排行榜入口                                |
| `/leaderboard/chat_completions` | Chat 榜                                   |
| `/leaderboard/completions`      | Completions 榜                            |

**提交示例**（本地 qwen32b on 910B）：

| 字段           | 值                                                |
| -------------- | ------------------------------------------------- |
| Endpoint 类型  | `chat_completions`                                |
| model_name     | `qwen32b`（服务实际 served name）                 |
| Base URL       | `http://127.0.0.1:8010/v1`，**或**只填端口 `8010` |
| Benchmark 模式 | `smoke`（先验证）/ `public_leaderboard`（进榜）   |
| 数据集         | `llmperf_550_150`                                 |
| Notes          | `engine: vLLM; hardware: 4x910B; quant: W8A8`     |

提交后自动跳转 `/jobs/{job_id}`，刷新查看状态与指标。

______________________________________________________________________

## 使用方式二：命令行（CLI）

CLI 与网页共用同一核心（`app.service` / `app.db`），逻辑一致；CLI 为**同步执行**，便于脚本化。

### 提交任务

```bash
# A) 只填端口的 chat smoke（快速验证 endpoint 可用）
$PY benchmark_cli.py submit \
  --endpoint-type chat_completions --port 8010 --model-name qwen32b --mode smoke

# B) 完整 base_url 的正式榜单（150 请求 / 并发 5）
$PY benchmark_cli.py submit \
  --endpoint-type chat_completions --base-url http://127.0.0.1:8010/v1 \
  --model-name qwen32b --mode public_leaderboard \
  --notes "engine: vLLM; hardware: 4x910B; quant: W8A8"

# C) completions 接口
$PY benchmark_cli.py submit \
  --endpoint-type completions --port 8010 --model-name qwen32b --mode smoke
```

API key（可选，**绝不入库/不写日志**）：加 `--api-key sk-...` 或设环境变量 `BENCH_API_KEY`。

### 查询 / 导出 / 排行榜

```bash
# 查询任务状态（完整 JSON）
$PY benchmark_cli.py status --job-id <job_id>

# 导出结果（写到 stdout，可重定向）
$PY benchmark_cli.py export --job-id <job_id> --format json > result.json
$PY benchmark_cli.py export --job-id <job_id> --format csv  > result.csv
$PY benchmark_cli.py export --job-id <job_id> --format html > report.html

# 排行榜（分端点类型）
$PY benchmark_cli.py leaderboard --endpoint-type chat_completions --format table
$PY benchmark_cli.py leaderboard --endpoint-type completions      --format json
$PY benchmark_cli.py leaderboard --endpoint-type chat_completions --format csv
```

______________________________________________________________________

## HTTP API（机器可读）

```
GET /reports/{job_id}.json        # parsed_result.json
GET /reports/{job_id}.html        # 自包含 HTML 报告
GET /reports/{job_id}.csv         # 结果 CSV
GET /api/jobs/{job_id}            # job + result JSON
GET /api/leaderboard/{type}.json  # 排行榜 JSON
GET /api/leaderboard/{type}.csv   # 排行榜 CSV
GET /healthz                      # 健康检查 {"status":"ok"}
```

`{type}` 为 `chat_completions` 或 `completions`。

______________________________________________________________________

## Benchmark 模式

| 模式                 | 请求数 | 并发 | 进榜 | 用途                   |
| -------------------- | ------ | ---- | ---- | ---------------------- |
| `smoke`              | 3      | 1    | ❌   | 快速验证 endpoint 可用 |
| `public_leaderboard` | 150    | 5    | ✅   | 正式榜单               |
| `stress`             | 150    | 10   | ❌   | 压力探测               |

`smoke` / `stress` 仍产出完整 JSON/HTML/CSV 报告并可在 `/jobs/{id}` 查看，只是不进榜。

______________________________________________________________________

## 评分与进榜规则

- **主排名指标**：`goodput_output_tokens_per_second` = 满足 SLO 的成功请求 output tokens / 有效运行时间。**无任何自创加权综合分**。
- **固定 SLO**（不可被任务覆盖）：TTFT ≤ 2s，TPOT ≤ 0.2s，E2E ≤ 60s，error ≤ 1%，success ≥ 99%。
- **排序**：goodput_out ↓ → goodput_req ↓ → p95_ttft ↑ → p95_tpot ↑ → error_rate ↑。
- **进榜条件**（须全满足）：`public_leaderboard` 模式 + `llmperf_550_150` 数据集 + 150 请求 + 并发 5 + max_tokens 150 + temperature 0 + top_p 1 + stream 真生效 + 完整结束 + err ≤ 1% + succ ≥ 99%。任何偏离都给出明确 `ineligible_reason`。
- Chat 与 Completions **分别独立成榜**，不混合。

______________________________________________________________________

## 产物文件

每个任务在 `runs/<job_id>/` 下生成：

| 文件                        | 内容                                                      |
| --------------------------- | --------------------------------------------------------- |
| `config.json`               | 任务配置（含 `api_key_provided` 布尔，**不含 key 明文**） |
| `stdout.log` / `stderr.log` | 执行日志                                                  |
| `raw_result.json`           | runner 选择、健康检查、smoke 探测原始信息                 |
| `parsed_result.json`        | 解析后的完整指标 + eligibility + run_status               |
| `per_request_metrics.jsonl` | 逐请求 TTFT/TPOT/E2E/token/状态                           |
| `result.csv`                | 固定列序的结果表                                          |
| `report.html`               | 自包含可视化报告                                          |

______________________________________________________________________

## 没有真实服务时：用 mock 跑通全流程（自检）

```bash
# 启动 guidellm 自带 mock OpenAI 服务（可调 TTFT/ITL/输出长度）
$PY -m guidellm mock-server --host 127.0.0.1 --port 8011 \
  --model qwen32b-mock --ttft-ms 120 --itl-ms 15 --output-tokens 150 &

# 对它跑正式榜单
$PY benchmark_cli.py submit --endpoint-type chat_completions \
  --port 8011 --model-name qwen32b-mock --mode public_leaderboard
```

______________________________________________________________________

## 多场景编排（可选）

`scripts/run_three_benchmarks.py`、`scripts/run_three_reliable.py` 演示了「启动 vLLM → 跑榜 → 释放显存」的三档参数顺序编排。这些脚本依赖外部 `autotune` 环境的 `start_service.sh` / `stop_service.sh`（脚本内 `AUTOTUNE` 常量需按实际部署环境填写），仅作参考。

______________________________________________________________________

## 安全与鲁棒性

- **API key**：只在内存传递，不入库、不写日志、不落盘；`config.json` 仅记录 `api_key_provided` 布尔。网页用 password 输入框。
- **并发互斥**：同一 `base_url` + `endpoint_type` 同时只允许一个运行中的任务。
- **优雅失败**：任何阶段失败都落盘错误原因并把任务标 `failed`，**绝不伪造成功**；失败任务隔离，不影响 Web 与其他任务。
- **base_url / port 校验**：非法端口在提交阶段即拒绝。

______________________________________________________________________

## 已知限制

- 无 tokenizer 时数据集 token 数为近似（`input_token_control=approximate`）。
- 后台执行用线程，适合单机内网；未做多机 / 鉴权 / 队列持久化。
- guidellm runner 当前为可用性探测占位，主路径始终用自定义 httpx 流式 runner（精确逐请求指标）。
