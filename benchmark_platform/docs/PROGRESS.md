# PROGRESS.md — Loop Harness 进展

平台：自带端点的大模型服务 benchmark 平台 MVP（FastAPI + SQLite + Jinja2 + 自定义 HTTP runner）。 工作目录：仓库的 `benchmark_platform/` 目录。

每轮：Inspect → Plan → Implement → Run → Verify → Record → Next。

______________________________________________________________________

## Loop 1 — Inspect 环境与 GuideLLM 能力

**Inspect**

- Python：`/usr/local/python3.11.14/bin/python3.11`（vLLM/aisbench 所在环境）。
- GuideLLM 源码完整在 `src/guidellm/`，有 `openai` backend、`guidellm run` CLI（`src/guidellm/cli/run.py`）。
- 关键约束：`pyproject.toml` 显示 guidellm 依赖 `datasets>=4.1.0`，与本机 aisbench 的 `datasets<=3.6.0` 冲突（共享 3.11 环境）。→ guidellm 导入可能不干净。

**Plan / 决策**

- **主路径用自定义 HTTP runner**（仅依赖 httpx，httpx 是 guidellm 依赖，必然存在），可精确记录每请求 TTFT/TPOT。
- guidellm runner 改为 guarded-import 的可选路径（`app/benchmark/guidellm_runner.py:available()`），不可用自动回落。
- benchmark 核心（datasets/metrics/slo/runner/reports）只依赖标准库 + httpx，保证与依赖冲突解耦。

**Record**：决策写入本文件；进入 Loop 2。

______________________________________________________________________

## Loop 2 — FastAPI + SQLite 骨架

- `app/config.py`：常量单一事实源（端点类型、模式、固定方案、SLO 配置）。
- `app/db.py`：SQLite，jobs + results 两表，WAL，线程安全短连接；`has_running_job_for_endpoint` 做并发互斥。
- `app/models.py`：`Status`（queued/running/success/failed）+ `RunStatus`（QUEUED/RUNNING/SUCCESS/FAILED/SLO_PASS/SLO_FAIL/NOT_LEADERBOARD_ELIGIBLE）。
- `app/main.py`：`/submit`（GET+POST）、`/jobs` 页面。提交即入库为 queued，后台线程执行。

______________________________________________________________________

## Loop 3 — benchmark_assets + 数据集生成

- `benchmark_assets/scripts/build_llmperf_550_150.py`：seed=0，150 条固定英文 prompt，每条约 550 input tokens，max_tokens=150。有 tokenizer 用 tokenizer 精确控制（`input_token_control=tokenizer`），否则按词数近似（`approximate`）。确定性、可复用、不每次随机。
- `app/benchmark/datasets.py`：加载固定 jsonl，文件缺失给清晰报错。
- `benchmark_assets/README.md`：数据集说明。

______________________________________________________________________

## Loop 4 — runner 分发 + chat_completions benchmark

- `app/benchmark/custom_http_runner.py`：健康检查 `/models`、单条 streaming smoke 探测、并发 benchmark。逐请求记录 request_id/start/first_token/end/ttft/tpot/e2e/prompt_tokens/output_tokens/success/error/timeout/status_code/error_message/streamed。
- `app/benchmark/payloads.py`：chat 与 completions schema 严格区分；流式带 `stream_options.include_usage` 以拿精确 token。
- `app/runner.py`：编排 健康检查→stream 探测→benchmark→解析→报告→入库；全程 try/except 落盘，失败标 failed 不伪造。

______________________________________________________________________

## Loop 5 — completions benchmark + 优雅失败

- `payloads.build_completions_payload` + `endpoint_path('completions') = /completions`。
- runner 对两种 endpoint 走同一并发框架，仅 payload/解析分支不同。
- 服务不支持 completions（404/不流式）→ smoke 失败 → 任务 failed + 明确 error_message，不进榜。

______________________________________________________________________

## Loop 6 — parser / metrics / slo + eligibility

- `app/benchmark/slo.py`：固定 SLO（TTFT≤2s, TPOT≤0.2s, E2E≤60s, err≤1%, succ≥99%）；`meets_slo` 单请求 goodput 判定。
- `app/benchmark/metrics.py`：goodput_output_tokens_per_second（主）、goodput_req/s、raw 三种吞吐、各分位延迟、成功/错误/超时率。线性插值分位。无自创加权分。
- `app/benchmark/eligibility.py`：严格校验 public_leaderboard 固定方案，逐项给 ineligible_reason。
- `app/parser.py`：组装 parsed_result + results 行 + run_status。

