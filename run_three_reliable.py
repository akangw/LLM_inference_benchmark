#!/usr/bin/env python3.11
"""
三档可靠参数顺序 benchmark 编排脚本（第二版）。

三档全部使用已验证可跑的 PIECEWISE + seqs=32 组合：
  R1: batched=8192,  无 Ascend 优化      → 保守基准
  R2: batched=16384, weight_prefetch+FlashComm → 平衡优化（场景B已验证）
  R3: batched=24576, fuse_allreduce+MLP_prefetch+cpu_bind+FlashComm → 全量（排除崩溃项）

两个已知崩溃项（已排除）：
  - async-scheduling=true → EngineCore crash (async_llm.py)
  - pass_config.enable_qk_norm_rope_fusion=true → hidden_states IndexError
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time

PY       = "/usr/local/python3.11.14/bin/python3.11"
AUTOTUNE = "/home/u_5f35688a99/autotune"
GUIDELLM = "/home/u_5f35688a99/autotune/guidellm"
CLI      = f"{GUIDELLM}/benchmark_cli.py"
LOG      = "/tmp/three_bench_v2.log"

RUNS = [
    {
        "tag":   "R1_seqs32_batched8192_noopt",
        "notes": "engine: vLLM 0.14.1; hw: 4×910B3; quant: W8A8; "
                 "PIECEWISE seqs=32; batched-tokens=8192; no Ascend opts",
        "params": {
            "cli": {
                "tensor-parallel-size": 4, "quantization": "ascend",
                "distributed-executor-backend": "mp", "block-size": 128,
                "max-num-seqs": 32, "max-num-batched-tokens": 8192,
                "max-model-len": 8192, "gpu-memory-utilization": 0.90,
                "enforce-eager": False, "enable-chunked-prefill": True,
            },
            "compilation_config": {"cudagraph_mode": "PIECEWISE", "cudagraph_num_of_warmups": 0},
            "additional_config": {
                "weight_prefetch_config.enabled": False, "pa_shape_list": None,
                "ascend_compilation_config.fuse_allreduce_rms": False, "enable_cpu_binding": False,
            },
            "env": {
                "VLLM_ASCEND_ENABLE_FLASHCOMM1": "0", "VLLM_ASCEND_ENABLE_NZ": "1",
                "VLLM_ASCEND_ENABLE_PREFETCH_MLP": "0",
                "HCCL_OP_EXPANSION_MODE": "AIV", "TASK_QUEUE_ENABLE": "1",
            },
            "selection_reason": "reliable_R1",
        },
    },
    {
        "tag":   "R2_seqs32_batched16384_baseopt",
        "notes": "engine: vLLM 0.14.1; hw: 4×910B3; quant: W8A8; "
                 "PIECEWISE seqs=32; batched-tokens=16384; weight_prefetch+FlashComm1",
        "params": {
            "cli": {
                "tensor-parallel-size": 4, "quantization": "ascend",
                "distributed-executor-backend": "mp", "block-size": 128,
                "max-num-seqs": 32, "max-num-batched-tokens": 16384,
                "max-model-len": 8192, "gpu-memory-utilization": 0.94,
                "enforce-eager": False, "enable-chunked-prefill": True,
            },
            "compilation_config": {"cudagraph_mode": "PIECEWISE", "cudagraph_num_of_warmups": 1},
            "additional_config": {
                "weight_prefetch_config.enabled": True, "pa_shape_list": None,
                "ascend_compilation_config.fuse_allreduce_rms": False, "enable_cpu_binding": False,
            },
            "env": {
                "VLLM_ASCEND_ENABLE_FLASHCOMM1": "1", "VLLM_ASCEND_ENABLE_NZ": "1",
                "VLLM_ASCEND_ENABLE_PREFETCH_MLP": "0",
                "HCCL_OP_EXPANSION_MODE": "AIV", "TASK_QUEUE_ENABLE": "1",
            },
            "selection_reason": "reliable_R2_proven",
        },
    },
    {
        "tag":   "R3_seqs32_batched24576_fullopt",
        "notes": "engine: vLLM 0.14.1; hw: 4×910B3; quant: W8A8; "
                 "PIECEWISE seqs=32; batched-tokens=24576; fuse_allreduce+MLP_prefetch+cpu_bind+FlashComm1",
        "params": {
            "cli": {
                "tensor-parallel-size": 4, "quantization": "ascend",
                "distributed-executor-backend": "mp", "block-size": 128,
                "max-num-seqs": 32, "max-num-batched-tokens": 24576,
                "max-model-len": 8192, "gpu-memory-utilization": 0.94,
                "enforce-eager": False, "enable-chunked-prefill": True,
                # async-scheduling: 已排除（EngineCore crash）
            },
            "compilation_config": {
                "cudagraph_mode": "PIECEWISE", "cudagraph_num_of_warmups": 2,
                # pass_config.enable_qk_norm_rope_fusion: 已排除（hidden_states IndexError）
            },
            "additional_config": {
                "weight_prefetch_config.enabled": True, "pa_shape_list": None,
                "ascend_compilation_config.fuse_allreduce_rms": True, "enable_cpu_binding": True,
            },
            "env": {
                "VLLM_ASCEND_ENABLE_FLASHCOMM1": "1", "VLLM_ASCEND_ENABLE_NZ": "1",
                "VLLM_ASCEND_ENABLE_PREFETCH_MLP": "1", "VLLM_ASCEND_BALANCE_SCHEDULING": "1",
                "HCCL_OP_EXPANSION_MODE": "AIV", "TASK_QUEUE_ENABLE": "1",
            },
            "selection_reason": "reliable_R3_fullopt",
        },
    },
]


def run(cmd, cwd=None, timeout=900):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def main():
    open(LOG, "w").close()  # 清空日志

    results = []
    for sc in RUNS:
        tag, notes = sc["tag"], sc["notes"]
        log(f"{'='*60}")
        log(f"开始 {tag}")

        # 写 chosen_params.json
        run_dir = f"/tmp/bench_reliable_{tag}"
        os.makedirs(run_dir, exist_ok=True)
        sc["params"]["run_id"] = tag
        with open(f"{run_dir}/chosen_params.json", "w") as f:
            json.dump(sc["params"], f, indent=2)

        # 启动 vLLM
        log("启动 vLLM...")
        rc, out = run(["bash", f"{AUTOTUNE}/scripts/start_service.sh", run_dir],
                      cwd=AUTOTUNE, timeout=700)
        # 只打关键行
        for line in out.splitlines():
            if any(k in line for k in ["渲染", "探活", "探通", "FAIL", "REJECT", "ERROR", "就绪"]):
                if not any(k in line for k in ["Warning", "_owner", "Diffusers", "onnxruntime"]):
                    print(line, flush=True)
                    with open(LOG, "a") as f: f.write(line + "\n")

        if rc != 0:
            log(f"❌ {tag} 服务启动失败 (rc={rc})，跳过 benchmark")
            results.append({"tag": tag, "rc": rc, "job_id": None})
            run(["bash", f"{AUTOTUNE}/scripts/stop_service.sh", "120"], cwd=AUTOTUNE, timeout=200)
            continue

        log(f"✅ 服务就绪，开始 benchmark (150 req / 并发 5)...")
        rc_b, out_b = run(
            [PY, CLI, "submit",
             "--endpoint-type", "chat_completions",
             "--port", "8010",
             "--model-name", "qwen3-32b-w8a8",
             "--mode", "public_leaderboard",
             "--notes", notes],
            cwd=GUIDELLM, timeout=900,
        )
        clean = "\n".join(l for l in out_b.splitlines()
                          if not any(k in l for k in ["Warning", "warnings.warn", "_owner"]))
        print(clean, flush=True)
        with open(LOG, "a") as f: f.write(clean + "\n")

        job_id = None
        m = re.search(r'"job_id":\s*"([a-f0-9]+)"', clean)
        if m: job_id = m.group(1)
        log(f"benchmark rc={rc_b}  job_id={job_id}")
        results.append({"tag": tag, "rc": rc_b, "job_id": job_id})

        # 停服务
        log("停服务，释放 HBM...")
        run(["bash", f"{AUTOTUNE}/scripts/stop_service.sh", "180"], cwd=AUTOTUNE, timeout=240)
        log("HBM 释放完毕，准备下一轮")
        time.sleep(5)

    # 汇总
    print("\n" + "="*60)
    print("三轮汇总")
    print("="*60)
    for r in results:
        ok = "✅ 成功" if r["rc"] == 0 else f"❌ rc={r['rc']}"
        print(f"  {r['tag']:<45} {ok}  job_id={r['job_id']}")

    print(f"\n榜单: {PY} {CLI} leaderboard --endpoint-type chat_completions --format table")
    print(f"网页: http://<ip>:8088/leaderboard/chat_completions  (15s 自动刷新)")
    return 0 if all(r["rc"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
