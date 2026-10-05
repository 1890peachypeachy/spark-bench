# G19 on four Sparks — first measurements (2026-10-05)

**Status: under test, not serving.** The live server stays on the fork's `main` (engine G13 + patches 0003–0006)
until the candidate passes every check (below).

## What was tested

jayleaton's newer engine (G14–G19: RDMA plan link, fail-fast, split prefill exchanges, native images) with our
four-Spark port on top: the fork's [`g19` branch](https://github.com/neko-legends/deepseek-v41-tensorfold-spark/tree/g19)
(patches 0001/0002 = Jay's G19, `0003-four-sparks.patch` = our port). Port fixes needed on the way: the plan
link's RDMA mailbox and fail-fast channels at four ranks, the memory floor reading the tightest follower, image
segments kept out of the prompt pipeline, and the BMQ clamp on G16's grouped prefill attention (its absence
crashed every start with the G19 speed switches on).

Configurations, one boot each, isolated (nothing else on the Sparks), 512-token completions, prose and code
fixtures at 1k / 20k / 160k, two trials (cold, then repeat):

| label | build | switches |
| --- | --- | --- |
| live | `main` (G13 + 0003–0006) | the three prompt-reading switches |
| G19 | `g19` | the same, nothing new |
| G19 + speed | `g19` | + `GLM53_TF_ROCE_FAST`, `TF_DSV41_BRANCHES`, `MHC_PF`, `PF_COPIES`, `PLAN_PIN=auto`, `PREFILL_ADAPT_GIB=4.5` and related |
| + fused | `g19` | + `TF_DSV41_PF_DENSE=fused` |
| + rdma | `g19` | G19 + speed + `TF_DSV41_PLAN_LINK=rdma` |

## Results

| | live | G19 | G19 + speed | + fused | + rdma |
| --- | ---: | ---: | ---: | ---: | ---: |
| cold first token, 160k (s) | 39.0–39.3 | 38.8–39.6 | 36.7–36.9 | **36.0–36.1** | 36.7–36.9 |
| cold first token, 20k (s) | 5.9–6.7 | 5.8–12.4¹ | 5.4–9.6¹ | **5.3–6.0** | 5.4–6.3 |
| decode, prose 1k / 160k cold (tok/s) | 53.2 / 47.3 | 53.0 / 47.6 | 53.6 / 48.7 | 53.5 / 49.3 | **54.4 / 48.8** |
| decode, code 1k / 160k cold (tok/s) | 88.1 / 85.8 | 87.2 / 84.4 | 89.5 / 84.8 | 89.6 / 85.0 | **89.5 / 86.4** |

¹ The first requests after the first start of a new image compile kernels (once: up to 37 s on a 1k prompt);
the compiled kernels are cached and later starts did not pay it.

Read with care:
- **Prompt reading: ~7% faster at 160k** with the speed switches and the fused dense prefill.
- **Decode: +1–3% on prose, code unchanged** — within the run-to-run spread we measured on 2026-10-05.
  The RDMA plan link, worth 23.4 → 21.8 ms a token at two Sparks, is not what limits four.
- One boot per configuration, and the `live` column was measured ~40 minutes before the others.

## Next

A candidate window: the live build and `+ fused + rdma` with native images and a 420k context (1.2M-token KV
pool) back to back; long-prompt needles at 20k / 80k / 158k and ~405k, the seven short gates, the six wide
sampling cases, an image question. It goes live only if every check passes and it is not slower.
