#!/usr/bin/env bash
# Measures Qwen2.5 1.5B perplexity at each quant level on 20 chunks of wikitext-2.
# Lower perplexity means better predictions, so this shows what each size saving costs in quality.
# Safe to re-run: finished quants are skipped.

set -u

REPO="$HOME/pi5-llm-inference"
PERPLEXITY="$HOME/llama.cpp/build/bin/llama-perplexity"
DATA="$HOME/data/wikitext/wikitext-2-raw/wiki.test.raw"
OUT="$REPO/results/perplexity"

mkdir -p "$OUT"
sha256sum "$DATA"

for quant in Q2_K Q4_K_M Q5_K_M Q8_0; do
    log="$OUT/qwen2.5-1.5b_$quant.log"

    if grep -q "Final estimate" "$log" 2>/dev/null; then
        echo "Skipping finished run: $quant"
        continue
    fi

    # Write to a temp file first, so a crash can't leave a partial log that looks finished.
    # Every quant sees the same tokens and chunks, so their scores are directly comparable.
    "$PERPLEXITY" -m "$HOME/models/Qwen2.5-1.5B-Instruct-$quant.gguf" -f "$DATA" \
        -c 512 --chunks 20 -t 4 > "$log.tmp" 2>&1
    exit_code=$?

    if [ "$exit_code" -eq 0 ] && grep -q "Final estimate" "$log.tmp"; then
        mv "$log.tmp" "$log"
        echo "OK $quant: $(grep "Final estimate" "$log")"
    else
        echo "FAILED $quant exit=$exit_code, log kept at $log.tmp"
    fi
done

echo "PERPLEXITY_FINISHED"
