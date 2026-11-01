#!/usr/bin/env bash
# Downloads every GGUF in the sweep to ~/models and verifies its SHA-256.
# Safe to re-run: verified files are skipped and partial files resume.

set -u

MODEL_DIR="$HOME/models"
mkdir -p "$MODEL_DIR"
failures=0

# Each line: Hugging Face repo, filename, expected SHA-256 from the repo's LFS metadata.
# Qwen2.5 1.5B carries the quant sweep because one uploader provides all four
# levels, so size is the only thing changing between those files.
while read -r repo file expected_sha; do
    path="$MODEL_DIR/$file"

    # Hash files that already exist so a re-run doesn't fetch them again.
    if [ -f "$path" ] && [ "$(sha256sum "$path" | cut -d' ' -f1)" = "$expected_sha" ]; then
        echo "OK (already verified): $file"
        continue
    fi

    echo "Downloading: $file"
    # -C - resumes a partial file; the retries cover Wi-Fi drops during long downloads.
    curl -fL -C - --retry 20 --retry-delay 10 --retry-all-errors \
        -o "$path" "https://huggingface.co/$repo/resolve/main/$file"

    # A corrupt file can't be resumed, so remove it and let the next run start clean.
    if [ "$(sha256sum "$path" | cut -d' ' -f1)" = "$expected_sha" ]; then
        echo "OK (verified): $file"
    else
        echo "FAILED checksum: $file"
        rm -f "$path"
        failures=$((failures + 1))
    fi
done <<'EOF'
bartowski/Llama-3.2-1B-Instruct-GGUF Llama-3.2-1B-Instruct-Q4_K_M.gguf 6f85a640a97cf2bf5b8e764087b1e83da0fdb51d7c9fab7d0fece9385611df83
bartowski/Llama-3.2-3B-Instruct-GGUF Llama-3.2-3B-Instruct-Q4_K_M.gguf 6c1a2b41161032677be168d354123594c0e6e67d2b9227c84f296ad037c728ff
bartowski/Qwen2.5-1.5B-Instruct-GGUF Qwen2.5-1.5B-Instruct-Q2_K.gguf a8880f0de2348db67d00519ef7f4b40326ef67012bf5f2e90bd1d47474e2355c
bartowski/Qwen2.5-1.5B-Instruct-GGUF Qwen2.5-1.5B-Instruct-Q4_K_M.gguf 1adf0b11065d8ad2e8123ea110d1ec956dab4ab038eab665614adba04b6c3370
bartowski/Qwen2.5-1.5B-Instruct-GGUF Qwen2.5-1.5B-Instruct-Q5_K_M.gguf cf240adc57e126e86102335f6565fb23e523b28d287c75bdb0759f064e8bb572
bartowski/Qwen2.5-1.5B-Instruct-GGUF Qwen2.5-1.5B-Instruct-Q8_0.gguf 7185d306cf45956c8c017cd0d3b05ecc6bc18b3ea8eb5c240dce40e87563db7f
bartowski/Qwen2.5-7B-Instruct-GGUF Qwen2.5-7B-Instruct-Q4_K_M.gguf 65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423
EOF

echo "DOWNLOADS_FINISHED failures=$failures"
