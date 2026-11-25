// absorb_q / expand_v: tensor-core per-head GEMMs vs the per-output-warp kernels (error + time), ERNIE TP4 shapes.
#include "dsa_attn.cu"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <random>
#include <cmath>
#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) { printf("CUDA %s @%d: %s\n", #x, __LINE__, cudaGetErrorString(e_)); exit(1); } } while (0)

static double relL2(const std::vector<__nv_bfloat16>& a, const std::vector<__nv_bfloat16>& b, size_t* eq) {
    double num = 0, den = 0; *eq = 0;
    for (size_t i = 0; i < a.size(); ++i) { double x = __bfloat162float(a[i]), y = __bfloat162float(b[i]); num += (x - y) * (x - y); den += x * x; *eq += x == y; }
    return sqrt(num / std::max(den, 1e-30));
}

int main(int argc, char** argv) {
    const int R = argc > 1 ? atoi(argv[1]) : 1024, H = 16;
    std::mt19937 rng(5); std::normal_distribution<float> nd(0.f, 1.f);
    auto fill = [&](std::vector<__nv_bfloat16>& v, float s) { for (auto& x : v) x = __float2bfloat16(nd(rng) * s); };
    std::vector<__nv_bfloat16> q((size_t)R * H * 256), wk((size_t)H * 192 * 512), ol((size_t)R * H * 512), wv((size_t)H * 256 * 512);
    fill(q, 1.f); fill(wk, 0.05f); fill(ol, 1.f); fill(wv, 0.05f);
    auto up = [](auto& v) { void* d; CK(cudaMalloc(&d, v.size() * sizeof(v[0]))); CK(cudaMemcpy(d, v.data(), v.size() * sizeof(v[0]), cudaMemcpyHostToDevice)); return (__nv_bfloat16*)d; };
    auto *dq = up(q), *dwk = up(wk), *dol = up(ol), *dwv = up(wv);
    __nv_bfloat16 *qa, *qb, *va, *vb;
    CK(cudaMalloc(&qa, (size_t)R * H * 576 * 2)); CK(cudaMalloc(&qb, (size_t)R * H * 576 * 2));
    CK(cudaMalloc(&va, (size_t)R * H * 256 * 2)); CK(cudaMalloc(&vb, (size_t)R * H * 256 * 2));
    auto old_abs = [&] { tf_ernie55_dsa_absorb_q<<<dim3(128, H, R), 128>>>(dq, dwk, qa, R, H); };
    auto new_abs = [&] { tf_ernie55_dsa_absorb_q_mma<<<dim3(8, H, (R + 63) / 64), 128>>>(dq, dwk, qb, R, H); tf_ernie55_dsa_rope_copy<<<R, H * 64>>>(dq, qb, R, H); };
    auto old_v = [&] { tf_ernie55_dsa_expand_v<<<dim3(64, H, R), 128>>>(dol, dwv, va, R, H); };
    auto new_v = [&] { tf_ernie55_dsa_expand_v_mma<<<dim3(4, H, (R + 63) / 64), 128>>>(dol, dwv, vb, R, H); };
    old_abs(); new_abs(); old_v(); new_v(); CK(cudaDeviceSynchronize()); CK(cudaGetLastError());
    std::vector<__nv_bfloat16> A((size_t)R * H * 576), B(A.size()), C((size_t)R * H * 256), D(C.size());
    CK(cudaMemcpy(A.data(), qa, A.size() * 2, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(B.data(), qb, B.size() * 2, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(C.data(), va, C.size() * 2, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(D.data(), vb, D.size() * 2, cudaMemcpyDeviceToHost));
    size_t e1, e2;
    double r1 = relL2(A, B, &e1), r2 = relL2(C, D, &e2);
    printf("rows=%d absorb_q rel-L2 %.2e (bit-equal %.1f%%)   expand_v rel-L2 %.2e (bit-equal %.1f%%)\n", R, r1, 100.0 * e1 / A.size(), r2, 100.0 * e2 / C.size());
    cudaEvent_t a, b; cudaEventCreate(&a); cudaEventCreate(&b); float ms; const int it = 10;
    auto t = [&](const char* n, auto f) { cudaEventRecord(a); for (int i = 0; i < it; ++i) f(); cudaEventRecord(b); CK(cudaEventSynchronize(b)); cudaEventElapsedTime(&ms, a, b); printf("   %-10s %8.3f ms\n", n, ms / it); };
    t("old absorb", old_abs); t("mma absorb", new_abs); t("old expand", old_v); t("mma expand", new_v);
}
