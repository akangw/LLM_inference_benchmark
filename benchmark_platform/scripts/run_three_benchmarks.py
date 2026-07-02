#!/usr/bin/env python3.11
"""
三场景顺序 benchmark 编排脚本。

流程（每场景）：
  1. 写 /tmp/bench_<tag>/chosen_params.json
  2. bash start_service.sh 启动 vLLM（port 8010）
  3. benchmark_cli.py submit --mode public_leaderboard
  4. bash stop_service.sh 释放 HBM

三个场景（Qwen3-32B-W8A8 on 4×910B3）：
  A — enforce-eager 基准（关图，seqs=128，无特殊优化）
  B — PIECEWISE 图编译 + 权重预取 + FlashComm（seqs=32，PIECEWISE 上限）
  C — PIECEWISE 全量优化（seqs=32，fuse_allreduce + QK融合 + MLP预取 + cpu绑核 + batched↑）

注意：PIECEWISE + seqs >= 64 在本硬件必崩（NPU stream 耗尽）→ B/C 强制 seqs=32。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from os.path import abspath, dirname

PY = "/usr/local/python3.11.14/bin/python3.11"
# 自动定位本仓库 benchmark_platform/ 目录（脚本在 benchmark_platform/scripts/ 下）
PLATFORM = dirname(dirname(abspath(__file__)))
CLI = f"{PLATFORM}/benchmark_cli.py"

# 外部 autotune 环境目录（包含 start_service.sh / stop_service.sh）
# 需按实际部署环境填写，与本仓库位置无关
AUTOTUNE = "/home/u_5f35688a99/autotune"

SCENARIOS = [
    {
        "tag": "A_piecewise_conservative",
        "label": "场景 A · PIECEWISE 保守基准（seqs=16，无优化）",
        "notes": "engine: vLLM 0.14.1; hardware: 4×910B3; quant: W8A8; "
        "graph: PIECEWISE; max-num-seqs: 16(保守); "
        "max-num-batched-tokens: 8192; gpu-mem-util: 0.90; no Ascend opts",
        "params": {
            "cli": {
                "tensor-parallel-size": 4,
                "quantization": "ascend",
                "distributed-executor-backend": "mp",
                "block-size": 128,
                "max-num-seqs": 16,
                "max-num-batched-tokens": 8192,
                "max-model-len": 8192,
                "gpu-memory-utilization": 0.90,
                "enforce-eager": False,
                "enable-chunked-prefill": True,
            },
            "compilation_config": {
                "cudagraph_mode": "PIECEWISE",
                "cudagraph_num_of_warmups": 0,
            },
            "additional_config": {
                "weight_prefetch_config.enabled": False,
                "pa_shape_list": None,
                "ascend_compilation_config.fuse_allreduce_rms": False,
                "enable_cpu_binding": False,
            },
            "env": {
                "VLLM_ASCEND_ENABLE_FLASHCOMM1": "0",
                "VLLM_ASCEND_ENABLE_NZ": "1",
                "VLLM_ASCEND_ENABLE_PREFETCH_MLP": "0",
                "HCCL_OP_EXPANSION_MODE": "AIV",
                "TASK_QUEUE_ENABLE": "1",
            },
            "selection_reason": "benchmark_scenario_A",
        },
    },
    {
        "tag": "B_piecewise_base_opt",
        "label": "场景 B · PIECEWISE 图编译 + 权重预取",
        "notes": "engine: vLLM 0.14.1; hardware: 4×910B3; quant: W8A8; "
        "graph: PIECEWISE; max-num-seqs: 32(上限); "
        "weight_prefetch+FlashComm1; gpu-mem-util: 0.94",
        "params": {
            "cli": {
                "tensor-parallel-size": 4,
                "quantization": "ascend",
                "distributed-executor-backend": "mp",
                "block-size": 128,
                "max-num-seqs": 32,  # PIECEWISE 硬上限：>=64 必崩
                "max-num-batched-tokens": 16384,
                "max-model-len": 8192,
                "gpu-memory-utilization": 0.94,
                "enforce-eager": False,
                "enable-chunked-prefill": True,
            },
            "compilation_config": {
                "cudagraph_mode": "PIECEWISE",
                "cudagraph_num_of_warmups": 1,
            },
            "additional_config": {
                "weight_prefetch_config.enabled": True,
                "pa_shape_list": None,
                "ascend_compilation_config.fuse_allreduce_rms": False,
                "enable_cpu_binding": False,
            },
            "env": {
                "VLLM_ASCEND_ENABLE_FLASHCOMM1": "1",
                "VLLM_ASCEND_ENABLE_NZ": "1",
                "VLLM_ASCEND_ENABLE_PREFETCH_MLP": "0",
                "HCCL_OP_EXPANSION_MODE": "AIV",
                "TASK_QUEUE_ENABLE": "1",
            },
            "selection_reason": "benchmark_scenario_B",
        },
    },
    {
        "tag": "C_piecewise_full_opt",
        "label": "场景 C · PIECEWISE 全量优化",
        "notes": "engine: vLLM 0.14.1; hardware: 4×910B3; quant: W8A8; "
        "graph: PIECEWISE; max-num-seqs: 32(上限); "
        "fuse_allreduce+QK融合+MLP预取+cpu绑核; batched-tokens: 24576; gpu-mem-util: 0.94",
        "params": {
            "cli": {
                "tensor-parallel-size": 4,
                "quantization": "ascend",
                "distributed-executor-backend": "mp",
                "block-size": 128,
                "max-num-seqs": 32,  # PIECEWISE 硬上限
                "max-num-batched-tokens": 24576,
                "max-model-len": 8192,
                "gpu-memory-utilization": 0.94,
                "enforce-eager": False,
                "enable-chunked-prefill": True,
                "async-scheduling": True,
            },
            "compilation_config": {
                "cudagraph_mode": "PIECEWISE",
                "cudagraph_num_of_warmups": 2,
                "pass_config.enable_qk_norm_rope_fusion": True,
            },
            "additional_config": {
                "weight_prefetch_config.enabled": True,
                "pa_shape_list": None,
                "ascend_compilation_config.fuse_allreduce_rms": True,
                "enable_cpu_binding": True,
            },
            "env": {
                "VLLM_ASCEND_ENABLE_FLASHCOMM1": "1",
                "VLLM_ASCEND_ENABLE_NZ": "1",
                "VLLM_ASCEND_ENABLE_PREFETCH_MLP": "1",
                "VLLM_ASCEND_BALANCE_SCHEDULING": "1",
                "HCCL_OP_EXPANSION_MODE": "AIV",
                "TASK_QUEUE_ENABLE": "1",
            },
            "selection_reason": "benchmark_scenario_C",
        },
    },
]


def run(cmd: list[str], cwd: str | None = None, timeout: int = 900) -> tuple[int, str]:
    """运行命令，返回 (exit_code, stdout+stderr)。"""
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )
    out = result.stdout + result.stderr
    return result.returncode, out


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def wait_port(port: int, timeout: int = 600) -> bool:
    """等待端口就绪（由 start_service.sh 负责，这里只是轮询保险）。"""
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            time.sleep(2)
    return False


def main() -> int:
    results: list[dict] = []

    for sc in SCENARIOS:
        tag = sc["tag"]
        label = sc["label"]
        notes = sc["notes"]
        log(f"{'=' * 60}")
        log(f"开始 {label}")
        log(f"{'=' * 60}")

        # ── 1. 写 chosen_params.json ──
        run_dir = f"/tmp/bench_{tag}"
        os.makedirs(run_dir, exist_ok=True)
        params_file = f"{run_dir}/chosen_params.json"
        sc["params"]["run_id"] = tag
        with open(params_file, "w") as f:
            json.dump(sc["params"], f, indent=2, ensure_ascii=False)
        log(f"written: {params_file}")

        # ── 2. 启动 vLLM 服务 ──
        log("启动 vLLM…")
        rc, out = run(
            ["bash", f"{AUTOTUNE}/scripts/start_service.sh", run_dir],
            cwd=AUTOTUNE,
            timeout=700,
        )
        print(out[-3000:])  # 只打末尾，避免太长
        if rc != 0:
            log(f"[ERROR] 场景 {tag} 服务启动失败 (rc={rc})，跳过 benchmark。")
            results.append(
                {"tag": tag, "service_rc": rc, "bench_rc": None, "job_id": None}
            )
            # 尝试清理
            run(
                ["bash", f"{AUTOTUNE}/scripts/stop_service.sh", "120"],
                cwd=AUTOTUNE,
                timeout=200,
            )
            continue

        log("vLLM 就绪 ✓  开始 benchmark (public_leaderboard, 150 req / 并发5)…")

        # ── 3. 跑正式榜单 benchmark ──
        bench_cmd = [
            PY,
            CLI,
            "submit",
            "--endpoint-type",
            "chat_completions",
            "--port",
            "8010",
            "--model-name",
            "qwen3-32b-w8a8",
            "--mode",
            "public_leaderboard",
            "--notes",
            notes,
        ]
        rc_b, out_b = run(bench_cmd, cwd=PLATFORM, timeout=900)
        # 去掉 torch_npu 告警
        clean = "\n".join(
            l
            for l in out_b.splitlines()
            if "Warning" not in l and "warnings.warn" not in l
        )
        print(clean)

        job_id = None
        try:
            import re

            m = re.search(r'"job_id":\s*"([a-f0-9]+)"', clean)
            if m:
                job_id = m.group(1)
        except Exception:
            pass

        log(f"benchmark 结束: rc={rc_b}  job_id={job_id}")
        results.append(
            {"tag": tag, "service_rc": 0, "bench_rc": rc_b, "job_id": job_id}
        )

        # ── 4. 停服务、释放 HBM ──
        log("停止 vLLM，等待 HBM 释放…")
        run(
            ["bash", f"{AUTOTUNE}/scripts/stop_service.sh", "180"],
            cwd=AUTOTUNE,
            timeout=240,
        )
        log("HBM 释放完毕，准备下一个场景。")
        time.sleep(5)

    # ── 汇总 ──
    print("\n" + "=" * 60)
    print("三场景汇总")
    print("=" * 60)
    for r in results:
        status = (
            "✅ 成功"
            if r["bench_rc"] == 0
            else (
                "⚠️ bench_rc={}".format(r["bench_rc"])
                if r["bench_rc"] is not None
                else "❌ 服务启动失败"
            )
        )
        print(f"  {r['tag']:<35} {status}  job_id={r['job_id']}")

    print("\n查看榜单:")
    print(f"  {PY} {CLI} leaderboard --endpoint-type chat_completions --format table")
    print("或网页: http://<ip>:8088/leaderboard/chat_completions")
    return 0 if all(r["bench_rc"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
