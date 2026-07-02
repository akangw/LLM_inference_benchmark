"""生成 parsed_result.json / result.csv / report.html。仅标准库。

CSV summary 列严格按 spec 顺序。HTML 报告自包含（无外链），含全部分区。
"""

from __future__ import annotations

import csv
import html
import io
import json
import os

from .benchmark.slo import slo_summary

# CSV summary 表头（spec 固定顺序）
CSV_COLUMNS = [
    "job_id",
    "endpoint_type",
    "model_name",
    "benchmark_mode",
    "dataset_profile",
    "total_requests",
    "concurrency",
    "goodput_output_tokens_per_second",
    "goodput_requests_per_second",
    "raw_output_tokens_per_second",
    "raw_request_throughput",
    "raw_total_tokens_per_second",
    "slo_pass_rate",
    "p50_ttft",
    "p95_ttft",
    "p99_ttft",
    "p50_tpot",
    "p95_tpot",
    "p99_tpot",
    "p95_e2e_latency",
    "p99_e2e_latency",
    "success_rate",
    "error_rate",
    "timeout_rate",
    "leaderboard_eligible",
    "ineligible_reason",
]


def _clean_for_json(parsed: dict) -> dict:
    d = dict(parsed)
    d.pop("_metrics_obj", None)
    return d


