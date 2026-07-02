"""FastAPI 应用：网页提交、任务列表/详情、排行榜、报告与 JSON/CSV API。

启动：
  /usr/local/python3.11.14/bin/python3.11 -m uvicorn app.main:app --host 0.0.0.0 --port 8088
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates

from . import db, reports
from .config import ENDPOINT_TYPES, RUNS_DIR, TEMPLATES_DIR
from .service import SubmitError, submit_job

app = FastAPI(title="LLM Service Benchmark Platform", version="0.1.0")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
def _startup():
    db.init_db()
    os.makedirs(RUNS_DIR, exist_ok=True)


# ───────── 页面 ─────────
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return RedirectResponse(url="/submit")


@app.get("/submit", response_class=HTMLResponse)
def submit_page(request: Request):
    return templates.TemplateResponse("submit.html", {"request": request})


@app.post("/submit")
def submit_action(
    endpoint_type: str = Form(...),
    model_name: str = Form(...),
    base_url: str = Form(""),
    port: str = Form(""),
    api_key: str = Form(""),
    benchmark_mode: str = Form("smoke"),
    dataset_profile: str = Form("llmperf_550_150"),
    notes: str = Form(""),
):
    try:
        job = submit_job(
            endpoint_type=endpoint_type,
            model_name=model_name,
            base_url=base_url or None,
            port=port or None,
            benchmark_mode=benchmark_mode,
            dataset_profile=dataset_profile or None,
            notes=notes or None,
            api_key=api_key or None,
            background=True,
        )
    except SubmitError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/jobs/{job['id']}", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    jobs = db.list_jobs()
    return templates.TemplateResponse("jobs.html", {"request": request, "jobs": jobs})


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")
    result = db.get_result_for_job(job_id)
    run_dir = os.path.join(RUNS_DIR, job_id)
    files = {}
    for name in ("config.json", "stdout.log", "stderr.log", "raw_result.json",
                 "parsed_result.json", "per_request_metrics.jsonl",
                 "result.csv", "report.html"):
        p = os.path.join(run_dir, name)
        files[name] = os.path.exists(p)
    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "job": job, "result": result, "files": files},
    )


@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard_home(request: Request):
    return templates.TemplateResponse("leaderboard.html", {"request": request})


@app.get("/leaderboard/{endpoint_type}", response_class=HTMLResponse)
def leaderboard_endpoint(request: Request, endpoint_type: str):
    if endpoint_type not in ENDPOINT_TYPES:
        raise HTTPException(status_code=404, detail="未知 endpoint_type")
    rows = db.leaderboard_rows(endpoint_type, eligible_only=True)
    return templates.TemplateResponse(
        "leaderboard_endpoint.html",
        {"request": request, "endpoint_type": endpoint_type, "rows": rows},
    )


# ───────── 报告文件 ─────────
def _read_run_file(job_id: str, filename: str) -> str:
    path = os.path.join(RUNS_DIR, job_id, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"{filename} 不存在")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/reports/{job_id}.json")
def report_json(job_id: str):
    return Response(content=_read_run_file(job_id, "parsed_result.json"),
                    media_type="application/json")


@app.get("/reports/{job_id}.html", response_class=HTMLResponse)
def report_html(job_id: str):
    return HTMLResponse(content=_read_run_file(job_id, "report.html"))


@app.get("/reports/{job_id}.csv")
def report_csv(job_id: str):
    return Response(content=_read_run_file(job_id, "result.csv"), media_type="text/csv")


# ───────── 机器可读 API ─────────
@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")
    result = db.get_result_for_job(job_id)
    return JSONResponse({"job": job, "result": result})


@app.get("/api/leaderboard/{endpoint_type}.json")
def api_leaderboard_json(endpoint_type: str):
    if endpoint_type not in ENDPOINT_TYPES:
        raise HTTPException(status_code=404, detail="未知 endpoint_type")
    rows = db.leaderboard_rows(endpoint_type, eligible_only=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return JSONResponse({"endpoint_type": endpoint_type, "rows": rows})


@app.get("/api/leaderboard/{endpoint_type}.csv")
def api_leaderboard_csv(endpoint_type: str):
    if endpoint_type not in ENDPOINT_TYPES:
        raise HTTPException(status_code=404, detail="未知 endpoint_type")
    rows = db.leaderboard_rows(endpoint_type, eligible_only=True)
    return PlainTextResponse(reports.leaderboard_csv_string(rows), media_type="text/csv")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
