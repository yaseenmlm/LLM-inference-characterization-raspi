#!/usr/bin/env bash
# Logs temperature, ARM clock and throttle state about once a second until killed.
# Usage: thermal_logger.sh <output.csv>

out="$1"
echo "epoch_s,temp_c,arm_hz,throttled" > "$out"

while true; do
    temp=$(vcgencmd measure_temp | sed "s/temp=//; s/'C//")
    clock=$(vcgencmd measure_clock arm | cut -d= -f2)
    throttled=$(vcgencmd get_throttled | cut -d= -f2)
    echo "$(date +%s),$temp,$clock,$throttled" >> "$out"
    sleep 1
done
