#!/usr/bin/env bash
# Runs read_bw on the PC at 1-8 threads, 3 repeats each, from Git Bash.
# Safe to re-run: finished repeats are skipped.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CSV="$REPO/results/pc/read_bw.csv"
export PATH="/c/gcc16/bin:$PATH"

# Windows has no governor file. Either of these two settings is the PC's performance mode.
HIGH_PERFORMANCE=8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
BEST_PERFORMANCE=ded574b5-45a0-4f42-8737-46345c09c238
POWER_KEY='HKLM\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes'

# MSYS_NO_PATHCONV stops Git Bash from rewriting the /flags as file paths.
plan=$(MSYS_NO_PATHCONV=1 powercfg /getactivescheme)
overlay=$(MSYS_NO_PATHCONV=1 reg query "$POWER_KEY" /v ActiveOverlayAcPowerScheme 2>/dev/null)
if ! echo "$plan $overlay" | grep -qE "$HIGH_PERFORMANCE|$BEST_PERFORMANCE"; then
    echo "ABORT: PC is not in performance mode"
    exit 1
fi

mkdir -p "$REPO/results/pc"
gcc -O3 -march=native -fopenmp "$REPO/scripts/read_bw.c" -o "$REPO/scripts/read_bw.exe"

[ -f "$CSV" ] || echo "epoch_s,threads,repeat,best_mb_s" > "$CSV"

for threads in 1 2 4 6 8; do
    for repeat in 1 2 3; do
        if grep -q "^[0-9]*,$threads,$repeat," "$CSV"; then
            echo "Skipping finished run: threads=$threads repeat=$repeat"
            continue
        fi

        line=$(OMP_NUM_THREADS=$threads "$REPO/scripts/read_bw.exe")
        mb_s=$(echo "$line" | cut -d, -f2)
        echo "$(date +%s),$threads,$repeat,$mb_s" >> "$CSV"
        echo "Done: threads=$threads repeat=$repeat mb_s=$mb_s"
    done
done

echo "READ_BW_FINISHED"
