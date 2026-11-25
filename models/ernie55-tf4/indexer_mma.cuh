// Lightning Indexer scores on tensor cores (Spark, 2026-11-24; appended to dsa_attn.cu).
// Same contract as tf_ernie55_dsa_indexer_scores: score[r, t] = sum_h (w[r,h] * scale) * relu(q[r,h,:] . k[t,:])
// for t < n_older(r), -1e38 beyond. One block: one query row (its 64 heads) x 64 key tokens, four warps of 16 heads;
// mma.sync m16n8k16 bf16 -> fp32 over the 128 dims, then relu, the weighted head sum (lanes, then warps).
#define TF_IDX_LD 136  // bf16 row stride: 272 bytes, conflict-free fragment loads

__device__ __forceinline__ void idx_mma16816(float* c, const uint32_t* a, const uint32_t* b) {
    asm volatile(
        "mma.sync.aligned.m16n8k16.row.col.f32.bf16.bf16.f32 {%0,%1,%2,%3}, {%4,%5,%6,%7}, {%8,%9}, {%0,%1,%2,%3};\n"
        : "+f"(c[0]), "+f"(c[1]), "+f"(c[2]), "+f"(c[3])
        : "r"(a[0]), "r"(a[1]), "r"(a[2]), "r"(a[3]), "r"(b[0]), "r"(b[1]));
}

// Launch: grid=(ceil(max_older / 64), rows), block=(128), smem = (64 + 64) * TF_IDX_LD * 2 + 4 * 64 * 4.
extern "C" __global__ void __launch_bounds__(128) tf_ernie55_dsa_indexer_scores_mma(
    const __nv_bfloat16* __restrict__ q_idx,    // [rows, 64, 128]
    const __nv_bfloat16* __restrict__ idx_k,    // [capacity, 128]
    const __nv_bfloat16* __restrict__ weights,  // [rows, 64]
    const int32_t* __restrict__ positions,      // [rows]
    float* __restrict__ scores,                 // [rows, max_older]
    int rows, int max_older, int window_size, float weights_scale) {
    const int r = blockIdx.y;
    const int t0 = blockIdx.x * 64;
    if (r >= rows || t0 >= max_older) return;
    const int n_older = positions[r] - window_size + 1;
    extern __shared__ __align__(16) __nv_bfloat16 sm[];
    __nv_bfloat16* qs = sm;                       // [64 heads][LD]
    __nv_bfloat16* ks = qs + 64 * TF_IDX_LD;      // [64 tokens][LD]
    float* red = reinterpret_cast<float*>(ks + 64 * TF_IDX_LD);  // [4 warps][64 tokens]
    const int warp = threadIdx.x >> 5, lane = threadIdx.x & 31, g = lane >> 2, tq = lane & 3;

    if (t0 >= n_older) {  // the whole tile is past this row's older tokens
        for (int i = threadIdx.x; i < 64; i += blockDim.x)
            if (t0 + i < max_older) scores[(int64_t)r * max_older + t0 + i] = -1e38f;
        return;
    }
    // 64 x 128 bf16 each: 16 bytes a thread-step
    const __nv_bfloat16* qr = q_idx + (int64_t)r * 64 * 128;
    for (int i = threadIdx.x; i < 64 * 16; i += blockDim.x) {
        const int row = i >> 4, c = (i & 15) * 8;
        *reinterpret_cast<uint4*>(qs + row * TF_IDX_LD + c) = *reinterpret_cast<const uint4*>(qr + row * 128 + c);
        const int t = t0 + row;
        uint4 v = make_uint4(0, 0, 0, 0);
        if (t < n_older) v = *reinterpret_cast<const uint4*>(idx_k + (int64_t)t * 128 + c);
        *reinterpret_cast<uint4*>(ks + row * TF_IDX_LD + c) = v;
    }
    __syncthreads();

    float acc[8][4];
#pragma unroll
    for (int j = 0; j < 8; ++j)
#pragma unroll
        for (int i = 0; i < 4; ++i) acc[j][i] = 0.0f;
#pragma unroll
    for (int kk = 0; kk < 128; kk += 16) {
        uint32_t a[4];
        const __nv_bfloat16* ap = qs + (warp * 16 + g) * TF_IDX_LD + kk + tq * 2;
        a[0] = *reinterpret_cast<const uint32_t*>(ap);
        a[1] = *reinterpret_cast<const uint32_t*>(ap + 8 * TF_IDX_LD);
        a[2] = *reinterpret_cast<const uint32_t*>(ap + 8);
        a[3] = *reinterpret_cast<const uint32_t*>(ap + 8 * TF_IDX_LD + 8);
#pragma unroll
        for (int j = 0; j < 8; ++j) {
            uint32_t b[2];
            const __nv_bfloat16* bp = ks + (j * 8 + g) * TF_IDX_LD + kk + tq * 2;
            b[0] = *reinterpret_cast<const uint32_t*>(bp);
            b[1] = *reinterpret_cast<const uint32_t*>(bp + 8);
            idx_mma16816(acc[j], a, b);
        }
    }
    // c0, c1: head warp*16 + g, tokens j*8 + tq*2 + {0,1}; c2, c3: head + 8
    const float w_lo = __bfloat162float(weights[(int64_t)r * 64 + warp * 16 + g]) * weights_scale;
    const float w_hi = __bfloat162float(weights[(int64_t)r * 64 + warp * 16 + g + 8]) * weights_scale;
#pragma unroll
    for (int j = 0; j < 8; ++j) {
#pragma unroll
        for (int e = 0; e < 2; ++e) {
            float v = w_lo * fmaxf(acc[j][e], 0.0f) + w_hi * fmaxf(acc[j][e + 2], 0.0f);
            v += __shfl_xor_sync(0xffffffffu, v, 4);  // the 8 lanes (g) sharing tq: the warp's 16 heads
            v += __shfl_xor_sync(0xffffffffu, v, 8);
            v += __shfl_xor_sync(0xffffffffu, v, 16);
            if (g == 0) red[warp * 64 + j * 8 + tq * 2 + e] = v;
        }
    }
    __syncthreads();
    for (int i = threadIdx.x; i < 64; i += blockDim.x) {
        const int t = t0 + i;
        if (t >= max_older) continue;
        const float total = red[i] + red[64 + i] + red[128 + i] + red[192 + i];
        scores[(int64_t)r * max_older + t] = t < n_older ? total : -1e38f;
    }
}
