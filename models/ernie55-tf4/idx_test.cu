// Indexer: tensor-core scores vs tf_ernie55_dsa_indexer_scores (score error, selected-set overlap, time).
#include "dsa_attn.cu"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <random>
#include <set>
#include <algorithm>
#include <cmath>
#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) { printf("CUDA %s @%d: %s\n", #x, __LINE__, cudaGetErrorString(e_)); exit(1); } } while (0)

int main(int argc, char** argv) {
    const int R = 64, T = argc > 1 ? atoi(argv[1]) : 13000, W = 128, TOPK = 2048;
    std::mt19937 rng(3); std::normal_distribution<float> nd(0.f, 1.f);
    std::vector<__nv_bfloat16> q((size_t)R * 64 * 128), k((size_t)(T + R) * 128), w((size_t)R * 64);
    for (auto& v : q) v = __float2bfloat16(nd(rng) * 0.5f);
    for (auto& v : k) v = __float2bfloat16(nd(rng) * 0.5f);
    for (auto& v : w) v = __float2bfloat16(nd(rng));
    std::vector<int32_t> pos(R);
    for (int r = 0; r < R; ++r) pos[r] = T + r;  // consecutive rows at the end of a T-token context
    const int max_older = pos[R - 1] + 1 - W;
    auto up = [](auto& v) { void* d; CK(cudaMalloc(&d, v.size() * sizeof(v[0]))); CK(cudaMemcpy(d, v.data(), v.size() * sizeof(v[0]), cudaMemcpyHostToDevice)); return d; };
    auto* dq = (__nv_bfloat16*)up(q); auto* dk = (__nv_bfloat16*)up(k); auto* dw = (__nv_bfloat16*)up(w); auto* dp = (int32_t*)up(pos);
    float *sa, *sb; CK(cudaMalloc(&sa, (size_t)R * max_older * 4)); CK(cudaMalloc(&sb, (size_t)R * max_older * 4));
    int32_t *ia, *ib, *ca, *cb;
    CK(cudaMalloc(&ia, (size_t)R * (TOPK + W) * 4)); CK(cudaMalloc(&ib, (size_t)R * (TOPK + W) * 4)); CK(cudaMalloc(&ca, R * 4)); CK(cudaMalloc(&cb, R * 4));
    const float wscale = 1.0f / (sqrtf(128.f) * sqrtf(64.f));
    const int smem = 128 * TF_IDX_LD * 2 + 4 * 64 * 4;
    CK(cudaFuncSetAttribute(tf_ernie55_dsa_indexer_scores_mma, cudaFuncAttributeMaxDynamicSharedMemorySize, smem));
    auto old_k = [&] { tf_ernie55_dsa_indexer_scores<<<dim3((max_older + 3) / 4, R), 128>>>(dq, dk, dw, dp, sa, R, max_older, W, wscale); };
    auto new_k = [&] { tf_ernie55_dsa_indexer_scores_mma<<<dim3((max_older + 63) / 64, R), 128, smem>>>(dq, dk, dw, dp, sb, R, max_older, W, wscale); };
    old_k(); new_k(); CK(cudaDeviceSynchronize()); CK(cudaGetLastError());
    tf_ernie55_dsa_select_topk<<<R, 256>>>(sa, dp, ia, ca, R, max_older, TOPK, W);
    tf_ernie55_dsa_select_topk<<<R, 256>>>(sb, dp, ib, cb, R, max_older, TOPK, W);
    CK(cudaDeviceSynchronize());
    std::vector<float> A((size_t)R * max_older), Bv(A.size());
    CK(cudaMemcpy(A.data(), sa, A.size() * 4, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(Bv.data(), sb, Bv.size() * 4, cudaMemcpyDeviceToHost));
    double num = 0, den = 0; size_t bad = 0;
    for (size_t i = 0; i < A.size(); ++i) {
        if (A[i] < -1e37f || Bv[i] < -1e37f) { bad += (A[i] < -1e37f) != (Bv[i] < -1e37f); continue; }
        double d = A[i] - Bv[i]; num += d * d; den += (double)A[i] * A[i];
    }
    std::vector<int32_t> IA((size_t)R * (TOPK + W)), IB(IA.size()), CA(R), CB(R);
    CK(cudaMemcpy(IA.data(), ia, IA.size() * 4, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(IB.data(), ib, IB.size() * 4, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(CA.data(), ca, R * 4, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(CB.data(), cb, R * 4, cudaMemcpyDeviceToHost));
    double overlap = 0;
    for (int r = 0; r < R; ++r) {
        std::set<int> sA(IA.begin() + (size_t)r * (TOPK + W), IA.begin() + (size_t)r * (TOPK + W) + CA[r]);
        int same = 0; for (int j = 0; j < CB[r]; ++j) same += sA.count(IB[(size_t)r * (TOPK + W) + j]);
        overlap += (double)same / std::max(CA[r], 1);
    }
    printf("T=%d rows=%d  score rel-L2 %.2e  mask mismatches %zu  selected-set overlap %.4f\n", T, R, sqrt(num / den), bad, overlap / R);
    cudaEvent_t a, b; cudaEventCreate(&a); cudaEventCreate(&b); float ms; const int it = 10;
    cudaEventRecord(a); for (int i = 0; i < it; ++i) old_k(); cudaEventRecord(b); CK(cudaEventSynchronize(b)); cudaEventElapsedTime(&ms, a, b);
    printf("   old  %8.3f ms per 64-row slice\n", ms / it);
    cudaEventRecord(a); for (int i = 0; i < it; ++i) new_k(); cudaEventRecord(b); CK(cudaEventSynchronize(b)); cudaEventElapsedTime(&ms, a, b);
    printf("   mma  %8.3f ms per 64-row slice\n", ms / it);
}
