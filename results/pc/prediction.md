# PC prediction

Written on 2026-11-01, before the PC sweep. The only PC decode figure that existed was one 8-token
build check on Llama 1B at 4 threads, which was not shown to the predictor and isn't data.

Inputs: 24.52 GB/s read bandwidth at 8 threads, Qwen Q2 0.676 GB, Qwen Q8 1.647 GB.

## As stated

> 36 for q2 and 18 for q8. reaches 90 percent of the ceiling due to limiting factors. Q2 will be
> limited by memory as CPU on pc is stronger than on pi

| Item | Prediction |
| --- | --- |
| Q2 ceiling at 8 threads | 36 tok/s |
| Q8 ceiling at 8 threads | 18 tok/s |
| Share of ceiling reached | 90% |
| Q2 limit at 1 thread | Memory |

## Checked against the formula

These checks were made before the sweep ran.

- Q2 ceiling: 24.52 / 0.676 = 36.27 tok/s, which matches the stated 36.
- Q8 ceiling: 24.52 / 1.647 = 14.89 tok/s, so the stated 18 is an arithmetic error.
- Q2 at 1 thread: the memory limit is 22.73 / 0.676 = 33.63 tok/s. Memory is the limit only if a
  7700X core is at least 33.63 / 5.31 = 6.3 times faster than a Pi core on this work. No value of
  `k` was stated.

## Final

Updated after the sweep ran, before any speeds were shown to the predictor.

> 1. update to 15
> 2. make k 6
> 3. dont know any limiting factors

| Item | Final prediction |
| --- | --- |
| Q2 ceiling at 8 threads | 36 tok/s |
| Q8 ceiling at 8 threads | 15 tok/s |
| Share of ceiling reached | 90%, so about 32.4 and 13.5 tok/s |
| CPU speed factor `k` | 6 |
| Q2 limit at 1 thread | Memory as stated, but `k` = 6 gives a CPU limit of 31.9 tok/s, below the 33.6 memory limit, so the method points to the CPU by a small margin |
| Cause of the gap below the ceiling | Unknown |
