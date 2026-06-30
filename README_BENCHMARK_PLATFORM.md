# LLM 服务 Benchmark 平台（自带端点）

把已部署的 **OpenAI 兼容推理服务**当作测试对象，自动跑标准 benchmark，输出网页 / JSON / HTML / CSV 四种结果，并维护 Chat / Completions 两个独立排行榜。

> 本平台 **不托管模型、不启动服务、不需要模型权重或路径**。你自己用 vLLM / SGLang / MindIE / TGI / LMDeploy 等启动好 OpenAI 兼容服务，把 `base_url` 或端口交给平台即可。

---

## 0. 依赖

运行在 vLLM 所在的 3.11 环境：`/usr/local/python3.11.14/bin/python3.11`。

- 必需：`fastapi`、`uvicorn`、`jinja2`、`httpx`、`python-multipart`（FastAPI 表单）。
- benchmark 核心只依赖标准库 + `httpx`，不依赖 guidellm 能否导入。
- 若缺依赖：
  ```bash
  /usr/local/python3.11.14/bin/python3.11 -m pip install fastapi uvicorn jinja2 python-multipart
  ```
  （`httpx` 通常已随 guidellm 安装。）

---

## 1. 启动 Web 服务

```bash
cd /home/u_5f35688a99/autotune/guidellm
/usr/local/python3.11.14/bin/python3.11 -m uvicorn app.main:app --host 0.0.0.0 --port 8088
```

打开 `http://<本机IP>:8088/submit`。

页面：`/submit` 提交、`/jobs` 列表、`/jobs/{id}` 详情、`/leaderboard` 排行榜首页、
`/leaderboard/chat_completions`、`/leaderboard/completions`。

---

## 2. 生成 llmperf_550_150 数据集（首次必做）

```bash
/usr/local/python3.11.14/bin/python3.11 benchmark_assets/scripts/build_llmperf_550_150.py
# 用真实 tokenizer 精确控制 550 tokens：
TOKENIZER=/path/to/Qwen3-32B-W8A8 /usr/local/python3.11.14/bin/python3.11 \
  benchmark_assets/scripts/build_llmperf_550_150.py --force
```

生成固定文件 `benchmark_assets/text/llmperf_550_150.jsonl`（150 条，seed=0，确定性复用）。

---

## 3. 网页提交 qwen32b + 910B 的 chat smoke test

1. 确认本地服务在 `http://127.0.0.1:8010/v1`。
2. 打开 `/submit`，填：
   - Endpoint 类型：`chat_completions`
   - model_name：`qwen32b`（或实际 served name）
   - Base URL：`http://127.0.0.1:8010/v1`，**或**只填端口 `8010`
   - Benchmark 模式：`smoke`
3. 提交后自动跳到 `/jobs/{job_id}`，刷新查看状态与指标。

---

## 4. CLI 提交

```bash
cd /home/u_5f35688a99/autotune/guidellm

# 只填端口（自动转 http://127.0.0.1:8010/v1），chat smoke
/usr/local/python3.11.14/bin/python3.11 benchmark_cli.py submit \
  --endpoint-type chat_completions --port 8010 --model-name qwen32b --mode smoke

# 完整 base_url，正式榜单
/usr/local/python3.11.14/bin/python3.11 benchmark_cli.py submit \
  --endpoint-type chat_completions --base-url http://127.0.0.1:8010/v1 \
  --model-name qwen32b --mode public_leaderboard

# completions
/usr/local/python3.11.14/bin/python3.11 benchmark_cli.py submit \
  --endpoint-type completions --port 8010 --model-name qwen32b --mode smoke

# 查询 / 导出 / 排行榜
/usr/local/python3.11.14/bin/python3.11 benchmark_cli.py status --job-id <job_id>
/usr/local/python3.11.14/bin/python3.11 benchmark_cli.py export --job-id <job_id> --format json
/usr/local/python3.11.14/bin/python3.11 benchmark_cli.py leaderboard --endpoint-type chat_completions --format table
```

API key（可选，不会被记录）：`--api-key sk-...` 或环境变量 `BENCH_API_KEY`。

---

## 5. 数据集方案（profile：`llmperf_550_150`，唯一 profile）

LLMPerf 风格的**固定长度合成 workload**，不是真实语料。设计目标是「只测服务性能、不测模型知识」，
所以刻意避开 ShareGPT / MMLU / GSM8K / HumanEval —— 用稳定的 prompt 分布消除内容方差，
让观测差异只反映**服务性能**，可跨引擎 / 硬件 / 量化方案比较。

固定参数（`app/config.py`，单一事实源）：

