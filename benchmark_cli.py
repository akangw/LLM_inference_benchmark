#!/usr/bin/env python3.11
"""benchmark_cli.py —— 命令行提交/查询/导出/排行榜。

与网页共用 app.service / app.db，逻辑一致。

示例：
  python benchmark_cli.py submit --endpoint-type chat_completions --port 8010 --model-name qwen32b --mode smoke
  python benchmark_cli.py submit --endpoint-type chat_completions --base-url http://127.0.0.1:8010/v1 --model-name qwen32b --mode public_leaderboard
  python benchmark_cli.py status --job-id <job_id>
  python benchmark_cli.py export --job-id <job_id> --format json|html|csv
  python benchmark_cli.py leaderboard --endpoint-type chat_completions --format table|json|csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db, reports  # noqa: E402
from app.config import RUNS_DIR  # noqa: E402
from app.service import SubmitError, submit_job  # noqa: E402


def cmd_submit(args) -> int:
    db.init_db()
    try:
        job = submit_job(
            endpoint_type=args.endpoint_type,
            model_name=args.model_name,
            base_url=args.base_url,
            port=args.port,
            benchmark_mode=args.mode,
            dataset_profile=args.dataset_profile,
            notes=args.notes,
            api_key=args.api_key or os.environ.get("BENCH_API_KEY"),
            background=False,  # CLI 同步执行，便于脚本化
        )
    except SubmitError as e:
        print(f"[submit] 失败: {e}", file=sys.stderr)
        return 2
    # 同步执行后重新取最新状态
    final = db.get_job(job["id"])
    print(json.dumps({
        "job_id": final["id"],
        "status": final["status"],
        "run_status": final["run_status"],
        "leaderboard_eligible": bool(final["leaderboard_eligible"]),
        "ineligible_reason": final["ineligible_reason"],
        "error_message": final["error_message"],
        "run_dir": os.path.join("runs", final["id"]),
    }, ensure_ascii=False, indent=2))
    return 0 if final["status"] == "success" else 1


def cmd_status(args) -> int:
    db.init_db()
    job = db.get_job(args.job_id)
    if not job:
        print(f"[status] job 不存在: {args.job_id}", file=sys.stderr)
        return 2
    result = db.get_result_for_job(args.job_id)
    print(json.dumps({"job": job, "result": result}, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args) -> int:
    db.init_db()
    fmt = args.format
    fname = {"json": "parsed_result.json", "html": "report.html", "csv": "result.csv"}[fmt]
    path = os.path.join(RUNS_DIR, args.job_id, fname)
    if not os.path.exists(path):
        print(f"[export] 文件不存在: {path}", file=sys.stderr)
        return 2
    with open(path, "r", encoding="utf-8") as f:
        sys.stdout.write(f.read())
    return 0


def cmd_leaderboard(args) -> int:
    db.init_db()
    rows = db.leaderboard_rows(args.endpoint_type, eligible_only=not args.include_ineligible)
    if args.format == "json":
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif args.format == "csv":
        sys.stdout.write(reports.leaderboard_csv_string(rows))
    else:  # table
        if not rows:
            print("（暂无榜单结果）")
            return 0
        hdr = f'{"#":<3}{"model":<16}{"goodput_out/s":>14}{"goodput_req/s":>14}{"p95_ttft":>10}{"p95_tpot":>10}{"err":>7}'
        print(hdr)
        print("-" * len(hdr))
        for i, r in enumerate(rows, 1):
            print(f'{i:<3}{str(r["model_name"])[:15]:<16}'
                  f'{r["goodput_output_tokens_per_second"]:>14.3f}'
                  f'{r["goodput_requests_per_second"]:>14.3f}'
                  f'{r["p95_ttft"]:>10.3f}{r["p95_tpot"]:>10.4f}'
                  f'{r["error_rate"]:>7.3f}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LLM 服务 benchmark 平台 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="提交并运行一个 benchmark 任务")
    s.add_argument("--endpoint-type", required=True, choices=["chat_completions", "completions"])
    s.add_argument("--model-name", required=True)
    s.add_argument("--base-url", default=None, help="如 http://127.0.0.1:8010/v1")
    s.add_argument("--port", default=None, help="只填端口，自动转 http://127.0.0.1:<port>/v1")
    s.add_argument("--mode", default="smoke", choices=["smoke", "public_leaderboard", "stress"])
    s.add_argument("--dataset-profile", default="llmperf_550_150")
    s.add_argument("--api-key", default=None, help="可选；也可用环境变量 BENCH_API_KEY")
    s.add_argument("--notes", default=None)
    s.set_defaults(func=cmd_submit)

    st = sub.add_parser("status", help="查询任务状态")
    st.add_argument("--job-id", required=True)
    st.set_defaults(func=cmd_status)

    e = sub.add_parser("export", help="导出结果")
    e.add_argument("--job-id", required=True)
    e.add_argument("--format", required=True, choices=["json", "html", "csv"])
    e.set_defaults(func=cmd_export)

    lb = sub.add_parser("leaderboard", help="查看排行榜")
    lb.add_argument("--endpoint-type", required=True, choices=["chat_completions", "completions"])
    lb.add_argument("--format", default="table", choices=["table", "json", "csv"])
    lb.add_argument("--include-ineligible", action="store_true", help="也展示未进榜结果")
    lb.set_defaults(func=cmd_leaderboard)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
