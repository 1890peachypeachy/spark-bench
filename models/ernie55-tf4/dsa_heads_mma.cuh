// Per-head projections of the MLA-DSA layers on tensor cores (Spark, 2026-11-24; appended to dsa_attn.cu).
// C[r, h, n] = sum_k A[r, h, k] * B_h(k, n) for every local head h:
//   absorb_q: A = q [rows, H, 256] (first 192 dims), B_h = wk[h] stored [k = 192][n = 512] (BKN = 1),
//             C = q_abs [rows, H, 576] (first 512); the rope tail is copied by tf_ernie55_dsa_rope_copy.
//   expand_v: A = o_lat [rows, H, 512], B_h = wv[h] stored [n = 256][k = 512] (BKN = 0), C = o_v [rows, H, 256].
// One block: one head, 64 rows x 64 columns, K in steps of 64; four warps of 16 rows; mma.sync m16n8k16, fp32 sums.
#define TF_HG_LD 72

__device__ __forceinline__ void hg_mma16816(float* c, const uint32_t* a, const uint32_t* b) {
    asm volatile(
        "mma.sync.aligned.m16n8k16.row.col.f32.bf16.bf16.f32 {%0,%1,%2,%3}, {%4,%5,%6,%7}, {%8,%9}, {%0,%1,%2,%3};\n"
        : "+f"(c[0]), "+f"(c[1]), "+f"(c[2]), "+f"(c[3])
        : "r"(a[0]), "r"(a[1]), "r"(a[2]), "r"(a[3]), "r"(b[0]), "r"(b[1]));
}

template <int BKN>
__device__ __forceinline__ void head_gemm_body(const __nv_bfloat16* __restrict__ A, int lda, int a_head,
                                               const __nv_bfloat16* __restrict__ B, int b_head, int ldb,
                                               __nv_bfloat16* __restrict__ C, int ldc, int c_head, int rows, int N, int K) {
    const int n0 = blockIdx.x * 64, h = blockIdx.y, r0 = blockIdx.z * 64;
    __shared__ __align__(16) __nv_bfloat16 as[64 * TF_HG_LD];
    __shared__ __align__(16) __nv_bfloat16 bs[64 * TF_HG_LD];  // [n][k]
    const int warp = threadIdx.x >> 5, lane = threadIdx.x & 31, g = lane >> 2, tq = lane & 3;
    float acc[8][4];
#pragma unroll
    for (int j = 0; j < 8; ++j)
#pragma unroll
        for (int i = 0; i < 4; ++i) acc[j][i] = 0.0f;
    const __nv_bfloat16* Bh = B + (int64_t)h * b_head;
    for (int k0 = 0; k0 < K; k0 += 64) {
        __syncthreads();
        for (int i = threadIdx.x; i < 64 * 8; i += blockDim.x) {  // A: 64 rows x 64 k, 8 bf16 a step
            const int rr = i >> 3, c = (i & 7) * 8, r = r0 + rr;
            uint4 v = make_uint4(0, 0, 0, 0);
            if (r < rows) v = *reinterpret_cast<const uint4*>(A + (int64_t)r * lda + (int64_t)h * a_head + k0 + c);
            *reinterpret_cast<uint4*>(as + rr * TF_HG_LD + c) = v;
        }
        if (BKN == 0) {  // B stored [n][k]: rows of k, straight in
            for (int i = threadIdx.x; i < 64 * 8; i += blockDim.x) {
                const int nn = i >> 3, c = (i & 7) * 8, n = n0 + nn;
                uint4 v = make_uint4(0, 0, 0, 0);
                if (n < N) v = *reinterpret_cast<const uint4*>(Bh + (int64_t)n * ldb + k0 + c);
                *reinterpret_cast<uint4*>(bs + nn * TF_HG_LD + c) = v;
            }
        } else {  // B stored [k][n]: coalesced along n, transposed into bs[n][k]
            for (int i = threadIdx.x; i < 64 * 64; i += blockDim.x) {
                const int kk = i >> 6, nn = i & 63, n = n0 + nn;
                bs[nn * TF_HG_LD + kk] = n < N ? Bh[(int64_t)(k0 + kk) * ldb + n] : __float2bfloat16(0.0f);
            }
        }
        __syncthreads();
#pragma unroll
        for (int kk = 0; kk < 64; kk += 16) {
            uint32_t a[4];
            const __nv_bfloat16* ap = as + (warp * 16 + g) * TF_HG_LD + kk + tq * 2;
            a[0] = *reinterpret_cast<const uint32_t*>(ap);
            a[1] = *reinterpret_cast<const uint32_t*>(ap + 8 * TF_HG_LD);
            a[2] = *reinterpret_cast<const uint32_t*>(ap + 8);
            a[3] = *reinterpret_cast<const uint32_t*>(ap + 8 * TF_HG_LD + 8);
#pragma unroll
            for (int j = 0; j < 8; ++j) {
                uint32_t b[2];
                const __nv_bfloat16* bp = bs + (j * 8 + g) * TF_HG_LD + kk + tq * 2;
                b[0] = *reinterpret_cast<const uint32_t*>(bp);
                b[1] = *reinterpret_cast<const uint32_t*>(bp + 8);
                hg_mma16816(acc[j], a, b);
            }
        }
    }
#pragma unroll
    for (int j = 0; j < 8; ++j)
#pragma unroll
        for (int i = 0; i < 4; ++i) {
            const int r = r0 + warp * 16 + g + (i >= 2 ? 8 : 0);
            const int n = n0 + j * 8 + tq * 2 + (i & 1);
            if (r < rows && n < N) C[(int64_t)r * ldc + (int64_t)h * c_head + n] = __float2bfloat16_rn(acc[j][i]);
        }
}

// Launch: grid=(ceil(512/64), H_loc, ceil(rows/64)), block=(128).
extern "C" __global__ void __launch_bounds__(128) tf_ernie55_dsa_absorb_q_mma(
    const __nv_bfloat16* __restrict__ q, const __nv_bfloat16* __restrict__ wk, __nv_bfloat16* __restrict__ q_abs, int rows, int H_loc) {
    head_gemm_body<1>(q, H_loc * 256, 256, wk, 192 * 512, 512, q_abs, H_loc * 576, 576, rows, 512, 192);
}

// q_abs[r, h, 512 .. 576) = q[r, h, 192 .. 256) (the rope dims pass through). Launch: grid=(rows), block=(H_loc * 64).
extern "C" __global__ void tf_ernie55_dsa_rope_copy(const __nv_bfloat16* __restrict__ q, __nv_bfloat16* __restrict__ q_abs, int rows, int H_loc) {
    const int r = blockIdx.x, h = threadIdx.x >> 6, l = threadIdx.x & 63;
    if (r >= rows || h >= H_loc) return;
    q_abs[((int64_t)r * H_loc + h) * 576 + 512 + l] = q[((int64_t)r * H_loc + h) * 256 + 192 + l];
}

// Launch: grid=(ceil(256/64), H_loc, ceil(rows/64)), block=(128).
extern "C" __global__ void __launch_bounds__(128) tf_ernie55_dsa_expand_v_mma(
    const __nv_bfloat16* __restrict__ o_lat, const __nv_bfloat16* __restrict__ wv, __nv_bfloat16* __restrict__ o_v, int rows, int H_loc) {
    head_gemm_body<0>(o_lat, H_loc * 512, 512, wv, 256 * 512, 512, o_v, H_loc * 256, 256, rows, 256, 512);
}