| 项 | 值 |
|---|---|
| 条数 | 150 |
| input 长度 | ≈ 550 tokens/条 |
| max_output_tokens | 150 |
| 随机种子 | seed=0（确定性，重复生成完全一致） |

### 榜单架构（零手动维护）

```
benchmark_cli.py submit
    ↓ 写入
runs/{job_id}/
    ├── report.json         ← 原始指标
    ├── report.html         ← 单任务报告
    └── report.csv
    ↓ 自动索引
guidellm/app/
    ├── db.py              ← SQLite 实时索引（runs/ → leaderboard 表）
    ├── main.py            ← FastAPI 服务 (端口 8088)
    └── templates/
        └── leaderboard_endpoint.html  ← 15秒自动刷新模板
```

**关键特性：**
- **零手动维护** — `submit` 自动写入 → SQLite 自动索引 → Web 自动展示
- **15秒自动刷新** — `<meta http-equiv="refresh" content="15">` + JS 倒计时
- **实时可见** — benchmark 跑完后约 15 秒内自动出现在榜单
- **多格式导出** — `/api/leaderboard/{endpoint_type}.json|.csv` API 端点

### 5.1 生成机制（`benchmark_assets/scripts/build_llmperf_550_150.py`）

每条 prompt = 固定主题前缀 + 中性词库随机填充，例如
`Request 000123 about latency profiling. <随机词...>.`。
词库 10 个主题循环、`random.Random(0)` 固定，所以 **150 条彼此不同但每次生成完全一致**。

长度精度分**两档**，写进每行的 `input_token_control` 字段：

- **`tokenizer`（精确档）**：设了 `TOKENIZER=/path/to/model` 时，用真实 tokenizer 把每条精确
  控制到 550 tokens（先按 0.8×550 词起步，循环补词到 ≥550，再 `encode()[:550]` 硬截）。
- **`approximate`（近似档）**：未装 tokenizer 时，按经验「英文 ≈ 0.75 词/token」→ 412 词近似 550 tokens，长度为近似值。

生成一次即固化成 `benchmark_assets/text/llmperf_550_150.jsonl`，之后只加载不重生成
（`app/benchmark/datasets.py`；缺文件会报错提示先跑 build 脚本）。

> ⚠️ **正式跑分前建议用真实 tokenizer 重建**，否则 input 长度近似、且服务不返回 usage 时 output_tokens
> 也近似，会让 goodput 绝对值带误差：
> ```bash
> TOKENIZER=/home/u_5f35688a99/vllm-ascend/models/Qwen3-32B-W8A8 \
>   /usr/local/python3.11.14/bin/python3.11 \
>   benchmark_assets/scripts/build_llmperf_550_150.py --force
> ```

---

## 6. 负载施加方式（custom HTTP runner，非 guidellm 本体）

主路径是 `app/benchmark/custom_http_runner.py`（仅依赖 httpx），**不是** guidellm 本体。
原因：本机 guidellm 需 `datasets>=4.1.0`，与 aisbench 的 `datasets<=3.6.0` 冲突，guidellm 可能无法干净导入；
guidellm runner 仅作可用性探测占位。

负载模型是**固定并发的闭环压测**（非泊松开环到达）：

- `asyncio.Semaphore(concurrency)` 控并发，150 条 prompt 一次性建 task、gather 等全部完成；
  一个请求结束才放下一个进来。
- 全程 `stream=True`（SSE），逐分片解析 —— 这是能拿到每请求 TTFT/TPOT 的前提。
- 三种模式只是并发 / 请求数不同（`MODE_CONFIGS`），共用同一数据集、`temperature=0`、`top_p=1`、`request_timeout=120s`：

| 模式 | total_requests | concurrency | 进正式榜 |
|---|---|---|---|
| smoke | 3 | 1 | 否 |
| **public_leaderboard** | **150** | **5** | **是** |
| stress | 150 | 10 | 否 |

### 6.1 单请求指标（逐 SSE 帧打点，`_one_request`）

- **TTFT** = 首个非空 delta 到达时间 − 请求开始时间（首帧同时标记 `streamed=true`）。
- **TPOT（==ITL）** = (end_time − first_token_time) / max(output_tokens−1, 1)，即首 token 之后的平均每 token 间隔。
- **E2E** = end_time − start_time。
- **token 统计**：优先用服务返回的 `usage`（completion_tokens / prompt_tokens）；服务不给 usage 时近似（≈4 字符/token 与词数取大）。
- **成功判定**：HTTP 200 且至少收到一个流式分片 → success；200 但无分片 → 按是否有内容兜底，否则 error；超时单独标 `timeout`。

---