______________________________________________________________________

## Loop 7 — reports：JSON / CSV / HTML

- `app/reports.py`：`parsed_result.json`、`result.csv`（spec 固定列序）、自包含 `report.html`（含全部分区）、`per_request_metrics.jsonl`、榜单 CSV 字符串。
- `app/main.py`：`/reports/{job_id}.json|html|csv`。

______________________________________________________________________

## Loop 8 — 排行榜页面 + API

- `db.leaderboard_rows`：jobs+results join，按 goodput_out → goodput_req → p95_ttft → p95_tpot → error_rate 排序。
- 页面 `/leaderboard`、`/leaderboard/chat_completions`、`/leaderboard/completions`；API `/api/leaderboard/{type}.json|csv`。两端点分榜，不混合。

______________________________________________________________________

## Loop 9 — 任务详情页

- `/jobs/{job_id}`：配置、状态、run_status、全部指标、SLO、goodput、产物文件存在性、错误原因、JSON/HTML/CSV/API 链接；`/api/jobs/{job_id}`。

______________________________________________________________________

## Loop 10 — benchmark_cli.py

- `submit`（base-url 或 port，同步执行便于脚本化）、`status`、`export json|html|csv`、`leaderboard table|json|csv`。与 Web 共用 `app.service`。

______________________________________________________________________

## Loop 11 — 鲁棒性与安全

- base_url/port 校验（`endpoints.normalize_base_url`）、request_timeout、同 endpoint 同时只允许一个 running job、api_key 不入库/不入日志/网页 password 输入、失败任务隔离不影响 Web、非 public_leaderboard 不进榜。

______________________________________________________________________

## 验证记录（Run / Verify）—— 实跑通过

验证用 guidellm 自带 mock OpenAI 服务（`python -m guidellm mock-server --port 8011 --ttft-ms 120 --itl-ms 15 --output-tokens 150`），避免占用真实 NPU；真实服务把端口换成 8010 即可。

| 验收项                                            | 结果                                                                      |
| ------------------------------------------------- | ------------------------------------------------------------------------- |
| 生成 `llmperf_550_150.jsonl`                      | ✅ 150 行，seed=0，确定性                                                 |
| 全部 app 模块导入                                 | ✅ 无报错；guidellm 探测可用                                              |
| CLI chat smoke（port→URL 归一）                   | ✅ success；run_status=NOT_LEADERBOARD_ELIGIBLE（smoke 不进榜，原因明确） |
| CLI completions smoke                             | ✅ success                                                                |
| chat public_leaderboard（150 req/并发5）          | ✅ success，run_status=SLO_PASS，**leaderboard_eligible=true**            |
| completions public_leaderboard                    | ✅ success，eligible=true                                                 |
| 8 个产物文件                                      | ✅ config/stdout/stderr/raw/parsed/per_request(=150行)/csv/html 全生成    |
| 逐请求 TTFT/TPOT/E2E                              | ✅ 流式逐分片记录，stream_supported=true                                  |
| Web 启动 + 页面                                   | ✅ /submit /jobs /leaderboard/\* 全 200                                   |
| Web POST /submit                                  | ✅ 303 跳转 /jobs/{id}                                                    |
| /reports/{id}.json\|csv\|html                     | ✅ 全部可下载                                                             |
| /api/jobs/{id}、/api/leaderboard/{type}.json\|csv | ✅                                                                        |
| 两榜分离                                          | ✅ chat 榜只含 chat，completions 榜只含 completions                       |
| 排序                                              | ✅ 按 goodput_output_tokens_per_second 降序                               |
| 优雅失败（端口 9999）                             | ✅ status=failed，error_message 明确，不伪造成功                          |
| 非法端口 99999                                    | ✅ submit 阶段拒绝（越界）                                                |
| api_key 安全                                      | ✅ config.json 只存 api_key_provided 布尔，不存值                         |
| 404 缺失 job                                      | ✅                                                                        |

最终库内：jobs=6（5 success + 1 故意 failed），chat 榜 1 条、completions 榜 1 条。

使用模板：`/home/u_5f35688a99/autotune/guidellm-docx/benchmark_platform_usage_template.md`。

### 已知限制

- 无 tokenizer 时数据集 token 为近似（`input_token_control=approximate`）。
- benchmark 主路径为自定义 httpx 流式 runner（精确逐请求指标）；guidellm runner 当前为可用性探测占位。
- 后台执行用线程，适合单机内网；未做多机/鉴权/队列持久化。
