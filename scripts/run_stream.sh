#!/usr/bin/env bash
# Measures memory bandwidth with STREAM at 1-4 threads, 3 repeats each.
# This is the bandwidth input to the roofline. Safe to re-run: finished repeats are skipped.

set -u

REPO="$HOME/pi5-llm-inference"
WORK="$HOME/stream"
CSV="$REPO/results/stream.csv"

# Refuse to collect data unless the machine is in its benchmark state.
governor=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)
if [ "$governor" != "performance" ]; then
    echo "ABORT: governor is $governor, expected performance"
    exit 1
fi
if [ "$(vcgencmd get_throttled | cut -d= -f2)" != "0x0" ]; then
    echo "ABORT: throttle flags are set, reboot first"
    exit 1
fi

mkdir -p "$WORK"
if [ ! -f "$WORK/stream.c" ]; then
    curl -fL -o "$WORK/stream.c" https://raw.githubusercontent.com/jeffhammond/STREAM/master/stream.c
fi
sha256sum "$WORK/stream.c"

# 40M doubles is 320MB per array, far larger than the 2MB L3, so STREAM measures DRAM
# rather than cache. -fopenmp lets OMP_NUM_THREADS set the thread count.
gcc -O3 -mcpu=native -fopenmp -DSTREAM_ARRAY_SIZE=40000000 -DNTIMES=20 \
    "$WORK/stream.c" -o "$WORK/stream"

[ -f "$CSV" ] || echo "epoch_s,threads,repeat,kernel,best_mb_s,throttled" > "$CSV"

for threads in 1 2 3 4; do
    for repeat in 1 2 3; do
        if grep -q "^[0-9]*,$threads,$repeat,Triad," "$CSV"; then
            echo "Skipping finished run: threads=$threads repeat=$repeat"
            continue
        fi

        output=$(OMP_NUM_THREADS=$threads OMP_PROC_BIND=spread "$WORK/stream")
        now=$(date +%s)
        flags=$(vcgencmd get_throttled | cut -d= -f2)

        # Keep every kernel. Triad is the most memory-heavy, but Copy and Add are useful checks.
        echo "$output" | awk -v now="$now" -v t="$threads" -v r="$repeat" -v f="$flags" \
            '/^(Copy|Scale|Add|Triad):/ { sub(":", "", $1); print now "," t "," r "," $1 "," $2 "," f }' \
            >> "$CSV"
        echo "Done: threads=$threads repeat=$repeat flags=$flags"
    done
done

echo "STREAM_FINISHED"
