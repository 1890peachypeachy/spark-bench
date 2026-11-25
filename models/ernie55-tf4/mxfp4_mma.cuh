// Tensor-core expert-major MXFP4 MoE kernels for ERNIE 5.5 prefill (appended to mxfp4_situ.cu after
// mxfp4_grouped.cuh, which provides route_count / route_scan / route_fill and tf_ernie55_moe_combine).
//
// One block: one expert, BN = 64 output columns, every pick routed to the expert (in passes of MT_MAX * 16 picks).
// Per K step of 64 inputs the block dequantizes its 64 x 64 MXFP4 weight tile to bf16 in shared memory (exact:
// e2m1 x 2^k is a bf16), gathers its picks' input rows, and each warp runs mma.sync m16n8k16 (bf16 in, fp32 sum)
// for its 16 columns. Sums differ from the CUDA-core kernels' order (not bit-identical), within bf16 rounding.

#define TF_MMA_BN 64
#define TF_MMA_BK 64
#define TF_MMA_LD (TF_MMA_BK + 8)  // bf16 row stride in shared memory: 144 bytes, conflict-free fragment loads
#define TF_MMA_MT 4                // 16-pick tiles held a pass

__device__ __forceinline__ void mma_bf16_16816(float* c, const uint32_t* a, const uint32_t* b) {
    asm volatile(
        "mma.sync.aligned.m16n8k16.row.col.f32.bf16.bf16.f32 {%0,%1,%2,%3}, {%4,%5,%6,%7}, {%8,%9}, {%0,%1,%2,%3};\n"
        : "+f"(c[0]), "+f"(c[1]), "+f"(c[2]), "+f"(c[3])
        : "r"(a[0]), "r"(a[1]), "r"(a[2]), "r"(a[3]), "r"(b[0]), "r"(b[1]));
}

// 32 e2m1 weights (one MXFP4 group, 16 bytes) times 2^scale into 32 bf16 at dst (16-byte aligned).
__device__ __forceinline__ void dequant32(uint4 q, float sc, __nv_bfloat16* dst) {
    const uint32_t words[4] = {q.x, q.y, q.z, q.w};
    const __nv_bfloat162 s2 = __floats2bfloat162_rn(sc, sc);
#pragma unroll
    for (int w = 0; w < 4; ++w) {
        uint4 o;
        uint32_t* op = reinterpret_cast<uint32_t*>(&o);
#pragma unroll
        for (int b = 0; b < 4; ++b) {
            __nv_bfloat162 v = __hmul2(e2m1_byte_to_bf162((words[w] >> (b * 8)) & 0xFFu), s2);
            op[b] = *reinterpret_cast<uint32_t*>(&v);
        }
        *reinterpret_cast<uint4*>(dst + w * 8) = o;
    }
}

// The block's 64-column x 64-input tile of matrix (q, s) [E][N][K/2], [E][N][K/32] at input k0, into ws[64][LD].
__device__ __forceinline__ void load_w_tile(const uint8_t* __restrict__ q, const uint8_t* __restrict__ s, int e, int n0,
                                            int N, int K, int k0, __nv_bfloat16* ws) {
    // 128 threads: thread t takes column t / 2, group (t & 1) of the two 32-input groups in the step
    const int t = threadIdx.x;
    const int c = t >> 1, g = t & 1;
    const int n = n0 + c;
    __nv_bfloat16* dst = ws + c * TF_MMA_LD + g * 32;
    if (n < N) {
        const int64_t row = (int64_t)e * N + n;
        const int kg = (k0 >> 5) + g;
        const uint4 v = __ldg(reinterpret_cast<const uint4*>(q + row * (K >> 1)) + kg);
        dequant32(v, ue8m0_to_f32(__ldg(s + row * (K >> 5) + kg)), dst);
    } else {
        const uint4 z = make_uint4(0, 0, 0, 0);
#pragma unroll
        for (int i = 0; i < 4; ++i) *reinterpret_cast<uint4*>(dst + i * 8) = z;
    }
}

// Rows of the pass's picks [p0, p0 + np) at inputs [k0, k0 + 64) into xs[np_pad][LD]; row of pick i: src_row(i).
template <typename RowOf>
__device__ __forceinline__ void load_x_tile(const __nv_bfloat16* __restrict__ x, int ldx, int np, int rows_pad, int k0,
                                            __nv_bfloat16* xs, RowOf src_row) {
    // 8 threads a row (8 bf16 = 16 bytes each)
    for (int i = threadIdx.x; i < rows_pad * 8; i += blockDim.x) {
        const int r = i >> 3, c = (i & 7) * 8;
        uint4 v = make_uint4(0, 0, 0, 0);
        if (r < np) v = *reinterpret_cast<const uint4*>(x + (int64_t)src_row(r) * ldx + k0 + c);
        *reinterpret_cast<uint4*>(xs + r * TF_MMA_LD + c) = v;
    }
}

