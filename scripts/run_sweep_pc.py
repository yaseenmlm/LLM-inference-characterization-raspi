#!/usr/bin/env python3
"""Runs the llama-bench sweep on the PC. Each config writes its own JSON, so a crash loses at most one.

Usage:
  run_sweep_pc.py          full sweep, saved to results/pc/sweep
  run_sweep_pc.py --smoke  short test of one model, saved to results/pc/smoke
"""

import argparse
import csv
import ctypes
import json
import os
import subprocess
import time
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent
BENCH = HOME / "llama.cpp/build/bin/llama-bench.exe"
MODELS = HOME / "models"
TOOLCHAIN = r"C:\gcc16\bin"

CPU_MASK = 0x5555  # One logical CPU per core on the 8-core 7700X, so threads never share a core.
BENCH_TIMEOUT_S = 3600
HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
BEST_PERFORMANCE = "ded574b5-45a0-4f42-8737-46345c09c238"
POWER_KEY = r"HKLM\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"
PERFORMANCE_COUNTER = r"\Processor Information(_Total)\% Processor Performance"
FREQUENCY_COUNTER = r"\Processor Information(_Total)\Processor Frequency"

LLAMA_1B = ("llama3.2-1b", "Q4_K_M", "Llama-3.2-1B-Instruct-Q4_K_M.gguf")
LLAMA_3B = ("llama3.2-3b", "Q4_K_M", "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
QWEN_Q2 = ("qwen2.5-1.5b", "Q2_K", "Qwen2.5-1.5B-Instruct-Q2_K.gguf")
QWEN_Q4 = ("qwen2.5-1.5b", "Q4_K_M", "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")
QWEN_Q5 = ("qwen2.5-1.5b", "Q5_K_M", "Qwen2.5-1.5B-Instruct-Q5_K_M.gguf")
QWEN_Q8 = ("qwen2.5-1.5b", "Q8_0", "Qwen2.5-1.5B-Instruct-Q8_0.gguf")
QWEN_7B = ("qwen2.5-7b", "Q4_K_M", "Qwen2.5-7B-Instruct-Q4_K_M.gguf")


def in_performance_mode():
    plan = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True)
    overlay = subprocess.run(["reg", "query", POWER_KEY, "/v", "ActiveOverlayAcPowerScheme"],
                             capture_output=True, text=True)
    text = plan.stdout + overlay.stdout
    return HIGH_PERFORMANCE in text or BEST_PERFORMANCE in text


def pin_to_physical_cores():
    """Child processes inherit this mask. MinGW's OpenMP ignores OMP_PLACES, so it can't do this."""
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not kernel32.SetProcessAffinityMask(kernel32.GetCurrentProcess(), CPU_MASK):
        raise SystemExit("ABORT: could not set CPU affinity")


def load_into_cache(file):
    """Reads the file once, so the first run isn't timing the disk."""
    with open(MODELS / file, "rb") as model:
        while model.read(1 << 24):
            pass


def summarize_clock(path):
    """Effective clock is base frequency scaled by % performance. Windows has no throttle flags."""
    with open(path, newline="") as file:
        rows = list(csv.reader(file))[1:]
    mhz = []
    for row in rows:
        try:
            mhz.append(float(row[1]) * float(row[2]) / 100)
        except (IndexError, ValueError):  # typeperf leaves a blank first sample.
            continue
    if not mhz:  # Very short runs can finish before the first sample.
        return {"samples": 0, "min_mhz": None, "mean_mhz": None}
    return {"samples": len(mhz), "min_mhz": min(mhz), "mean_mhz": sum(mhz) / len(mhz)}


def save_json(path, payload):
    """Writes then renames, so a crash can't leave half a result that looks finished."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2))
    os.replace(temp_path, path)


def run_phase(out_dir, config_id, phase, file, threads, prompt, gen, repeats):
    clock_path = out_dir / f"{config_id}_{phase}_clock.csv"
    # Running from the models folder avoids passing the space in the user's folder name.
    command = [str(BENCH), "-m", file, "-t", str(threads), "-p", str(prompt), "-n", str(gen),
               "-r", str(repeats), "-o", "json"]

    started = time.time()
    # typeperf's own -o file is lost when it is stopped, so capture its printed samples instead.
    with open(clock_path, "w") as clock_file:
        logger = subprocess.Popen(["typeperf", PERFORMANCE_COUNTER, FREQUENCY_COUNTER, "-si", "1"],
                                  stdout=clock_file, stderr=subprocess.DEVNULL)
        try:
            bench = subprocess.run(command, capture_output=True, text=True,
                                   timeout=BENCH_TIMEOUT_S, cwd=MODELS)
            exit_code, stdout, stderr = bench.returncode, bench.stdout, bench.stderr
        except subprocess.TimeoutExpired:
            exit_code, stdout, stderr = -1, "", "timed out"
        finally:
            logger.terminate()
            logger.wait()

    return {
        "command": command, "started": started, "seconds": time.time() - started,
        "clock": summarize_clock(clock_path), "exit_code": exit_code,
        "stdout": stdout, "stderr": stderr,
    }


def run_config(out_dir, config, prompt, gen, repeats):
    model, quant, file, threads = config
    config_id = f"{model}_{quant}_t{threads}"
    done_path = out_dir / f"{config_id}.json"

    if done_path.exists():
        print(f"SKIP {config_id}", flush=True)
        return

    phases = {
        "prefill": run_phase(out_dir, config_id, "prefill", file, threads, prompt, 0, repeats),
        "decode": run_phase(out_dir, config_id, "decode", file, threads, 0, gen, repeats),
    }

    failed = any(phase["exit_code"] != 0 for phase in phases.values())
    bench = [] if failed else [row for phase in phases.values() for row in json.loads(phase["stdout"])]
    started = phases["prefill"]["started"]

    for phase in phases.values():
        del phase["stdout"]
        phase["stderr"] = phase["stderr"][-2000:] if failed else ""

    payload = {
        "model": model, "quant": quant, "file": file, "threads": threads,
        "started": started, "phases": phases, "bench": bench,
    }

    if failed:
        save_json(out_dir / "failed" / f"{config_id}_{int(started)}.json", payload)
        print(f"FAILED {config_id}", flush=True)
    else:
        save_json(done_path, payload)
        print(f"OK {config_id} {[p['clock'] for p in phases.values()]}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if not in_performance_mode():
        raise SystemExit("ABORT: PC is not in performance mode")
    pin_to_physical_cores()
    os.environ["PATH"] = TOOLCHAIN + os.pathsep + os.environ["PATH"]  # llama-bench needs its DLLs.

    out_dir = REPO / "results" / "pc" / ("smoke" if args.smoke else "sweep")
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt, gen, repeats = (256, 128, 1) if args.smoke else (256, 128, 3)

    if args.smoke:
        grid = [(*QWEN_Q8, 1), (*QWEN_Q8, 8)]
    else:
        models = [LLAMA_1B, QWEN_Q2, QWEN_Q4, QWEN_Q5, QWEN_Q8, LLAMA_3B, QWEN_7B]
        grid = [(*model, threads) for model in models for threads in (1, 2, 4, 6, 8)]

    for model in {config[2] for config in grid}:
        load_into_cache(model)

    for number, config in enumerate(grid, start=1):
        print(f"[{number}/{len(grid)}] {config[0]} {config[1]} t{config[3]}", flush=True)
        try:
            run_config(out_dir, config, prompt, gen, repeats)
        except Exception as error:  # One bad config must not stop a long run.
            print(f"ERROR {config}: {error}", flush=True)

    print("SWEEP_FINISHED", flush=True)


if __name__ == "__main__":
    main()
