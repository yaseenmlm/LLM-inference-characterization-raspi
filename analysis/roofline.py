#!/usr/bin/env python3
"""Compares measured decode speed with the roofline, and writes analysis/roofline.csv.

Roofline: ceiling tok/s = read bandwidth / model bytes, because each token reads about every
weight once and never writes them. Run from anywhere: paths are relative to this file.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "results"


def read_bandwidth():
    """Returns mean read bandwidth in bytes per second for each thread count."""
    samples = defaultdict(list)
    with open(RESULTS / "read_bw.csv", newline="") as file:
        for row in csv.DictReader(file):
            samples[int(row["threads"])].append(float(row["best_mb_s"]) * 1e6)
    return {threads: mean(values) for threads, values in samples.items()}


def model_bytes():
    with open(RESULTS / "model_sizes.csv", newline="") as file:
        return {row["file"]: int(row["bytes"]) for row in csv.DictReader(file)}


def decode_result(run):
    """Returns (tok/s, stddev) from the one decode entry, which has no prompt tokens."""
    entry = next(item for item in run["bench"] if item["n_prompt"] == 0)
    return entry["avg_ts"], entry["stddev_ts"]


def main():
    bandwidth = read_bandwidth()
    sizes = model_bytes()

    rows = []
    # Only finished configs sit at the top of results/sweep. Rejected runs have their own folders.
    for path in sorted((RESULTS / "sweep").glob("*.json")):
        run = json.loads(path.read_text())
        threads = run["threads"]
        measured, stddev = decode_result(run)
        ceiling = bandwidth[threads] / sizes[run["file"]]
        rows.append({
            "model": run["model"], "quant": run["quant"], "threads": threads,
            "model_gb": round(sizes[run["file"]] / 1e9, 3),
            "ceiling_tok_s": round(ceiling, 2),
            "measured_tok_s": round(measured, 2),
            "stddev_tok_s": round(stddev, 2),
            "pct_of_ceiling": round(100 * measured / ceiling, 1),
        })

    rows.sort(key=lambda row: (row["threads"], row["model_gb"]))
    with open(REPO / "analysis" / "roofline.csv", "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    for row in rows:
        print(f"t{row['threads']} {row['model']:14} {row['quant']:7} {row['model_gb']:5.3f} GB  "
              f"ceiling {row['ceiling_tok_s']:6.2f}  measured {row['measured_tok_s']:6.2f}  "
              f"{row['pct_of_ceiling']:5.1f}%")


if __name__ == "__main__":
    main()
