// Microbench for TensorFold's FP8G qmmf decode GEMV on GB10: time per call vs K-slices (cluster or reduce).
// Build: nvcc -O3 -std=c++17 -arch=sm_121a -I<tf>/zig/kernels/cuda qmmf_bench.cu -o qmmf_bench
#include "qmmf.cu"
#include <cstdio>
#include <cstdlib>
#include <vector>

using namespace tf_qmmf;

#define CK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { printf("CUDA %s @%d: %s\n", #x, __LINE__, cudaGetErrorString(e)); exit(1); } } while (0)

static const int COPIES = 24;  // rotate weights so L2 cannot hold them

template <bool CL>
float run(int M, int N, int K, int SK, bool reduce, int iters) {
    int npad = (N + 127) / 128 * 128;
    size_t wbytes = (size_t)npad * K, sbytes = (size_t)npad * (K / 64) * 4 + 4096;
    std::vector<unsigned char*> W(COPIES); std::vector<uint8_t*> S(COPIES);
    for (int c = 0; c < COPIES; ++c) { CK(cudaMalloc(&W[c], wbytes)); CK(cudaMemset(W[c], 0x22, wbytes)); CK(cudaMalloc(&S[c], sbytes)); CK(cudaMemset(S[c], 0, sbytes)); }
    __nv_bfloat16* x; CK(cudaMalloc(&x, (size_t)M * K * 2)); CK(cudaMemset(x, 0, (size_t)M * K * 2));
    void* y; CK(cudaMalloc(&y, (size_t)M * N * 4));
    float* part; CK(cudaMalloc(&part, (size_t)SK * M * N * 4 + 16));
    auto kfn = qmmf_kernel<FP8G, 16, 64, 1, 4, 4, false, CL, false>;
    int smem = Tile<FP8G, 16, 64, 1, 4, 4>::SMEM;
    CK(cudaFuncSetAttribute(kfn, cudaFuncAttributeMaxDynamicSharedMemorySize, smem));
    if (CL && SK > 8) CK(cudaFuncSetAttribute(kfn, cudaFuncAttributeNonPortableClusterSizeAllowed, 1));
    int tiles = (N + 63) / 64, rows_t = (M + 15) / 16;
    cudaLaunchConfig_t cfg = {};
    cfg.gridDim = dim3(rows_t * tiles, 1, SK); cfg.blockDim = dim3(128); cfg.dynamicSmemBytes = smem;
    cudaLaunchAttribute at[1]; int na = 0;
    if (CL) { at[0].id = cudaLaunchAttributeClusterDimension; at[0].val.clusterDim.x = 1; at[0].val.clusterDim.y = 1; at[0].val.clusterDim.z = SK; na = 1; }
    cfg.attrs = at; cfg.numAttrs = na;
    int band = 1; float* p = reduce ? part : nullptr;
    long long total = (long long)M * N;
    auto launch = [&](int c) {
        CK(cudaLaunchKernelEx(&cfg, kfn, (const __nv_bfloat16*)x, (const unsigned char*)W[c], (const uint8_t*)S[c], 1.0f, y, p, M, N, K, SK, npad, K, band));
        if (reduce) reduce_kernel<false><<<(total + 255) / 256, 256>>>(part, y, total, SK, 1.0f);
    };
    for (int i = 0; i < 20; ++i) launch(i % COPIES);
    CK(cudaDeviceSynchronize());
    cudaEvent_t a, b; cudaEventCreate(&a); cudaEventCreate(&b);
    cudaEventRecord(a);
    for (int i = 0; i < iters; ++i) launch(i % COPIES);
    cudaEventRecord(b); CK(cudaEventSynchronize(b));
    float ms; cudaEventElapsedTime(&ms, a, b);
    CK(cudaGetLastError());
    for (int c = 0; c < COPIES; ++c) { cudaFree(W[c]); cudaFree(S[c]); }
    cudaFree(x); cudaFree(y); cudaFree(part);
    return ms * 1000.f / iters;
}

int main(int argc, char** argv) {
    int M = argc > 1 ? atoi(argv[1]) : 8;
    int shapes[][2] = {{512, 4096}, {1024, 4096}, {2048, 4096}, {4096, 2048}, {8192, 1024}, {2048, 1024}, {4096, 512}, {1536, 4096}, {3072, 4096}, {10240, 1024}};
    printf("M=%d  (us per call, GB/s of weight bytes)\n", M);
    for (auto& s : shapes) {
        int N = s[0], K = s[1];
        double mb = (double)N * K * (1 + 4.0 / 64) / 1e6;  // codes + fp32 scales a 64
        int groups = K / 64;
        printf("N=%5d K=%5d (%.1f MB): ", N, K, mb);
        for (int sk : {1, 2, 4, 8, 16, 32}) {
            if (groups % sk || (sk > 1 && groups / sk < 4)) continue;
            float t = sk == 1 ? run<false>(M, N, K, 1, false, 200) : sk <= 8 ? run<true>(M, N, K, sk, false, 200) : run<false>(M, N, K, sk, true, 200);
            printf(" sk%-2d %6.1fus %4.0f |", sk, t, mb * 1e3 / t);
        }
        printf("\n");
    }
}
