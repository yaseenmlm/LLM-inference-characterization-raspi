// Read-only memory bandwidth, shaped like decode: threads split one large block between them.
// STREAM always mixes in writes and gives each thread its own arrays, so it isn't a close
// match for decode, which mostly reads weights.
// Build on the Pi: gcc -O3 -mcpu=native -fopenmp read_bw.c -o read_bw
// Build on the PC: gcc -O3 -march=native -fopenmp read_bw.c -o read_bw.exe
// Usage: OMP_NUM_THREADS=<n> ./read_bw

#include <omp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#ifdef _WIN32
#include <malloc.h>
#include <windows.h>
#define aligned_alloc(alignment, size) _aligned_malloc(size, alignment) // MinGW has no aligned_alloc.
#define free _aligned_free

// omp_get_wtime only ticks every 1 ms here, too coarse for a pass of about 45 ms.
static double now_s(void) {
    LARGE_INTEGER ticks, frequency;
    QueryPerformanceCounter(&ticks);
    QueryPerformanceFrequency(&frequency);
    return (double)ticks.QuadPart / frequency.QuadPart;
}
#else
#define now_s omp_get_wtime
#endif

#define TOTAL_BYTES (1024UL * 1024 * 1024) // 1 GiB, far larger than the Pi's 2MB or the PC's 32MB L3.
#define PASSES 20

int main(void) {
#ifdef _WIN32
    // MinGW's OpenMP ignores OMP_PLACES, so use one logical CPU per core on the 8-core 7700X.
    SetProcessAffinityMask(GetCurrentProcess(), 0x5555);
#endif

    size_t count = TOTAL_BYTES / sizeof(uint64_t);
    uint64_t *data = aligned_alloc(4096, TOTAL_BYTES);
    if (data == NULL) {
        return 1;
    }

    // Nonzero values stop the kernel from backing the block with one shared zero page.
    for (size_t i = 0; i < count; i++) {
        data[i] = i;
    }

    double best_s = 1e9;
    uint64_t total = 0;

    // Keep the best pass, as STREAM does, and skip the first because it warms things up.
    for (int pass = 0; pass < PASSES; pass++) {
        uint64_t sum = 0;
        double start = now_s();

#pragma omp parallel for schedule(static) reduction(+ : sum)
        for (size_t i = 0; i < count; i++) {
            sum += data[i];
        }

        double elapsed = now_s() - start;
        total += sum; // Using the sum stops the compiler from deleting the read loop.
        if (pass > 0 && elapsed < best_s) {
            best_s = elapsed;
        }
    }

    printf("%d,%.1f,%llu\n", omp_get_max_threads(), TOTAL_BYTES / best_s / 1e6,
           (unsigned long long)total);
    free(data);
    return 0;
}
