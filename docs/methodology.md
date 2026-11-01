# Methodology

## Hardware setup

- Raspberry Pi 5 8GB, active cooler, SanDisk 128GB microSD, Wi-Fi.
- The first sweep ran in the case with the **lid off**. With the lid closed, the Pi reached
  85.1°C and throttled under sustained load.
- The 4-thread re-runs ran **out of the case**, on the active cooler alone, with no desk fan.
- Power was not measured because no USB-C power meter was available. No tok/J figures
  are reported.

## Software

- Debian GNU/Linux 13 (trixie), kernel 6.18.50+rpt-rpi-2712. OS updates are frozen.
- llama.cpp commit `5047748f114564fcf271e6a648f60e2d2eae6264`, built with GCC 14.2.0:
  `cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON`
- CPU flags chosen by the build: `-mcpu=cortex-a76+crc+crypto+dotprod+noi8mm+nosve+nosme`
- Model files and their SHA-256 hashes are listed in `scripts/download_models.sh`.
- STREAM: `stream.c` from `jeffhammond/STREAM`, SHA-256
  `c388924eb140fda95f534cdb808ae7f1f8ebb18da41d8aec1b512a3c8d303c9b`.

## Perplexity

`scripts/run_perplexity.sh` scores Qwen2.5 1.5B at each quant on 20 chunks of wikitext-2
`wiki.test.raw` with `-c 512`. SHA-256 of that file:
`173c87a53759e0201f33e0ccf978e510c2042d7f2cb78229d9a50d79b9e7dd08`.
Throttling affects its speed but not its scores, so these runs have no thermal rejection.

## Cooling gate

`scripts/cooling_gate.sh` starts only if `get_throttled` is `0x0`. It runs the sweep's two
worst thermal loads: the Llama 3B 4-thread prefill, then a cooldown to 50°C, then 5 minutes of
4-thread decode. Each load must hold at least 2.39 GHz with no throttle flags after a
30-second warm-up.

Gate history, all in `results/`:

- `cooling_gate_20261030_183327.csv`: failed with the lid closed.
- `cooling_gate_20261030_190123.csv`: open case, but stale throttle flags, so it doesn't count.
- `cooling_gate_20261030_194525.csv`: passed, but it tested decode only. Four 4-thread runs
  then throttled during the sweep, because prefill runs hotter than decode.
- `cooling_gate_20261031_123526.csv`: failed. It held prefill for about 135 seconds. It
  throttled at 84.0°C and dropped to 1.5 GHz during prefill, while the decode that followed held
  2.4 GHz with no live flags at up to 79.6°C.
- `cooling_gate_20261031_150827_prefill.csv` and `..._decode.csv`: failed under the split gate.
  The 7B prefill call took 122 seconds, not the 70 estimated beforehand. The soft temperature
  flag latched 105 seconds in and was live from 116 to 120 seconds, at up to 82.3°C with the
  clock at 2.4 GHz. Decode ran 5 minutes after a cooldown with no live flags, at up to 79.0°C.

After the first of those failures the gate was deliberately changed to match the real worst
case, and the benchmark was split as described below. This loosens the earlier prefill test.
After the second, 7B prefill was dropped and the gate moved to Llama 3B prefill, the longest one
still measured. 7B prefill could not be measured without throttling on this cooling, so 7B
reports decode only. The roofline needs only decode.

Passing run: `results/cooling_gate_20261031_152521_prefill.csv` and `..._decode.csv`, at up to
78.5°C in prefill and 80.7°C in decode, with the clock at 2.4 GHz and `get_throttled` still `0x0`
at the end. The margin is thin, so per-run rejection remains the real guard.

## Benchmark runs

The first sweep ran prefill and decode in one `llama-bench` call. The 4-thread re-runs use one
call for each, with a cooldown to 50°C before each, so prefill heat can't carry into decode.
`run_sweep.py --split-check` repeats Llama 1B and Qwen Q4 at 4 threads under the split method
to check whether splitting changes their speeds. Combined versus split, tok/s:

| Config | Prefill combined | Prefill split | Decode combined | Decode split |
| --- | --- | --- | --- | --- |
| Llama 1B t4 | 85.49 | 85.26 | 14.34 | 14.56 |
| Qwen Q4 t4 | 62.25 | 62.11 | 11.80 | 12.06 |

Prefill matched to within 0.3%. Decode ran 1.5% and 2.2% faster when split, which is more than
the variation between repeats, so splitting is not fully neutral. The cause is unknown. Results
from the two methods differ by about 2% in decode, and comparisons across them carry that
uncertainty.

Qwen Q8 at 4 threads was set aside because its prefill looked low at 43.53 tok/s, against 67.56
at 3 threads. The split re-run measured 42.78 with no throttling, so the low value reproduces.

Any throttled phase rejects the whole config, whatever the gate result.
