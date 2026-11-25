// Expert-major MXFP4 MoE kernels for ERNIE 5.5 prefill (appended to mxfp4_situ.cu).
//
// The decode kernels above run one (row, expert) pick a block, so a 256-row chunk reads every expert's weights once
// per pick that chose it. These sort the picks by expert and give each warp one output column of one expert: the
// warp holds that column's weights in registers and loops over every pick routed to the expert. Each lane's FMA
// order, the warp sum and the top-k combine order match tf_ernie55_mxfp4_w13_situ / _w2_combine exactly, so the
// outputs are bit-identical to theirs.

// counts[e] += picks of expert e (counts zeroed by the caller).
extern "C" __global__ void tf_ernie55_route_count(const int32_t* __restrict__ ids, int pairs, int32_t* __restrict__ counts) {
    int p = blockIdx.x * blockDim.x + threadIdx.x;
    if (p < pairs) atomicAdd(&counts[ids[p]], 1);
}

// offsets[e] = picks below expert e; cursor[e] = offsets[e]. One block of `E` (<= 1024) threads.
extern "C" __global__ void tf_ernie55_route_scan(const int32_t* __restrict__ counts, int32_t* __restrict__ offsets,
                                                 int32_t* __restrict__ cursor, int E) {
    __shared__ int32_t s[1024];
    int t = threadIdx.x;
    s[t] = t < E ? counts[t] : 0;
    __syncthreads();
    for (int off = 1; off < 1024; off <<= 1) {
        int v = t >= off ? s[t - off] : 0;
        __syncthreads();
        s[t] += v;
        __syncthreads();
    }
    if (t < E) {
        int ex = s[t] - counts[t];
        offsets[t] = ex;
        cursor[t] = ex;
    }
    if (t == 0) offsets[E] = s[1023];
}

// list[offsets[e] ..] = the picks of expert e (in no set order: each pick's output is its own).
extern "C" __global__ void tf_ernie55_route_fill(const int32_t* __restrict__ ids, int pairs, int32_t* __restrict__ cursor,
                                                 int32_t* __restrict__ list) {
    int p = blockIdx.x * blockDim.x + threadIdx.x;
    if (p < pairs) list[atomicAdd(&cursor[ids[p]], 1)] = p;
}

#define TF_GROUPED_W13_WARPS 8
#define TF_GROUPED_W13_BATCH 8

// out[p, n] for every pick p = r * topk + tk of expert blockIdx.y, n = blockIdx.x * 8 + warp. K = 2048.
// Launch: grid=(ceil(N_loc/8), E), block=(256), smem = BATCH * K * 2.
extern "C" __global__ void __launch_bounds__(256) tf_ernie55_mxfp4_w13_grouped(
    const __nv_bfloat16* __restrict__ x, const uint8_t* __restrict__ w1_q, const uint8_t* __restrict__ w1_s,
    const uint8_t* __restrict__ w3_q, const uint8_t* __restrict__ w3_s, const int32_t* __restrict__ offsets,
    const int32_t* __restrict__ list, __nv_bfloat16* __restrict__ out, int topk, int N_loc, int K, float beta,
    float linear_beta) {
    const int e = blockIdx.y;
    const int begin = offsets[e], end = offsets[e + 1];
    if (begin == end) return;
    const int warp = threadIdx.x >> 5, lane = threadIdx.x & 31;
    const int n = blockIdx.x * TF_GROUPED_W13_WARPS + warp;
    const bool live = n < N_loc;
    const int Kg = K >> 5;  // 64 groups at K = 2048: two a lane

    uint4 v1[2], v3[2];
    float sc1[2], sc3[2];
    if (live) {
        const int64_t q_off = ((int64_t)e * N_loc + n) * (K >> 1);
        const int64_t s_off = ((int64_t)e * N_loc + n) * Kg;
        const uint4* q1 = reinterpret_cast<const uint4*>(w1_q + q_off);
        const uint4* q3 = reinterpret_cast<const uint4*>(w3_q + q_off);
#pragma unroll
        for (int j = 0; j < 2; ++j) {
            const int g = lane + 32 * j;
            v1[j] = __ldg(q1 + g);
            v3[j] = __ldg(q3 + g);
            sc1[j] = ue8m0_to_f32(__ldg(w1_s + s_off + g));
            sc3[j] = ue8m0_to_f32(__ldg(w3_s + s_off + g));
        }
    }

    extern __shared__ __nv_bfloat16 s_x[];  // [BATCH][K]
    for (int b0 = begin; b0 < end; b0 += TF_GROUPED_W13_BATCH) {
        const int nb = min(TF_GROUPED_W13_BATCH, end - b0);
        __syncthreads();
        for (int i = threadIdx.x * 8; i < nb * K; i += blockDim.x * 8) {
            const int b = i / K, c = i - b * K;
            const int r = list[b0 + b] / topk;
            *reinterpret_cast<uint4*>(s_x + b * K + c) = *reinterpret_cast<const uint4*>(x + (int64_t)r * K + c);
        }
        __syncthreads();
        if (!live) continue;
        for (int b = 0; b < nb; ++b) {
            const __nv_bfloat162* sx2 = reinterpret_cast<const __nv_bfloat162*>(s_x + b * K);
            float g_acc = 0.0f, u_acc = 0.0f;
#pragma unroll
            for (int j = 0; j < 2; ++j) {
                const __nv_bfloat162* xp = sx2 + (lane + 32 * j) * 16;
                g_acc = fmaf(dot32_e2m1(v1[j], xp), sc1[j], g_acc);
                u_acc = fmaf(dot32_e2m1(v3[j], xp), sc3[j], u_acc);
            }
            g_acc = warp_sum(g_acc);
            u_acc = warp_sum(u_acc);
            if (lane == 0) {
                const float sg = beta * tanhf(g_acc / beta) * sigmoid_rn(g_acc);
                const float su = linear_beta * tanhf(u_acc / linear_beta);
                out[(int64_t)list[b0 + b] * N_loc + n] = __float2bfloat16_rn(sg * su);
            }
        }
    }
}

