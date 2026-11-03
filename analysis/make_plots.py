#!/usr/bin/env python3
"""Draws the README plots into analysis/plots. Run analysis/roofline.py first."""

import csv
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")  # Writes files only, so no display is needed.
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

from roofline import read_bandwidth

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "results"
PLOTS = REPO / "analysis" / "plots"

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
INK = "#0b0b0b"
SECONDARY = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"

NAMES = {
    ("qwen2.5-1.5b", "Q2_K"): "Qwen 1.5B Q2",
    ("llama3.2-1b", "Q4_K_M"): "Llama 1B Q4",
    ("qwen2.5-1.5b", "Q4_K_M"): "Qwen 1.5B Q4",
    ("qwen2.5-1.5b", "Q5_K_M"): "Qwen 1.5B Q5",
    ("qwen2.5-1.5b", "Q8_0"): "Qwen 1.5B Q8",
    ("llama3.2-3b", "Q4_K_M"): "Llama 3B Q4",
    ("qwen2.5-7b", "Q4_K_M"): "Qwen 7B Q4",
}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 11, "text.color": INK, "axes.labelcolor": SECONDARY,
    "xtick.color": SECONDARY, "ytick.color": SECONDARY,
    "axes.edgecolor": AXIS, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "xtick.major.size": 0, "ytick.major.size": 0, "lines.linewidth": 2, "lines.markersize": 8,
    "legend.frameon": False,
})


def load_csv(name, numbers):
    with open(REPO / "analysis" / name, newline="") as file:
        rows = list(csv.DictReader(file))
    for row in rows:
        row["threads"] = int(row["threads"])
        for key in numbers:
            row[key] = float(row[key])
    return rows


def load_roofline(name="roofline.csv"):
    return load_csv(name, ("model_gb", "ceiling_tok_s", "measured_tok_s"))


def load_triad():
    """Returns mean Triad bandwidth in GB/s for each thread count."""
    samples = defaultdict(list)
    with open(RESULTS / "stream.csv", newline="") as file:
        for row in csv.DictReader(file):
            if row["kernel"] == "Triad":
                samples[int(row["threads"])].append(float(row["best_mb_s"]) / 1000)
    return {threads: mean(values) for threads, values in samples.items()}


def load_perplexity():
    """Returns (quant, score, error) for each log, using its final estimate line."""
    scores = []
    for path in (RESULTS / "perplexity").glob("*.log"):
        match = re.search(r"PPL = ([\d.]+) \+/- ([\d.]+)", path.read_text(errors="replace"))
        scores.append((path.stem.split("_", 1)[1], float(match[1]), float(match[2])))
    return scores


def save(figure, name):
    figure.savefig(PLOTS / name, dpi=200, bbox_inches="tight", pad_inches=0.15)
    plt.close(figure)


def plot_roofline(rows):
    """The main result. Log axes turn the ceiling, bandwidth / size, into a straight line."""
    points = sorted((r for r in rows if r["threads"] == 4), key=lambda r: r["model_gb"])
    bandwidth_gb = read_bandwidth()[4] / 1e9

    figure, axes = plt.subplots(figsize=(8, 5))
    sizes = [0.6, 5.5]
    axes.plot(sizes, [bandwidth_gb / size for size in sizes], color=SECONDARY, linestyle="--",
              label=f"Ceiling: {bandwidth_gb:.2f} GB/s ÷ model size")
    axes.plot([r["model_gb"] for r in points], [r["measured_tok_s"] for r in points], "o",
              color=BLUE, label="Measured decode")

    # Labels sit below the ceiling line, where there is room next to each dot.
    for row in points:
        axes.annotate(NAMES[(row["model"], row["quant"])],
                      (row["model_gb"], row["measured_tok_s"]), xytext=(-7, -7),
                      textcoords="offset points", ha="right", va="top", fontsize=9.5,
                      color=SECONDARY)

    axes.set_xscale("log")
    axes.set_yscale("log")
    axes.set_xlim(0.45, 6)
    axes.set_ylim(1.5, 25)
    for axis, ticks in ((axes.xaxis, [0.5, 1, 2, 5]), (axes.yaxis, [2, 5, 10, 20])):
        axis.set_major_locator(FixedLocator(ticks))
        axis.set_minor_locator(NullLocator())
        axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    axes.set_xlabel("Model file size (GB, log scale)")
    axes.set_ylabel("Decode speed (tok/s, log scale)")
    axes.set_title("At 4 threads, every model runs at 86-93% of the memory ceiling",
                   loc="left", fontsize=13, fontweight="bold")
    axes.legend(loc="upper right")
    save(figure, "1_roofline_4_threads.png")


