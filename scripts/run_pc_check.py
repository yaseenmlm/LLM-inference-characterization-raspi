#!/usr/bin/env python3
"""Tests whether decode slowing down with threads on the PC comes from how the sweep was run.

Repeats Qwen Q2 decode at 8 threads with one setting changed at a time.
Saves to results/pc/checks/q2_t8_decode.json.
"""

import ctypes
import json
import os
import subprocess

from run_sweep_pc import BENCH, CPU_MASK, MODELS, QWEN_Q2, REPO, TOOLCHAIN, in_performance_mode

ALL_LOGICAL_CPUS = 0xFFFF

# Each line: name, process CPU mask, extra environment, extra llama-bench flags.
VARIANTS = [
    ("sweep_settings", CPU_MASK, {}, []),
    ("unpinned", ALL_LOGICAL_CPUS, {}, []),
    ("openmp_active_wait", CPU_MASK, {"OMP_WAIT_POLICY": "active"}, []),
    ("full_polling", CPU_MASK, {}, ["--poll", "100"]),
]


def set_cpu_mask(mask):
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not kernel32.SetProcessAffinityMask(kernel32.GetCurrentProcess(), mask):
        raise SystemExit("ABORT: could not set CPU affinity")


def main():
    if not in_performance_mode():
        raise SystemExit("ABORT: PC is not in performance mode")

    results = []
    for name, mask, extra_env, flags in VARIANTS:
        set_cpu_mask(mask)
        env = {**os.environ, "PATH": TOOLCHAIN + os.pathsep + os.environ["PATH"], **extra_env}
        command = [str(BENCH), "-m", QWEN_Q2[2], "-t", "8", "-p", "0", "-n", "128", "-r", "3",
                   "-o", "json", *flags]
        bench = subprocess.run(command, capture_output=True, text=True, cwd=MODELS, env=env, check=True)
        entry = json.loads(bench.stdout)[0]
        results.append({"variant": name, "mask": mask, "env": extra_env, "command": command,
                        "bench": entry})
        print(f"{name}: {entry['avg_ts']:.2f} sd {entry['stddev_ts']:.2f}", flush=True)

    out_dir = REPO / "results" / "pc" / "checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "q2_t8_decode.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
