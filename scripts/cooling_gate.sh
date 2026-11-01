#!/usr/bin/env bash
# Cooling gate: must pass before any benchmark number counts.
# Runs the sweep's two worst thermal loads, each from a cool start like the split sweep:
# the longest prefill it measures (Llama 3B), a cooldown, then 5 minutes of 4-thread decode.

set -u

REPO="$HOME/pi5-llm-inference"
BENCH="$HOME/llama.cpp/build/bin/llama-bench"
MODEL="$HOME/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
WARMUP_S=30     # The clock can legitimately dip while the model loads.
GATE_S=300
COOLDOWN_C=50.0     # Same start temperature as the sweep.
COOLDOWN_LIMIT_S=600
MIN_HZ=2390000000   # Allows for measure_clock reporting just under the nominal 2.4 GHz.

stamp="$(date +%Y%m%d_%H%M%S)"
prefill_csv="$REPO/results/cooling_gate_${stamp}_prefill.csv"
decode_csv="$REPO/results/cooling_gate_${stamp}_decode.csv"
mkdir -p "$REPO/results"

echo "Idle before load: $(vcgencmd measure_temp), $(vcgencmd get_throttled)"

# get_throttled history bits stay set until reboot, so old events would fail this run.
if [ "$(vcgencmd get_throttled | cut -d= -f2)" != "0x0" ]; then
    echo "GATE_RESULT=INVALID throttle flags already set, reboot first"
    exit 1
fi

# Reading the model into the page cache makes loading quick, so warmup hides no real load.
cat "$MODEL" > /dev/null

summarize() {
    awk -F, -v warmup="$WARMUP_S" -v min_hz="$MIN_HZ" -v label="$2" '
        NR == 2 { start = $1 }
        NR > 1 && $1 >= start + warmup {
            n++
            if (n == 1 || $2 > max_temp) max_temp = $2
            if (n == 1 || $3 < low_hz) low_hz = $3
            if ($3 < min_hz) slow++
            if ($4 != "0x0") throttled++
        }
        END {
            pass = (n > 0 && slow == 0 && throttled == 0)
            printf "%s: samples=%d max_temp_c=%.1f min_arm_hz=%d samples_below_min=%d samples_throttled=%d\n",
                label, n, max_temp, low_hz, slow, throttled
            exit !pass
        }
    ' "$1"
}

# The same call the sweep makes for Llama 3B, which is its longest measured 4-thread prefill.
"$REPO/scripts/thermal_logger.sh" "$prefill_csv" &
logger_pid=$!
"$BENCH" -m "$MODEL" -t 4 -p 256 -n 0 -r 3 > /dev/null 2>&1
bench_exit=$?
kill "$logger_pid"

if [ "$bench_exit" -ne 0 ]; then
    echo "GATE_RESULT=INVALID prefill failed, exit=$bench_exit"
    exit 1
fi

cool_start=$SECONDS
while [ "$(vcgencmd measure_temp | sed "s/temp=//; s/'C//" | awk -v limit="$COOLDOWN_C" '{ print ($1 > limit) }')" = "1" ]; do
    if [ "$((SECONDS - cool_start))" -gt "$COOLDOWN_LIMIT_S" ]; then
        echo "GATE_RESULT=INVALID still above ${COOLDOWN_C}C after ${COOLDOWN_LIMIT_S}s"
        exit 1
    fi
    sleep 5
done

# -r 100 asks for more decode than the window can hold, so timeout always ends this load.
"$REPO/scripts/thermal_logger.sh" "$decode_csv" &
logger_pid=$!
timeout "$((WARMUP_S + GATE_S))" "$BENCH" -m "$MODEL" -t 4 -p 0 -n 128 -r 100 > /dev/null 2>&1
bench_exit=$?
kill "$logger_pid"

# Exit 124 means timeout stopped it, so the load lasted the full window.
if [ "$bench_exit" -ne 124 ]; then
    echo "GATE_RESULT=INVALID load ended early, exit=$bench_exit"
    exit 1
fi

summarize "$prefill_csv" prefill
prefill_ok=$?
summarize "$decode_csv" decode
decode_ok=$?

if [ "$prefill_ok" -eq 0 ] && [ "$decode_ok" -eq 0 ]; then
    echo "GATE_RESULT=PASS"
else
    echo "GATE_RESULT=FAIL"
fi

echo "Final: $(vcgencmd get_throttled), csvs=$prefill_csv $decode_csv"
