#!/usr/bin/env bash
# Runs read_bw at 1-4 threads, 3 repeats each. Safe to re-run: finished repeats are skipped.

set -u

REPO="$HOME/pi5-llm-inference"
CSV="$REPO/results/read_bw.csv"

governor=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)
if [ "$governor" != "performance" ]; then
    echo "ABORT: governor is $governor, expected performance"
    exit 1
fi

gcc -O3 -mcpu=native -fopenmp "$REPO/scripts/read_bw.c" -o "$REPO/scripts/read_bw"

[ -f "$CSV" ] || echo "epoch_s,threads,repeat,best_mb_s,throttled" > "$CSV"

for threads in 1 2 3 4; do
    for repeat in 1 2 3; do
        if grep -q "^[0-9]*,$threads,$repeat," "$CSV"; then
            echo "Skipping finished run: threads=$threads repeat=$repeat"
            continue
        fi

        line=$(OMP_NUM_THREADS=$threads OMP_PROC_BIND=spread "$REPO/scripts/read_bw")
        mb_s=$(echo "$line" | cut -d, -f2)
        flags=$(vcgencmd get_throttled | cut -d= -f2)
        echo "$(date +%s),$threads,$repeat,$mb_s,$flags" >> "$CSV"
        echo "Done: threads=$threads repeat=$repeat flags=$flags"
    done
done

echo "READ_BW_FINISHED"
