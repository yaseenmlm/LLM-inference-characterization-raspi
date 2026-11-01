// Read-only memory bandwidth, shaped like decode: threads split one large block between them.
// STREAM always mixes in writes and gives each thread its own arrays, so it isn't a close
// match for decode, which mostly reads weights.
// Build: gcc -O3 -mcpu=native -fopenmp read_bw.c -o read_bw
// Usage: OMP_NUM_THREADS=<n> ./read_bw

#include <omp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define TOTAL_BYTES (1024UL * 1024 * 1024) // 1 GiB, far larger than the 2MB L3 cache.
#define PASSES 20

int main(void) {
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
        double start = omp_get_wtime();

#pragma omp parallel for schedule(static) reduction(+ : sum)
        for (size_t i = 0; i < count; i++) {
            sum += data[i];
        }

        double elapsed = omp_get_wtime() - start;
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