#define TF_GROUPED_W2_WARPS 8
#define TF_GROUPED_W2_BATCH 16

// part[p, n] = the w2 dot of pick p (its mid row) for output n, unweighted. K_loc = 512 (one half group a lane).
// Launch: grid=(ceil(N_out/8), E), block=(256), smem = BATCH * K_loc * 2.
extern "C" __global__ void __launch_bounds__(256) tf_ernie55_mxfp4_w2_grouped(
    const __nv_bfloat16* __restrict__ mid, const uint8_t* __restrict__ w2_q, const uint8_t* __restrict__ w2_s,
    const int32_t* __restrict__ offsets, const int32_t* __restrict__ list, float* __restrict__ part, int N_out,
    int K_loc) {
    const int e = blockIdx.y;
    const int begin = offsets[e], end = offsets[e + 1];
    if (begin == end) return;
    const int warp = threadIdx.x >> 5, lane = threadIdx.x & 31;
    const int n = blockIdx.x * TF_GROUPED_W2_WARPS + warp;
    const bool live = n < N_out;
    const int K2 = K_loc >> 1, Kg = K_loc >> 5;

    uint2 v = make_uint2(0, 0);
    float sc = 0.0f;
    if (live) {  // K_loc = 512: 32 halves, lane h = lane
        const int64_t q_off = ((int64_t)e * N_out + n) * K2;
        const int64_t s_off = ((int64_t)e * N_out + n) * Kg;
        v = __ldg(reinterpret_cast<const uint2*>(w2_q + q_off) + lane);
        sc = ue8m0_to_f32(__ldg(w2_s + s_off + (lane >> 1)));
    }

    extern __shared__ __nv_bfloat16 s_mid[];  // [BATCH][K_loc]
    for (int b0 = begin; b0 < end; b0 += TF_GROUPED_W2_BATCH) {
        const int nb = min(TF_GROUPED_W2_BATCH, end - b0);
        __syncthreads();
        for (int i = threadIdx.x * 8; i < nb * K_loc; i += blockDim.x * 8) {
            const int b = i / K_loc, c = i - b * K_loc;
            *reinterpret_cast<uint4*>(s_mid + b * K_loc + c) =
                *reinterpret_cast<const uint4*>(mid + (int64_t)list[b0 + b] * K_loc + c);
        }
        __syncthreads();
        if (!live) continue;
        for (int b = 0; b < nb; ++b) {
            const __nv_bfloat162* xtk = reinterpret_cast<const __nv_bfloat162*>(s_mid + b * K_loc);
            float acc = fmaf(dot16_e2m1(v, xtk + lane * 8), sc, 0.0f);
            acc = warp_sum(acc);
            if (lane == 0) part[(int64_t)list[b0 + b] * N_out + n] = acc;
        }
    }
}

// out[r, n] = sum over tk = 0 .. topk - 1 (in order) of part[r * topk + tk, n] * weights[r * topk + tk].
// Launch: grid=(ceil(N_out/256), rows), block=(256).
extern "C" __global__ void tf_ernie55_moe_combine(const float* __restrict__ part, const float* __restrict__ weights,
                                                  __nv_bfloat16* __restrict__ out, int topk, int N_out) {
    const int r = blockIdx.y;
    const int n = blockIdx.x * blockDim.x + threadIdx.x;
    if (n >= N_out) return;
    float total = 0.0f;
    for (int tk = 0; tk < topk; ++tk) {
        const int64_t p = (int64_t)r * topk + tk;
        total = fmaf(part[p * N_out + n], weights[p], total);
    }
    out[(int64_t)r * N_out + n] = __float2bfloat16_rn(total);
}
