#include "ops.cu"
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <random>
#include <cmath>
#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) { printf("CUDA %s @%d: %s\n", #x, __LINE__, cudaGetErrorString(e_)); exit(1); } } while (0)
int main(int argc, char** argv) {
    const int R = argc > 1 ? atoi(argv[1]) : 1024, HC = 16384;
    std::mt19937 rng(9); std::normal_distribution<float> nd(0.f, 1.f);
    std::vector<__nv_bfloat16> res((size_t)R * HC); for (auto& v : res) v = __float2bfloat16(nd(rng));
    std::vector<float> fn((size_t)24 * HC); for (auto& v : fn) v = nd(rng) * 0.01f;
    __nv_bfloat16* dr; float *df, *ma, *mb, *sa, *sb;
    CK(cudaMalloc(&dr, res.size() * 2)); CK(cudaMemcpy(dr, res.data(), res.size() * 2, cudaMemcpyHostToDevice));
    CK(cudaMalloc(&df, fn.size() * 4)); CK(cudaMemcpy(df, fn.data(), fn.size() * 4, cudaMemcpyHostToDevice));
    CK(cudaMalloc(&ma, R * 24 * 4)); CK(cudaMalloc(&mb, R * 24 * 4)); CK(cudaMalloc(&sa, R * 4)); CK(cudaMalloc(&sb, R * 4));
    auto o = [&] { tf_ernie55_mhc_pre_gemv<<<dim3(24, R), 256>>>(dr, df, ma, sa, R, HC); };
    auto n = [&] { tf_ernie55_mhc_pre_tiled<<<(R + 7) / 8, 256>>>(dr, df, mb, sb, R, HC); };
    o(); n(); CK(cudaDeviceSynchronize()); CK(cudaGetLastError());
    std::vector<float> A(R * 24), B(R * 24), SA(R), SB(R);
    CK(cudaMemcpy(A.data(), ma, A.size() * 4, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(B.data(), mb, B.size() * 4, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(SA.data(), sa, R * 4, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(SB.data(), sb, R * 4, cudaMemcpyDeviceToHost));
    double num = 0, den = 0, n2 = 0, d2 = 0;
    for (size_t i = 0; i < A.size(); ++i) { num += (A[i] - B[i]) * (A[i] - B[i]); den += A[i] * A[i]; }
    for (int i = 0; i < R; ++i) { n2 += (SA[i] - SB[i]) * (SA[i] - SB[i]); d2 += SA[i] * SA[i]; }
    printf("rows=%d mix rel-L2 %.2e  sqrsum rel-L2 %.2e\n", R, sqrt(num / den), sqrt(n2 / d2));
    cudaEvent_t a, b; cudaEventCreate(&a); cudaEventCreate(&b); float ms; const int it = 20;
    cudaEventRecord(a); for (int i = 0; i < it; ++i) o(); cudaEventRecord(b); CK(cudaEventSynchronize(b)); cudaEventElapsedTime(&ms, a, b); printf("   old   %7.3f ms\n", ms / it);
    cudaEventRecord(a); for (int i = 0; i < it; ++i) n(); cudaEventRecord(b); CK(cudaEventSynchronize(b)); cudaEventElapsedTime(&ms, a, b); printf("   tiled %7.3f ms\n", ms / it);
}
