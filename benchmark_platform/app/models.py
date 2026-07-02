"""数据模型与状态枚举。仅标准库。"""

from __future__ import annotations

import uuid


# jobs.status（生命周期）
class Status:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


# jobs.run_status（结果语义，spec: endpoint_run_status）
class RunStatus:
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SLO_PASS = "SLO_PASS"
    SLO_FAIL = "SLO_FAIL"
    NOT_LEADERBOARD_ELIGIBLE = "NOT_LEADERBOARD_ELIGIBLE"


def new_job_id() -> str:
    return uuid.uuid4().hex[:16]
