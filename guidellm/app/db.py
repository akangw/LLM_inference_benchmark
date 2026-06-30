"""SQLite 持久层。jobs 表 + results 表。仅依赖标准库 sqlite3。

设计：单文件 SQLite，WAL 模式，线程安全连接（check_same_thread=False + 每次操作短连接）。
api_key 绝不入库、绝不入日志。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import DB_PATH

_lock = threading.Lock()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _lock, get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                endpoint_type TEXT NOT NULL,
                model_name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                base_url_masked TEXT NOT NULL,
                status TEXT NOT NULL,
                benchmark_mode TEXT NOT NULL,
                dataset_profile TEXT NOT NULL,
                total_requests INTEGER,
                concurrency INTEGER,
                max_output_tokens INTEGER,
                temperature REAL,
                top_p REAL,
                stream INTEGER,
                request_timeout INTEGER,
                created_at REAL,
                started_at REAL,
                finished_at REAL,
                error_message TEXT,
                run_dir TEXT,
                leaderboard_eligible INTEGER DEFAULT 0,
                ineligible_reason TEXT,
                notes TEXT,
                run_status TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                endpoint_type TEXT,
                model_name TEXT,
                benchmark_mode TEXT,
                dataset_profile TEXT,
                total_requests INTEGER,
                concurrency INTEGER,
                max_output_tokens INTEGER,
                raw_request_throughput REAL,
                raw_output_tokens_per_second REAL,
                raw_total_tokens_per_second REAL,
                goodput_requests_per_second REAL,
                goodput_output_tokens_per_second REAL,
                p50_ttft REAL, p95_ttft REAL, p99_ttft REAL,
                p50_tpot REAL, p95_tpot REAL, p99_tpot REAL,
                p50_e2e_latency REAL, p95_e2e_latency REAL, p99_e2e_latency REAL,
                success_rate REAL, error_rate REAL, timeout_rate REAL,
                slo_pass_rate REAL,
                stream_supported INTEGER,
                usage_available INTEGER,
                prompt_tokens_count_source TEXT,
                output_tokens_count_source TEXT,
                leaderboard_eligible INTEGER,
                ineligible_reason TEXT,
                json_report_path TEXT,
                html_report_path TEXT,
                csv_report_path TEXT,
                raw_report_path TEXT,
                created_at REAL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_results_job ON results(job_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            """
        )


def insert_job(job: dict) -> None:
    cols = [
        "id", "endpoint_type", "model_name", "base_url", "base_url_masked",
        "status", "benchmark_mode", "dataset_profile", "total_requests",
        "concurrency", "max_output_tokens", "temperature", "top_p", "stream",
        "request_timeout", "created_at", "started_at", "finished_at",
        "error_message", "run_dir", "leaderboard_eligible", "ineligible_reason",
        "notes", "run_status",
    ]
    placeholders = ",".join("?" for _ in cols)
    vals = [job.get(c) for c in cols]
    with _lock, get_conn() as conn:
        conn.execute(
            f"INSERT INTO jobs ({','.join(cols)}) VALUES ({placeholders})", vals
        )


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with _lock, get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)


def get_job(job_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def has_running_job_for_endpoint(base_url: str, endpoint_type: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE base_url=? AND endpoint_type=? "
            "AND status IN ('queued','running')",
            (base_url, endpoint_type),
        ).fetchone()
        return row["c"] > 0


def insert_result(result_row: dict) -> None:
    cols = list(result_row.keys())
    placeholders = ",".join("?" for _ in cols)
    vals = [result_row[c] for c in cols]
    with _lock, get_conn() as conn:
        conn.execute(
            f"INSERT INTO results ({','.join(cols)}) VALUES ({placeholders})", vals
        )


def get_result_for_job(job_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM results WHERE job_id=? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return dict(row) if row else None


def leaderboard_rows(endpoint_type: str, eligible_only: bool = True) -> list[dict]:
    """连接 jobs+results，按 spec 排序返回正式榜单行。"""
    where = "j.endpoint_type=?"
    params: list = [endpoint_type]
    if eligible_only:
        where += " AND r.leaderboard_eligible=1"
    sql = f"""
        SELECT r.*, j.base_url_masked, j.notes, j.benchmark_mode AS job_mode,
               j.created_at AS job_created_at
        FROM results r JOIN jobs j ON r.job_id=j.id
        WHERE {where}
        ORDER BY r.goodput_output_tokens_per_second DESC,
                 r.goodput_requests_per_second DESC,
                 r.p95_ttft ASC,
                 r.p95_tpot ASC,
                 r.error_rate ASC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def now() -> float:
    return time.time()
