#!/usr/bin/env python3
"""Splits each PC decode token into the time the ceiling predicts and the extra time on top.

extra ms = 1000 / measured tok/s - 1000 / ceiling tok/s. Dividing by layer count tests whether the
extra is a fixed cost per layer rather than a cost per byte. Layer counts are read from the GGUF
headers in ~/models. Run analysis/roofline.py first. Writes analysis/thread_overhead_pc.csv.
"""

import csv
import struct
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODELS = Path.home() / "models"

FILES = {
    ("llama3.2-1b", "Q4_K_M"): "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
    ("llama3.2-3b", "Q4_K_M"): "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    ("qwen2.5-1.5b", "Q2_K"): "Qwen2.5-1.5B-Instruct-Q2_K.gguf",
    ("qwen2.5-1.5b", "Q4_K_M"): "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
    ("qwen2.5-1.5b", "Q5_K_M"): "Qwen2.5-1.5B-Instruct-Q5_K_M.gguf",
    ("qwen2.5-1.5b", "Q8_0"): "Qwen2.5-1.5B-Instruct-Q8_0.gguf",
    ("qwen2.5-7b", "Q4_K_M"): "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
}

# Byte sizes of the fixed-size GGUF value types, by type id. 8 is a string and 9 is an array.
TYPE_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}


def read_string(file):
    length = struct.unpack("<Q", file.read(8))[0]
    return file.read(length)


def skip_value(file, value_type):
    if value_type == 8:
        read_string(file)
    elif value_type == 9:
        item_type, count = struct.unpack("<IQ", file.read(12))
        for _ in range(count):
            skip_value(file, item_type)
    else:
        file.seek(TYPE_SIZES[value_type], 1)


def layer_count(path):
    """Walks the GGUF metadata until it finds <architecture>.block_count, the number of layers."""
    with open(path, "rb") as file:
        file.read(8)  # Magic number and version.
        _, key_count = struct.unpack("<QQ", file.read(16))
        for _ in range(key_count):
            key = read_string(file).decode()
            value_type = struct.unpack("<I", file.read(4))[0]
            if key.endswith(".block_count"):
                return struct.unpack("<I", file.read(4))[0]
            skip_value(file, value_type)
    raise ValueError(f"no block_count in {path}")


def main():
    layers = {key: layer_count(MODELS / file) for key, file in FILES.items()}

    with open(REPO / "analysis" / "roofline_pc.csv", newline="") as file:
        rows = list(csv.DictReader(file))

    out = []
    for row in rows:
        n_layers = layers[(row["model"], row["quant"])]
        measured_ms = 1000 / float(row["measured_tok_s"])
        ceiling_ms = 1000 / float(row["ceiling_tok_s"])
        extra_ms = measured_ms - ceiling_ms
        out.append({
            "model": row["model"], "quant": row["quant"], "threads": row["threads"],
            "model_gb": row["model_gb"], "layers": n_layers,
            "measured_ms": round(measured_ms, 1), "ceiling_ms": round(ceiling_ms, 1),
            "extra_ms": round(extra_ms, 1), "extra_ms_per_layer": round(extra_ms / n_layers, 2),
        })

    with open(REPO / "analysis" / "thread_overhead_pc.csv", "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=out[0].keys())
        writer.writeheader()
        writer.writerows(out)

    for row in out:
        print(f"t{row['threads']} {row['model']:13} {row['quant']:7} layers {row['layers']:3} "
              f"extra {row['extra_ms']:5.1f} ms  per layer {row['extra_ms_per_layer']:5.2f}")


if __name__ == "__main__":
    main()
