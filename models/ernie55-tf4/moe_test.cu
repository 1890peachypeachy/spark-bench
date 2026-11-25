// Parity + timing: expert-major MXFP4 MoE kernels vs the per-pick kernels (ERNIE 5.5 shapes, TP4 shard).
// Build: nvcc -O3 -std=c++17 -arch=sm_121a -I<dir with mxfp4_situ.cu> moe_test.cu -o moe_test
#include "mxfp4_situ.cu"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <random>
#include <algorithm>

#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) { printf("CUDA %s @%d: %s\n", #x, __LINE__, cudaGetErrorString(e_)); exit(1); } } while (0)

int main(int argc, char** argv) {
    const int R = argc > 1 ? atoi(argv[1]) : 256;
    const int E = 512, TOPK = 10, K = 2048, N_LOC = 512, N_OUT = 2048, K_LOC = 512;
    const int P = R * TOPK;
    const float beta = 4.0f, lbeta = 25.0f;
    std::mt19937 rng(7);
    auto rbytes = [&](std::vector<uint8_t>& v) { for (auto& b : v) b = rng() & 0xFF; };
    // weights: e2m1 codes random, scales near 2^0 (127 +- 3)
    std::vector<uint8_t> w1q((size_t)E * N_LOC * K / 2), w3q(w1q.size()), w1s((size_t)E * N_LOC * K / 32), w3s(w1s.size());
    std::vector<uint8_t> w2q((size_t)E * N_OUT * K_LOC / 2), w2s((size_t)E * N_OUT * K_LOC / 32);
    rbytes(w1q); rbytes(w3q); rbytes(w2q);
    for (auto* v : {&w1s, &w3s, &w2s}) for (auto& b : *v) b = 121 + rng() % 6;
    std::vector<__nv_bfloat16> x((size_t)R * K);
    std::normal_distribution<float> nd(0.f, 1.f);
    for (auto& a : x) a = __float2bfloat16(nd(rng));
    // routing: distinct experts per row, skewed so some experts are hot
    std::vector<int32_t> ids(P);
    std::vector<float> wts(P);
    for (int r = 0; r < R; ++r) {
        std::vector<int> pick;
        while ((int)pick.size() < TOPK) {
            int e = (rng() % 4 == 0) ? (int)(rng() % 32) : (int)(rng() % E);
            if (std::find(pick.begin(), pick.end(), e) == pick.end()) pick.push_back(e);
        }
        for (int t = 0; t < TOPK; ++t) { ids[r * TOPK + t] = pick[t]; wts[r * TOPK + t] = 0.05f + 0.1f * (rng() % 100) / 100.f; }
    }
    auto up = [](auto& v) { void* d; CK(cudaMalloc(&d, v.size() * sizeof(v[0]))); CK(cudaMemcpy(d, v.data(), v.size() * sizeof(v[0]), cudaMemcpyHostToDevice)); return d; };
    auto* d_w1q = (uint8_t*)up(w1q); auto* d_w3q = (uint8_t*)up(w3q); auto* d_w1s = (uint8_t*)up(w1s); auto* d_w3s = (uint8_t*)up(w3s);
    auto* d_w2q = (uint8_t*)up(w2q); auto* d_w2s = (uint8_t*)up(w2s);
    auto* d_x = (__nv_bfloat16*)up(x); auto* d_ids = (int32_t*)up(ids); auto* d_w = (float*)up(wts);
    __nv_bfloat16 *mid_a, *mid_b, *out_a, *out_b; float* part;
    int32_t *counts, *offsets, *cursor, *list;
    CK(cudaMalloc(&mid_a, (size_t)P * N_LOC * 2)); CK(cudaMalloc(&mid_b, (size_t)P * N_LOC * 2));
    CK(cudaMalloc(&out_a, (size_t)R * N_OUT * 2)); CK(cudaMalloc(&out_b, (size_t)R * N_OUT * 2));
    CK(cudaMalloc(&part, (size_t)P * N_OUT * 4));
    CK(cudaMalloc(&counts, E * 4)); CK(cudaMalloc(&offsets, (E + 1) * 4)); CK(cudaMalloc(&cursor, E * 4)); CK(cudaMalloc(&list, P * 4));

    auto old_path = [&]() {
        tf_ernie55_mxfp4_w13_situ<<<dim3((N_LOC + 3) / 4, TOPK, R), 128, K * 2>>>(d_x, d_w1q, d_w1s, d_w3q, d_w3s, d_ids, mid_a, R, TOPK, N_LOC, K, beta, lbeta);
        tf_ernie55_mxfp4_w2_combine<<<dim3((N_OUT + 3) / 4, R), 128, TOPK * K_LOC * 2>>>(mid_a, d_w2q, d_w2s, d_ids, d_w, out_a, R, TOPK, N_OUT, K_LOC);
    };
    auto new_path = [&]() {
        CK(cudaMemsetAsync(counts, 0, E * 4));
        tf_ernie55_route_count<<<(P + 255) / 256, 256>>>(d_ids, P, counts);
        tf_ernie55_route_scan<<<1, 1024>>>(counts, offsets, cursor, E);
        tf_ernie55_route_fill<<<(P + 255) / 256, 256>>>(d_ids, P, cursor, list);
        tf_ernie55_mxfp4_w13_grouped<<<dim3((N_LOC + 7) / 8, E), 256, TF_GROUPED_W13_BATCH * K * 2>>>(d_x, d_w1q, d_w1s, d_w3q, d_w3s, offsets, list, mid_b, TOPK, N_LOC, K, beta, lbeta);
        tf_ernie55_mxfp4_w2_grouped<<<dim3((N_OUT + 7) / 8, E), 256, TF_GROUPED_W2_BATCH * K_LOC * 2>>>(mid_b, d_w2q, d_w2s, offsets, list, part, N_OUT, K_LOC);
        tf_ernie55_moe_combine<<<dim3((N_OUT + 255) / 256, R), 256>>>(part, d_w, out_b, TOPK, N_OUT);
    };
    CK(cudaFuncSetAttribute(tf_ernie55_mxfp4_w2_combine, cudaFuncAttributeMaxDynamicSharedMemorySize, TOPK * K_LOC * 2));
    CK(cudaFuncSetAttribute(tf_ernie55_mxfp4_w13_grouped, cudaFuncAttributeMaxDynamicSharedMemorySize, TF_GROUPED_W13_BATCH * K * 2));
    old_path(); new_path(); CK(cudaDeviceSynchronize()); CK(cudaGetLastError());
    std::vector<uint16_t> ma((size_t)P * N_LOC), mb(ma.size()), oa((size_t)R * N_OUT), ob(oa.size());
    CK(cudaMemcpy(ma.data(), mid_a, ma.size() * 2, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(mb.data(), mid_b, mb.size() * 2, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(oa.data(), out_a, oa.size() * 2, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(ob.data(), out_b, ob.size() * 2, cudaMemcpyDeviceToHost));
    size_t dm = 0, dout = 0;
    for (size_t i = 0; i < ma.size(); ++i) dm += ma[i] != mb[i];
    for (size_t i = 0; i < oa.size(); ++i) dout += oa[i] != ob[i];
    printf("R=%d  mid mismatches %zu / %zu   out mismatches %zu / %zu   %s\n", R, dm, ma.size(), dout, oa.size(), (dm == 0 && dout == 0) ? "BIT-IDENTICAL" : "DIFFERENT");
    cudaEvent_t a, b; cudaEventCreate(&a); cudaEventCreate(&b); float ms;
    const int it = 20;
    cudaEventRecord(a); for (int i = 0; i < it; ++i) old_path(); cudaEventRecord(b); CK(cudaEventSynchronize(b)); cudaEventElapsedTime(&ms, a, b);
    printf("old per-pick  : %8.3f ms / layer\n", ms / it);
    cudaEventRecord(a); for (int i = 0; i < it; ++i) new_path(); cudaEventRecord(b); CK(cudaEventSynchronize(b)); cudaEventElapsedTime(&ms, a, b);
    printf("expert-major  : %8.3f ms / layer\n", ms / it);
    auto timeit = [&](const char* name, auto fn) {
        cudaEventRecord(a); for (int i = 0; i < it; ++i) fn(); cudaEventRecord(b); CK(cudaEventSynchronize(b));
        cudaEventElapsedTime(&ms, a, b); printf("   %-12s %8.3f ms\n", name, ms / it);
    };
    timeit("route", [&] { CK(cudaMemsetAsync(counts, 0, E * 4)); tf_ernie55_route_count<<<(P + 255) / 256, 256>>>(d_ids, P, counts);
        tf_ernie55_route_scan<<<1, 1024>>>(counts, offsets, cursor, E); tf_ernie55_route_fill<<<(P + 255) / 256, 256>>>(d_ids, P, cursor, list); });
    timeit("w13", [&] { tf_ernie55_mxfp4_w13_grouped<<<dim3((N_LOC + 7) / 8, E), 256, TF_GROUPED_W13_BATCH * K * 2>>>(d_x, d_w1q, d_w1s, d_w3q, d_w3s, offsets, list, mid_b, TOPK, N_LOC, K, beta, lbeta); });
    timeit("w2", [&] { tf_ernie55_mxfp4_w2_grouped<<<dim3((N_OUT + 7) / 8, E), 256, TF_GROUPED_W2_BATCH * K_LOC * 2>>>(mid_b, d_w2q, d_w2s, offsets, list, part, N_OUT, K_LOC); });
    timeit("combine", [&] { tf_ernie55_moe_combine<<<dim3((N_OUT + 255) / 256, R), 256>>>(part, d_w, out_b, TOPK, N_OUT); });
    // ---- tensor-core path: tolerance check vs the per-pick kernels, then timing
    const int smem13 = (2 * TF_MMA_BN + TF_MMA_MT * 16) * TF_MMA_LD * 2, smem2 = (TF_MMA_BN + TF_MMA_MT * 16) * TF_MMA_LD * 2;
    CK(cudaFuncSetAttribute(tf_ernie55_mxfp4_w13_mma, cudaFuncAttributeMaxDynamicSharedMemorySize, smem13));
    CK(cudaFuncSetAttribute(tf_ernie55_mxfp4_w2_mma, cudaFuncAttributeMaxDynamicSharedMemorySize, smem2));
    auto mma_path = [&]() {
        CK(cudaMemsetAsync(counts, 0, E * 4));
        tf_ernie55_route_count<<<(P + 255) / 256, 256>>>(d_ids, P, counts);
        tf_ernie55_route_scan<<<1, 1024>>>(counts, offsets, cursor, E);
        tf_ernie55_route_fill<<<(P + 255) / 256, 256>>>(d_ids, P, cursor, list);
        tf_ernie55_mxfp4_w13_mma<<<dim3((N_LOC + 63) / 64, E), 128, smem13>>>(d_x, d_w1q, d_w1s, d_w3q, d_w3s, offsets, list, mid_b, TOPK, N_LOC, K, beta, lbeta);
        tf_ernie55_mxfp4_w2_mma<<<dim3((N_OUT + 63) / 64, E), 128, smem2>>>(mid_b, d_w2q, d_w2s, offsets, list, part, N_OUT, K_LOC);
        tf_ernie55_moe_combine<<<dim3((N_OUT + 255) / 256, R), 256>>>(part, d_w, out_b, TOPK, N_OUT);
    };
    old_path(); mma_path(); CK(cudaDeviceSynchronize()); CK(cudaGetLastError());
    CK(cudaMemcpy(ma.data(), mid_a, ma.size() * 2, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(mb.data(), mid_b, mb.size() * 2, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(oa.data(), out_a, oa.size() * 2, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(ob.data(), out_b, ob.size() * 2, cudaMemcpyDeviceToHost));
    auto bf = [](uint16_t h) { uint32_t u = (uint32_t)h << 16; float f; memcpy(&f, &u, 4); return f; };
    auto cmp = [&](const char* nm, std::vector<uint16_t>& A, std::vector<uint16_t>& Bv) {
        double num = 0, den = 0, mx = 0; size_t exact = 0;
        for (size_t i = 0; i < A.size(); ++i) { double d = bf(A[i]) - bf(Bv[i]); num += d * d; den += (double)bf(A[i]) * bf(A[i]); mx = std::max(mx, fabs(d)); exact += A[i] == Bv[i]; }
        printf("   %-4s rel-L2 %.2e  max-abs %.3e  bit-equal %.1f%%\n", nm, sqrt(num / std::max(den, 1e-30)), mx, 100.0 * exact / A.size());
    };
    printf("tensor-core vs per-pick:\n"); cmp("mid", ma, mb); cmp("out", oa, ob);
    timeit("MMA total", mma_path);
    timeit("MMA w13", [&] { tf_ernie55_mxfp4_w13_mma<<<dim3((N_LOC + 63) / 64, E), 128, smem13>>>(d_x, d_w1q, d_w1s, d_w3q, d_w3s, offsets, list, mid_b, TOPK, N_LOC, K, beta, lbeta); });
    timeit("MMA w2", [&] { tf_ernie55_mxfp4_w2_mma<<<dim3((N_OUT + 63) / 64, E), 128, smem2>>>(mid_b, d_w2q, d_w2s, offsets, list, part, N_OUT, K_LOC); });
    timeit("old w13", [&] { tf_ernie55_mxfp4_w13_situ<<<dim3((N_LOC + 3) / 4, TOPK, R), 128, K * 2>>>(d_x, d_w1q, d_w1s, d_w3q, d_w3s, d_ids, mid_a, R, TOPK, N_LOC, K, beta, lbeta); });
    timeit("old w2", [&] { tf_ernie55_mxfp4_w2_combine<<<dim3((N_OUT + 3) / 4, R), 128, TOPK * K_LOC * 2>>>(mid_a, d_w2q, d_w2s, d_ids, d_w, out_a, R, TOPK, N_OUT, K_LOC); });
    return 0;
}
