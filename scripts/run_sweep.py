#!/usr/bin/env python3
"""Runs the llama-bench sweep. Each config writes its own JSON, so a crash loses at most one.

Usage:
  run_sweep.py          full sweep, saved to results/sweep
  run_sweep.py --smoke  short end-to-end test of every model, saved to results/smoke
  run_sweep.py --split-check  repeats two accepted combined runs, saved to results/split_check
"""

import argparse
import csv
import json
import os
import subprocess
import time
from pathlib import Path

HOME = Path.home()
REPO = HOME / "pi5-llm-inference"
BENCH = HOME / "llama.cpp/build/bin/llama-bench"
MODELS = HOME / "models"
LOGGER = REPO / "scripts/thermal_logger.sh"

COOLDOWN_C = 50.0  # Lowered from 55 for the 4-thread re-runs, to give them more thermal margin.
COOLDOWN_LIMIT_S = 600
MIN_HZ = 2_390_000_000  # With the performance governor, any clock below this is a throttle.
BENCH_TIMEOUT_S = 3600

LLAMA_1B = ("llama3.2-1b", "Q4_K_M", "Llama-3.2-1B-Instruct-Q4_K_M.gguf")
LLAMA_3B = ("llama3.2-3b", "Q4_K_M", "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
QWEN_Q2 = ("qwen2.5-1.5b", "Q2_K", "Qwen2.5-1.5B-Instruct-Q2_K.gguf")
QWEN_Q4 = ("qwen2.5-1.5b", "Q4_K_M", "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")
QWEN_Q5 = ("qwen2.5-1.5b", "Q5_K_M", "Qwen2.5-1.5B-Instruct-Q5_K_M.gguf")
QWEN_Q8 = ("qwen2.5-1.5b", "Q8_0", "Qwen2.5-1.5B-Instruct-Q8_0.gguf")
QWEN_7B = ("qwen2.5-7b", "Q4_K_M", "Qwen2.5-7B-Instruct-Q4_K_M.gguf")


def build_grid(smoke):
    """Returns (model, quant, file, threads) tuples, smallest models first."""
    if smoke:
        models = [LLAMA_1B, QWEN_Q2, QWEN_Q4, QWEN_Q5, QWEN_Q8, LLAMA_3B, QWEN_7B]
        return [(*LLAMA_1B, 1)] + [(*m, 4) for m in models]

    grid = []
    for model in [LLAMA_1B, QWEN_Q2, QWEN_Q4, QWEN_Q5, QWEN_Q8, LLAMA_3B]:
        grid += [(*model, threads) for threads in (1, 2, 3, 4)]
    grid.append((*QWEN_7B, 4))  # A single bandwidth data point, so one thread count is enough.
    return grid


def vcgencmd(*args):
    output = subprocess.run(["vcgencmd", *args], capture_output=True, text=True, check=True)
    return output.stdout.strip().split("=")[1]


def read_temp():
    return float(vcgencmd("measure_temp").replace("'C", ""))


def cooldown():
    """Every run starts below the same temperature, so runs are comparable."""
    start = time.time()
    while read_temp() > COOLDOWN_C:
        if time.time() - start > COOLDOWN_LIMIT_S:
            raise RuntimeError(f"still above {COOLDOWN_C}C after {COOLDOWN_LIMIT_S}s")
        time.sleep(5)


def summarize_thermal(path):
    with open(path, newline="") as file:
        rows = list(csv.DictReader(file))
    # The low 4 bits are live state. The high bits are history that only a reboot clears.
    live_flags = sum(1 for row in rows if int(row["throttled"], 16) & 0xF)
    return {
        "samples": len(rows),
        "max_temp_c": max(float(row["temp_c"]) for row in rows),
        "min_arm_hz": min(int(row["arm_hz"]) for row in rows),
        "live_flag_samples": live_flags,
    }


def save_json(path, payload):
    """Writes then renames, so a crash can't leave half a result that looks finished."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2))
    os.replace(temp_path, path)


def run_phase(out_dir, config_id, phase, file, threads, prompt, gen, repeats):
    """Runs one llama-bench call. Each call starts cool, so prefill heat can't carry into decode."""
    cooldown()
    thermal_path = out_dir / f"{config_id}_{phase}_thermal.csv"
    flags_before = vcgencmd("get_throttled")
    command = [str(BENCH), "-m", str(MODELS / file), "-t", str(threads), "-p", str(prompt),
               "-n", str(gen), "-r", str(repeats), "-o", "json"]

    started = time.time()
    logger = subprocess.Popen(["bash", str(LOGGER), str(thermal_path)])
    try:
        bench = subprocess.run(command, capture_output=True, text=True, timeout=BENCH_TIMEOUT_S)
        exit_code, stdout, stderr = bench.returncode, bench.stdout, bench.stderr
    except subprocess.TimeoutExpired:
        exit_code, stdout, stderr = -1, "", "timed out"
    finally:
        logger.terminate()
        logger.wait()

    thermal = summarize_thermal(thermal_path)
    flags_after = vcgencmd("get_throttled")
    # A run is rejected for live throttling, a clock drop, or a new entry in the flag history.
    throttled = (thermal["live_flag_samples"] > 0 or thermal["min_arm_hz"] < MIN_HZ
                 or flags_before != flags_after)
    return {
        "command": command, "started": started, "seconds": time.time() - started,
        "flags_before": flags_before, "flags_after": flags_after, "thermal": thermal,
        "exit_code": exit_code, "throttled": throttled, "stdout": stdout, "stderr": stderr,
    }


def run_config(out_dir, config, prompt, gen, repeats):
    model, quant, file, threads = config
    config_id = f"{model}_{quant}_t{threads}"
    done_path = out_dir / f"{config_id}.json"

    if done_path.exists():
        print(f"SKIP {config_id}", flush=True)
        return

    phases = {}
    # 7B's prefill throttles on this cooling, and the roofline only needs its decode speed.
    if file != QWEN_7B[2]:
        phases["prefill"] = run_phase(out_dir, config_id, "prefill", file, threads, prompt, 0, repeats)
    phases["decode"] = run_phase(out_dir, config_id, "decode", file, threads, 0, gen, repeats)

    failed = any(phase["exit_code"] != 0 for phase in phases.values())
    throttled = any(phase["throttled"] for phase in phases.values())
    # All phases count as one config, so a re-run always measures them under one setup.
    bench = [] if failed else [row for phase in phases.values() for row in json.loads(phase["stdout"])]
    started = min(phase["started"] for phase in phases.values())

    for phase in phases.values():
        del phase["stdout"]
        phase["stderr"] = phase["stderr"][-2000:] if failed else ""

    payload = {
        "model": model, "quant": quant, "file": file, "threads": threads,
        "started": started, "phases": phases, "bench": bench,
    }
    max_temp = max(phase["thermal"]["max_temp_c"] for phase in phases.values())

    stamp = int(started)
    if failed:
        save_json(out_dir / "failed" / f"{config_id}_{stamp}.json", payload)
        print(f"FAILED {config_id}", flush=True)
    elif throttled:
        save_json(out_dir / "rejected" / f"{config_id}_{stamp}.json", payload)
        print(f"REJECTED {config_id} {[p['thermal'] for p in phases.values()]}", flush=True)
    else:
        save_json(done_path, payload)
        print(f"OK {config_id} max={max_temp}C", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--split-check", action="store_true")
    args = parser.parse_args()

    governor = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    if governor != "performance":
        raise SystemExit(f"ABORT: governor is {governor}, expected performance")

    folder = "smoke" if args.smoke else "split_check" if args.split_check else "sweep"
    out_dir = REPO / "results" / folder
    prompt, gen, repeats = (32, 16, 1) if args.smoke else (256, 128, 3)
    out_dir.mkdir(parents=True, exist_ok=True)

    grid = build_grid(args.smoke)
    if args.split_check:
        # These ran as one combined call, so matching speeds show that splitting changes nothing.
        grid = [(*LLAMA_1B, 4), (*QWEN_Q4, 4)]

    for number, config in enumerate(grid, start=1):
        print(f"[{number}/{len(grid)}] {config[0]} {config[1]} t{config[3]}", flush=True)
        try:
            run_config(out_dir, config, prompt, gen, repeats)
        except Exception as error:  # One bad config must not stop an overnight run.
            print(f"ERROR {config}: {error}", flush=True)

    print("SWEEP_FINISHED", flush=True)


if __name__ == "__main__":
    main()