// A fragment (rows mt*16 .., inputs kk ..) and B fragment (columns nb .., inputs kk ..) from shared memory.
__device__ __forceinline__ void frag_a(const __nv_bfloat16* xs, int mt, int kk, uint32_t* a) {
    const int lane = threadIdx.x & 31, g = lane >> 2, t = lane & 3;
    const __nv_bfloat16* p = xs + (mt * 16 + g) * TF_MMA_LD + kk + t * 2;
    a[0] = *reinterpret_cast<const uint32_t*>(p);
    a[1] = *reinterpret_cast<const uint32_t*>(p + 8 * TF_MMA_LD);
    a[2] = *reinterpret_cast<const uint32_t*>(p + 8);
    a[3] = *reinterpret_cast<const uint32_t*>(p + 8 * TF_MMA_LD + 8);
}
__device__ __forceinline__ void frag_b(const __nv_bfloat16* ws, int nb, int kk, uint32_t* b) {
    const int lane = threadIdx.x & 31, g = lane >> 2, t = lane & 3;
    const __nv_bfloat16* p = ws + (nb + g) * TF_MMA_LD + kk + t * 2;
    b[0] = *reinterpret_cast<const uint32_t*>(p);
    b[1] = *reinterpret_cast<const uint32_t*>(p + 8);
}

// w1 and w3 of expert blockIdx.y on its picks, then SITU: out[p, n] for n in the block's 64 columns. K = 2048.
// Launch: grid=(ceil(N_loc/64), E), block=(128), smem = (2 * 64 + MT * 16) * LD * 2.
extern "C" __global__ void __launch_bounds__(128) tf_ernie55_mxfp4_w13_mma(
    const __nv_bfloat16* __restrict__ x, const uint8_t* __restrict__ w1_q, const uint8_t* __restrict__ w1_s,
    const uint8_t* __restrict__ w3_q, const uint8_t* __restrict__ w3_s, const int32_t* __restrict__ offsets,
    const int32_t* __restrict__ list, __nv_bfloat16* __restrict__ out, int topk, int N_loc, int K, float beta,
    float linear_beta) {
    const int e = blockIdx.y;
    const int begin = offsets[e], end = offsets[e + 1];
    if (begin == end) return;
    extern __shared__ __align__(16) __nv_bfloat16 smem[];
    __nv_bfloat16* w1s = smem;
    __nv_bfloat16* w3s = w1s + TF_MMA_BN * TF_MMA_LD;
    __nv_bfloat16* xs = w3s + TF_MMA_BN * TF_MMA_LD;
    const int n0 = blockIdx.x * TF_MMA_BN;
    const int warp = threadIdx.x >> 5, lane = threadIdx.x & 31, g = lane >> 2, t = lane & 3;

    for (int p0 = begin; p0 < end; p0 += TF_MMA_MT * 16) {
        const int np = min(TF_MMA_MT * 16, end - p0);
        const int mts = (np + 15) >> 4;
        float acc1[TF_MMA_MT][2][4], acc3[TF_MMA_MT][2][4];
#pragma unroll
        for (int m = 0; m < TF_MMA_MT; ++m)
#pragma unroll
            for (int j = 0; j < 2; ++j)
#pragma unroll
                for (int i = 0; i < 4; ++i) acc1[m][j][i] = acc3[m][j][i] = 0.0f;

        for (int k0 = 0; k0 < K; k0 += TF_MMA_BK) {
            __syncthreads();
            load_w_tile(w1_q, w1_s, e, n0, N_loc, K, k0, w1s);
            load_w_tile(w3_q, w3_s, e, n0, N_loc, K, k0, w3s);
            load_x_tile(x, K, np, mts * 16, k0, xs, [&](int i) { return list[p0 + i] / topk; });
            __syncthreads();
#pragma unroll
            for (int kk = 0; kk < TF_MMA_BK; kk += 16) {
                uint32_t b1[2][2], b3[2][2];
#pragma unroll
                for (int j = 0; j < 2; ++j) {
                    frag_b(w1s, warp * 16 + j * 8, kk, b1[j]);
                    frag_b(w3s, warp * 16 + j * 8, kk, b3[j]);
                }
#pragma unroll
                for (int m = 0; m < TF_MMA_MT; ++m) {
                    if (m < mts) {
                        uint32_t a[4];
                        frag_a(xs, m, kk, a);
#pragma unroll
                        for (int j = 0; j < 2; ++j) {
                            mma_bf16_16816(acc1[m][j], a, b1[j]);
                            mma_bf16_16816(acc3[m][j], a, b3[j]);
                        }
                    }
                }
            }
        }
        // epilogue: c0,c1 row g, cols t*2, t*2+1; c2,c3 row g + 8
#pragma unroll
        for (int m = 0; m < TF_MMA_MT; ++m) {
            if (m >= mts) continue;
#pragma unroll
            for (int j = 0; j < 2; ++j) {
#pragma unroll
                for (int i = 0; i < 4; ++i) {
                    const int r = m * 16 + g + (i >= 2 ? 8 : 0);
                    const int n = n0 + warp * 16 + j * 8 + t * 2 + (i & 1);
                    if (r < np && n < N_loc) {
                        const float ga = acc1[m][j][i], ua = acc3[m][j][i];
                        const float sg = beta * tanhf(ga / beta) * sigmoid_rn(ga);
                        const float su = linear_beta * tanhf(ua / linear_beta);
                        out[(int64_t)list[p0 + r] * N_loc + n] = __float2bfloat16_rn(sg * su);
                    }
                }
            }
        }
    }
}