def plot_two_limits(rows):
    """Adding cores adds compute but no bandwidth, so the shape of each line shows its limit."""
    figure, panels = plt.subplots(1, 2, figsize=(9, 4.6), sharey=True)
    for axes, quant, heading in zip(panels, ("Q2_K", "Q8_0"),
                                    ("Qwen 1.5B Q2: limited by the CPU at first",
                                     "Qwen 1.5B Q8: limited by memory from 1 thread")):
        series = sorted((r for r in rows if r["model"] == "qwen2.5-1.5b" and r["quant"] == quant),
                        key=lambda r: r["threads"])
        threads = [r["threads"] for r in series]
        axes.plot(threads, [r["ceiling_tok_s"] for r in series], color=SECONDARY, linestyle="--",
                  label="Memory ceiling")
        axes.plot(threads, [r["measured_tok_s"] for r in series], "o-", color=BLUE,
                  label="Measured decode")
        axes.set_title(heading, loc="left", fontsize=11.5, fontweight="bold")
        axes.set_xlabel("Threads")
        axes.set_xticks(threads)
        axes.set_ylim(0, 24)
    panels[0].set_ylabel("Decode speed (tok/s)")
    panels[0].legend(loc="lower right")
    figure.tight_layout()
    save(figure, "2_two_limits.png")


def plot_bandwidth():
    read_only = {threads: value / 1e9 for threads, value in read_bandwidth().items()}
    triad = load_triad()
    threads = sorted(read_only)

    figure, axes = plt.subplots(figsize=(7, 4.6))
    axes.plot(threads, [read_only[t] for t in threads], "o-", color=BLUE, label="Read-only test")
    axes.plot(threads, [triad[t] for t in threads], "s-", color=ORANGE, label="STREAM Triad")
    for series in (read_only, triad):
        for t in (threads[0], threads[-1]):
            axes.annotate(f"{series[t]:.2f}", (t, series[t]), xytext=(0, 9),
                          textcoords="offset points", ha="center", fontsize=10, color=SECONDARY)
    axes.set_xticks(threads)
    axes.set_ylim(0, 17)
    axes.set_xlabel("Threads")
    axes.set_ylabel("Bandwidth (GB/s)")
    axes.set_title("Memory bandwidth falls as threads are added", loc="left", fontsize=13,
                   fontweight="bold")
    axes.legend(loc="lower left")
    save(figure, "3_bandwidth.png")


def plot_quality(rows):
    sizes = {r["quant"]: r["model_gb"] for r in rows if r["model"] == "qwen2.5-1.5b"}
    scores = sorted(load_perplexity(), key=lambda score: sizes[score[0]])

    figure, axes = plt.subplots(figsize=(7, 4.6))
    xs = [sizes[quant] for quant, _, _ in scores]
    ys = [score for _, score, _ in scores]
    axes.errorbar(xs, ys, yerr=[error for _, _, error in scores], fmt="o-", color=BLUE, capsize=4)
    for x, y, (quant, _, _) in zip(xs, ys, scores):
        # Q4 and Q5 sit close together, so Q4's label goes below the line.
        offset = (-12, -24) if quant == "Q4_K_M" else (8, 10)
        axes.annotate(f"{quant.split('_')[0]}: {y:.2f}", (x, y), xytext=offset,
                      textcoords="offset points", fontsize=10, color=SECONDARY)
    axes.set_xlim(0.5, 1.9)
    axes.set_ylim(0, 18)
    axes.set_xlabel("Model file size (GB)")
    axes.set_ylabel("Perplexity (lower is better)")
    axes.set_title("Qwen 1.5B quality drops sharply at Q2, and little above Q4", loc="left",
                   fontsize=13, fontweight="bold")
    save(figure, "4_quality_vs_size.png")


def plot_pc_threads():
    """Left: PC decode slows as threads are added. Right: the extra time is per layer, not per byte."""
    speeds = load_roofline("roofline_pc.csv")
    overhead = load_csv("thread_overhead_pc.csv", ("extra_ms_per_layer",))
    figure, (left, right) = plt.subplots(1, 2, figsize=(10, 4.6))

    # Marker shapes repeat the color coding, so the lines stay distinct without color.
    series = [(("qwen2.5-1.5b", "Q2_K"), BLUE, "o"), (("qwen2.5-1.5b", "Q8_0"), ORANGE, "s"),
              (("llama3.2-1b", "Q4_K_M"), AQUA, "^")]
    for key, color, marker in series:
        name = NAMES[key]
        for axes, rows, field in ((left, speeds, "measured_tok_s"),
                                  (right, overhead, "extra_ms_per_layer")):
            points = sorted((r for r in rows if (r["model"], r["quant"]) == key),
                            key=lambda r: r["threads"])
            axes.plot([r["threads"] for r in points], [r[field] for r in points],
                      marker=marker, color=color, label=name)

    left.set_title("PC decode gets slower with more threads", loc="left", fontsize=11.5,
                   fontweight="bold")
    left.set_ylabel("Decode speed (tok/s)")
    left.set_ylim(0, 30)
    right.set_title("Extra time per layer tracks threads, not size", loc="left",
                    fontsize=11.5, fontweight="bold")
    right.set_ylabel("Extra ms per layer, above the ceiling")
    right.set_ylim(0, 1.4)
    for axes in (left, right):
        axes.set_xlabel("Threads")
        axes.set_xticks([1, 2, 4, 6, 8])
    left.legend(loc="lower left")
    figure.tight_layout()
    save(figure, "5_pc_threads.png")


def main():
    PLOTS.mkdir(exist_ok=True)
    rows = load_roofline()
    plot_roofline(rows)
    plot_two_limits(rows)
    plot_bandwidth()
    plot_quality(rows)
    plot_pc_threads()


if __name__ == "__main__":
    main()
