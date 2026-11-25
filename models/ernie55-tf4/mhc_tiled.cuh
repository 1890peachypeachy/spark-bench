// mHC pre-mix for prompt rows (Spark, 2026-11-24; appended to ops.cu). Same outputs as tf_ernie55_mhc_pre_gemv:
//   mix_raw[r, j] = sum_i res[r, i] * fn[j, i] (j < 24), sqrsum[r] = sum_i res[r, i]^2, over hc_dim = 4 * hidden.
// tf_ernie55_mhc_pre_gemv runs a block a (j, r) and reads row r 24 times and fn once a row; this one tiles 8 rows a
// block over K chunks of 256 in shared memory: each of the 8 x 24 outputs (and 8 squares) is one thread's fp32 sum.
// Launch: grid=(ceil(rows/8)), block=(256), smem static.
#define TF_MHC_ROWS 8
#define TF_MHC_KC 256
extern "C" __global__ void __launch_bounds__(256) tf_ernie55_mhc_pre_tiled(
    const __nv_bfloat16* __restrict__ res, const float* __restrict__ fn, float* __restrict__ mix_raw,
    float* __restrict__ sqrsum_out, int rows, int hc_dim) {
    __shared__ float xs[TF_MHC_ROWS][TF_MHC_KC + 1];
    __shared__ float fs[24][TF_MHC_KC + 1];
    const int r0 = blockIdx.x * TF_MHC_ROWS;
    const int t = threadIdx.x;
    // outputs: t < 192 -> (row t / 24, j t % 24); 192 <= t < 200 -> square of row t - 192
    const int orow = t < 192 ? t / 24 : t - 192;
    const int oj = t % 24;
    float acc = 0.0f;
    for (int k0 = 0; k0 < hc_dim; k0 += TF_MHC_KC) {
        __syncthreads();
        for (int i = t; i < TF_MHC_ROWS * TF_MHC_KC; i += blockDim.x) {
            const int rr = i / TF_MHC_KC, c = i % TF_MHC_KC, r = r0 + rr;
            xs[rr][c] = r < rows ? __bfloat162float(res[(int64_t)r * hc_dim + k0 + c]) : 0.0f;
        }
        for (int i = t; i < 24 * TF_MHC_KC; i += blockDim.x) {
            const int jj = i / TF_MHC_KC, c = i % TF_MHC_KC;
            fs[jj][c] = fn[(int64_t)jj * hc_dim + k0 + c];
        }
        __syncthreads();
        if (t < 192) {
#pragma unroll 8
            for (int c = 0; c < TF_MHC_KC; ++c) acc = fmaf(xs[orow][c], fs[oj][c], acc);
        } else if (t < 200) {
#pragma unroll 8
            for (int c = 0; c < TF_MHC_KC; ++c) acc = fmaf(xs[orow][c], xs[orow][c], acc);
        }
    }
    const int r = r0 + orow;
    if (r < rows) {
        if (t < 192) mix_raw[(int64_t)r * 24 + oj] = acc;
        else if (t < 200) sqrsum_out[r] = acc;
    }
}