// w2 of expert blockIdx.y on its picks' mid rows: part[p, n] (unweighted fp32) for the block's 64 columns.
// Launch: grid=(ceil(N_out/64), E), block=(128), smem = (64 + MT * 16) * LD * 2.
extern "C" __global__ void __launch_bounds__(128) tf_ernie55_mxfp4_w2_mma(
    const __nv_bfloat16* __restrict__ mid, const uint8_t* __restrict__ w2_q, const uint8_t* __restrict__ w2_s,
    const int32_t* __restrict__ offsets, const int32_t* __restrict__ list, float* __restrict__ part, int N_out,
    int K_loc) {
    const int e = blockIdx.y;
    const int begin = offsets[e], end = offsets[e + 1];
    if (begin == end) return;
    extern __shared__ __align__(16) __nv_bfloat16 smem[];
    __nv_bfloat16* ws = smem;
    __nv_bfloat16* xs = ws + TF_MMA_BN * TF_MMA_LD;
    const int n0 = blockIdx.x * TF_MMA_BN;
    const int warp = threadIdx.x >> 5, lane = threadIdx.x & 31, g = lane >> 2, t = lane & 3;

    for (int p0 = begin; p0 < end; p0 += TF_MMA_MT * 16) {
        const int np = min(TF_MMA_MT * 16, end - p0);
        const int mts = (np + 15) >> 4;
        float acc[TF_MMA_MT][2][4];
#pragma unroll
        for (int m = 0; m < TF_MMA_MT; ++m)
#pragma unroll
            for (int j = 0; j < 2; ++j)
#pragma unroll
                for (int i = 0; i < 4; ++i) acc[m][j][i] = 0.0f;
        for (int k0 = 0; k0 < K_loc; k0 += TF_MMA_BK) {
            __syncthreads();
            load_w_tile(w2_q, w2_s, e, n0, N_out, K_loc, k0, ws);
            load_x_tile(mid, K_loc, np, mts * 16, k0, xs, [&](int i) { return list[p0 + i]; });
            __syncthreads();
#pragma unroll
            for (int kk = 0; kk < TF_MMA_BK; kk += 16) {
                uint32_t b[2][2];
#pragma unroll
                for (int j = 0; j < 2; ++j) frag_b(ws, warp * 16 + j * 8, kk, b[j]);
#pragma unroll
                for (int m = 0; m < TF_MMA_MT; ++m) {
                    if (m < mts) {
                        uint32_t a[4];
                        frag_a(xs, m, kk, a);
#pragma unroll
                        for (int j = 0; j < 2; ++j) mma_bf16_16816(acc[m][j], a, b[j]);
                    }
                }
            }
        }
#pragma unroll
        for (int m = 0; m < TF_MMA_MT; ++m) {
            if (m >= mts) continue;
#pragma unroll
            for (int j = 0; j < 2; ++j)
#pragma unroll
                for (int i = 0; i < 4; ++i) {
                    const int r = m * 16 + g + (i >= 2 ? 8 : 0);
                    const int n = n0 + warp * 16 + j * 8 + t * 2 + (i & 1);
                    if (r < np && n < N_out) part[(int64_t)list[p0 + r] * N_out + n] = acc[m][j][i];
                }
        }
    }
}