def write_parsed_json(run_dir: str, parsed: dict) -> str:
    path = os.path.join(run_dir, "parsed_result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_clean_for_json(parsed), f, ensure_ascii=False, indent=2)
    return path


def write_csv(run_dir: str, parsed: dict) -> str:
    path = os.path.join(run_dir, "result.csv")
    m = parsed["metrics"]
    row = {
        "job_id": parsed["job_id"],
        "endpoint_type": parsed["endpoint_type"],
        "model_name": parsed["model_name"],
        "benchmark_mode": parsed["benchmark_mode"],
        "dataset_profile": parsed["dataset_profile"],
        "total_requests": parsed["total_requests"],
        "concurrency": parsed["concurrency"],
        "goodput_output_tokens_per_second": m["goodput_output_tokens_per_second"],
        "goodput_requests_per_second": m["goodput_requests_per_second"],
        "raw_output_tokens_per_second": m["raw_output_tokens_per_second"],
        "raw_request_throughput": m["raw_request_throughput"],
        "raw_total_tokens_per_second": m["raw_total_tokens_per_second"],
        "slo_pass_rate": m["slo_pass_rate"],
        "p50_ttft": m["p50_ttft"],
        "p95_ttft": m["p95_ttft"],
        "p99_ttft": m["p99_ttft"],
        "p50_tpot": m["p50_tpot"],
        "p95_tpot": m["p95_tpot"],
        "p99_tpot": m["p99_tpot"],
        "p95_e2e_latency": m["p95_e2e_latency"],
        "p99_e2e_latency": m["p99_e2e_latency"],
        "success_rate": m["success_rate"],
        "error_rate": m["error_rate"],
        "timeout_rate": m["timeout_rate"],
        "leaderboard_eligible": parsed["leaderboard_eligible"],
        "ineligible_reason": parsed["ineligible_reason"] or "",
    }
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerow(row)
    return path


def write_per_request(run_dir: str, result) -> str:
    """per_request_metrics.jsonl。result 为 BenchmarkResult。"""
    path = os.path.join(run_dir, "per_request_metrics.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for rec in result.records:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
    return path


def leaderboard_csv_string(rows: list[dict]) -> str:
    """榜单导出 CSV 字符串。"""
    buf = io.StringIO()
    if not rows:
        w = csv.writer(buf)
        w.writerow(["rank"] + CSV_COLUMNS)
        return buf.getvalue()
    fields = ["rank"] + [c for c in CSV_COLUMNS if c in rows[0]]
    # 补充榜单特有列
    for extra in ("base_url_masked", "notes", "p50_ttft", "p95_e2e_latency"):
        if extra in rows[0] and extra not in fields:
            fields.append(extra)
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for i, r in enumerate(rows, 1):
        rr = dict(r)
        rr["rank"] = i
        w.writerow(rr)
    return buf.getvalue()


def _row(label: str, value) -> str:
    return (
        f"<tr><th>{html.escape(str(label))}</th><td>{html.escape(str(value))}</td></tr>"
    )


def render_report_html(parsed: dict, job: dict, run_dir: str) -> str:
    """生成自包含 report.html。"""
    m = parsed["metrics"]
    slo = slo_summary()
    eligible = parsed["leaderboard_eligible"]
    badge_color = "#137333" if eligible else "#b3261e"
    badge_text = "进入正式排行榜" if eligible else "不进入正式排行榜"

    def sec(title, rows_html):
        return f"<section><h2>{html.escape(title)}</h2><table>{rows_html}</table></section>"

    job_summary = (
        _row("Job ID", parsed["job_id"])
        + _row("Run Status", parsed.get("run_status", ""))
        + _row("Benchmark Mode", parsed["benchmark_mode"])
        + _row("Dataset Profile", parsed["dataset_profile"])
        + _row("Runner", parsed.get("runner_name", ""))
        + _row("Effective Duration (s)", parsed.get("effective_duration", ""))
    )
    endpoint_info = (
        _row("Endpoint Type", parsed["endpoint_type"])
        + _row("Model", parsed["model_name"])
        + _row("Base URL (masked)", parsed["base_url_masked"])
        + _row("Notes", job.get("notes") or "")
    )
    bench_config = (
        _row("Total Requests", parsed["total_requests"])
        + _row("Concurrency", parsed["concurrency"])
        + _row("Max Output Tokens", parsed["max_output_tokens"])
        + _row("Stream Supported", parsed["stream_supported"])
    )
    goodput = (
        _row("Goodput Output tok/s", m["goodput_output_tokens_per_second"])
        + _row("Goodput Req/s", m["goodput_requests_per_second"])
        + _row("SLO Pass Rate", m["slo_pass_rate"])
    )
    raw = (
        _row("Raw Output tok/s", m["raw_output_tokens_per_second"])
        + _row("Raw Req/s", m["raw_request_throughput"])
        + _row("Raw Total tok/s", m["raw_total_tokens_per_second"])
    )
    latency = (
        _row("P50 TTFT (s)", m["p50_ttft"])
        + _row("P95 TTFT (s)", m["p95_ttft"])
        + _row("P99 TTFT (s)", m["p99_ttft"])
        + _row("P50 TPOT (s)", m["p50_tpot"])
        + _row("P95 TPOT (s)", m["p95_tpot"])
        + _row("P99 TPOT (s)", m["p99_tpot"])
        + _row("P95 E2E (s)", m["p95_e2e_latency"])
        + _row("P99 E2E (s)", m["p99_e2e_latency"])
    )
    reliability = (
        _row("Success Rate", m["success_rate"])
        + _row("Error Rate", m["error_rate"])
        + _row("Timeout Rate", m["timeout_rate"])
    )
    slo_res = (
        _row("SLO TTFT", f"<= {slo['slo_ttft']}s")
        + _row("SLO TPOT", f"<= {slo['slo_tpot']}s")
        + _row("SLO E2E", f"<= {slo['slo_e2e']}s")
        + _row("Max Error Rate", slo["max_error_rate"])
        + _row("Min Success Rate", slo["min_success_rate"])
        + _row("SLO Gate Pass", parsed.get("slo_gate_pass", ""))
    )
    elig = _row("Leaderboard Eligible", eligible) + _row(
        "Ineligible Reason", parsed["ineligible_reason"] or "—"
    )

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>Benchmark Report {html.escape(parsed["job_id"])}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;color:#202124;background:#f8f9fa}}
h1{{font-size:22px}} h2{{font-size:16px;margin:18px 0 6px;border-left:4px solid #1a73e8;padding-left:8px}}
table{{border-collapse:collapse;width:100%;background:#fff;margin-bottom:6px}}
th,td{{border:1px solid #e0e0e0;padding:6px 10px;text-align:left;font-size:13px}}
th{{background:#f1f3f4;width:240px}}
.badge{{display:inline-block;padding:4px 12px;border-radius:12px;color:#fff;font-size:13px;background:{badge_color}}}
.links a{{margin-right:12px}}
</style></head><body>
<h1>Benchmark Report <span class="badge">{html.escape(badge_text)}</span></h1>
{sec("Job Summary", job_summary)}
{sec("Endpoint Info", endpoint_info)}
{sec("Benchmark Config", bench_config)}
{sec("Goodput Metrics（主排名依据）", goodput)}
{sec("Raw Throughput Metrics", raw)}
{sec("Latency Metrics", latency)}
{sec("Reliability Metrics", reliability)}
{sec("SLO Result", slo_res)}
{sec("Leaderboard Eligibility", elig)}
<section><h2>Links</h2><div class="links">
<a href="/reports/{html.escape(parsed["job_id"])}.json">JSON</a>
<a href="/reports/{html.escape(parsed["job_id"])}.csv">CSV</a>
<a href="/jobs/{html.escape(parsed["job_id"])}">Job Detail</a>
</div></section>
</body></html>"""


def write_report_html(run_dir: str, parsed: dict, job: dict) -> str:
    path = os.path.join(run_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_report_html(parsed, job, run_dir))
    return path
