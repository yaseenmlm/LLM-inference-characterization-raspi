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

## PC comparison

Hardware: AMD Ryzen 7 7700X (8 cores, 16 threads, one CCD), 2 x 16 GB DDR5 reported at 3600 MT/s,
Windows 11 Home 10.0.26200, Best Performance power mode on mains. Runs use the CPU only. The
RTX 3060 Ti isn't used.

Software: llama.cpp `5047748`, GCC 16.2.0 (WinLibs), `-DGGML_NATIVE=ON`, plus
`-D_WIN32_WINNT=0x0A00` so that cpp-httplib compiles. The model files have the same SHA-256 values
as the Pi's. The toolchain is copied to `C:\gcc16` because the GCC linker fails on the space in the
user's folder name.

Read bandwidth comes from `scripts/run_read_bw_pc.sh`. The first run is kept in
`results/pc/rejected/read_bw_1ms_timer.csv` and isn't used: `omp_get_wtime` ticks every 1 ms on
MinGW, so passes of about 45 ms landed on whole milliseconds, an error of about 2%. That run also
wasn't pinned, because MinGW's OpenMP ignores `OMP_PLACES`. `read_bw.c` now uses
`QueryPerformanceCounter` on Windows and limits itself to one logical CPU per core (mask `0x5555`).
The change doesn't affect the Pi build.

`scripts/run_sweep_pc.py` runs 7 models at 1, 2, 4, 6 and 8 threads with the Pi's workload: a
256-token prefill call and a 128-token decode call, 3 repeats each. The process is pinned to mask
`0x5555`, which was confirmed on a live `llama-bench` process. Windows has no throttle flags, so
the script logs the effective clock at 1 Hz. This rule was set before the sweep ran: a config is
rejected if any sample in either phase falls below the 4.5 GHz base clock. No CPU temperature was
recorded on the PC.

All 35 configs finished, with no clock sample below 4.5 GHz. Decode slowed as threads were added,
so `scripts/run_pc_check.py` repeated Qwen Q2 decode at 8 threads with one setting changed at a
time (`results/pc/checks/q2_t8_decode.json`):

| Variant | tok/s | Std dev |
| --- | ---: | ---: |
| Sweep settings | 16.52 | 0.09 |
| Unpinned | 15.91 | 0.49 |
| `OMP_WAIT_POLICY=active` | 16.66 | 0.19 |
| `--poll 100` | 16.76 | 0.60 |

None of them restored the 1-thread speed of 27.25 tok/s, so pinning and these wait settings don't
explain the slowdown. These checks don't rule out the Windows build itself.

## Cooler repair

On 2026-11-02 the Pi was dropped and the cooler came loose, after all Pi results above were
collected. Before the repair, a 4-copy `yes` load reached 75.7°C in 90 seconds and stopped at the
75°C guard. After it, the same load reached 52.7°C at 120 seconds, and `cooling_gate_20261102_133003`
passed with a maximum of 70.8°C, 2.4 GHz and flags `0x0`. Read bandwidth at 4 threads was 12.72 GB/s
against 12.74 before, and all seven model checksums matched. The governor was `ondemand` for these
checks, and room temperature wasn't recorded. No results in the README come from after the repair.