## 7. SLO 与评价体系（`app/benchmark/slo.py` + `metrics.py`）

正式 SLO（固定，**不可被任务覆盖**，单请求级）：

| 项 | 阈值 |
|---|---|
| 单请求 TTFT | ≤ 2.0 s |
| 单请求 TPOT (ITL) | ≤ 0.2 s |
| 单请求 E2E latency | ≤ 60.0 s |
| error_rate | ≤ 1% |
| success_rate | ≥ 99% |

**主排名指标**（不使用任何自创加权综合分）：

```
goodput_output_tokens_per_second = Σ(SLO 达标请求的 output_tokens) / effective_duration
```

- 一个请求计入 goodput 需**同时**满足：success 且 not error 且 not timeout 且 stream_supported 且
  TTFT≤2s 且 TPOT≤0.2s 且 E2E≤60s（`meets_slo()`）。
- **effective_duration**（分母）= 末请求 end − 首请求 start 的墙钟时间，**不是**各请求耗时之和。
- **raw 指标**对照用**全部成功请求**（不卡 SLO），看「不限 SLO 能跑多快」。
- 分位延迟 p50/p95/p99 的 TTFT/TPOT/E2E 只对成功请求线性插值计算。

排序键（多级）：`goodput_output_tokens_per_second` ↓ → `goodput_requests_per_second` ↓ →
`p95_ttft` ↑ → `p95_tpot` ↑ → `error_rate` ↑。

辅助指标全部展示：raw_output_tokens_per_second、raw_request_throughput、
raw_total_tokens_per_second、slo_pass_rate、p50/p95/p99 TTFT/TPOT、p95/p99 E2E、
success/error/timeout rate。

---

## 8. 正式排行榜准入（`app/benchmark/eligibility.py`，强校验、不静默淘汰）

只有**全部**满足才进 `/leaderboard`：

- `benchmark_mode = public_leaderboard`
- 配置**逐字段等于** `PUBLIC_LEADERBOARD_CONFIG`：`dataset_profile = llmperf_550_150`、`total_requests = 150`、`concurrency = 5`、`max_output_tokens = 150`、`temperature = 0`、`top_p = 1`
- `stream_supported = true`，endpoint 为 chat_completions 或 completions
- benchmark 完整结束，`error_rate ≤ 1%`，`success_rate ≥ 99%`，token 统计可用

不满足者仍展示在 `/jobs` 与 `/jobs/{id}`，并给出 `ineligible_reason`（逐项列出原因，不静默淘汰）。
`smoke` / `stress` 默认不进正式榜单。

---

## 9. 结果查看

每个任务输出在 `runs/<job_id>/`：
`config.json`、`stdout.log`、`stderr.log`、`raw_result.json`、`parsed_result.json`、
`per_request_metrics.jsonl`、`result.csv`、`report.html`。

- 网页：`/jobs/{job_id}`
- JSON：`/reports/{job_id}.json`
- HTML：`/reports/{job_id}.html`
- CSV：`/reports/{job_id}.csv`
- API：`/api/jobs/{job_id}`、`/api/leaderboard/{endpoint_type}.json|csv`

---

## 10. MVP 限制

- 只支持 `/v1/chat/completions` 与 `/v1/completions`；音频接口仅预留结构（见下）。
- benchmark 主路径是自定义 HTTP runner（因本机 guidellm 的 `datasets>=4.1.0` 与 aisbench 的 `datasets<=3.6.0` 冲突）；guidellm runner 为可用性探测占位。
- 无 tokenizer 时数据集 token 长度为近似值（`input_token_control=approximate`）。
- 后台执行用线程；适合单机内网评测，未做多机/鉴权/队列持久化。
- token 统计优先用服务返回的 `usage`；服务不返回时用近似（约 4 字符/token）。

---

## 11. 扩展 audio transcription / translation

预留位已留好，按以下步骤扩展：

1. `app/config.py`：把 `audio_transcriptions` / `audio_translations` 从 `RESERVED_ENDPOINT_TYPES` 移入 `ENDPOINT_TYPES`。
2. `app/benchmark/payloads.py`：`endpoint_path()` 增加 `/audio/transcriptions`、`/audio/translations` 分支；新增 multipart 音频请求体构造。
3. `app/benchmark/custom_http_runner.py`：音频接口多为非流式，新增非流式分支记录 E2E（TTFT/TPOT 可置空）。
4. `app/benchmark/eligibility.py` + `slo.py`：为音频定义独立 SLO 与 goodput 口径。
5. 新增 `/leaderboard/audio_transcriptions` 等分榜（与现有两榜并列，互不混合）。
