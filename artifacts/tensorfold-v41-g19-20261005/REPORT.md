# G19 on four Sparks (2026-10-05 → 2026-10-07)

**Status: serving since 2026-10-07 00:06** (image `tp4g19b`), after the candidate window below passed every check.
First measurements (2026-10-05) first, then the candidate window and the TP=2 check for Jay's PR (2026-10-06/07).

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

## Candidate window (2026-10-06 23:48 → 2026-10-07 00:06)

The live G13 build and `+ fused + rdma` with native images, `CONTEXT=420000` and `TF_DSV41_POOL_TOKENS=1201152`,
back to back in one window, 1k / 20k / 160k prose and code, two trials (cold, repeat).

| | G13 build (live until then) | **G19 candidate** |
| --- | ---: | ---: |
| decode, prose 1k / 20k / 160k cold (tok/s) | 53.1 / 50.1 / 47.5 | 54.5 / 50.3 / 48.6 |
| decode, code 1k / 20k / 160k cold (tok/s) | 88.9 / 80.8 / 84.9 | 90.7 / 82.3 / 86.2 |
| mean decode over the 12 cells (tok/s) | 69.1 | 70.3 |
| cold first token 20k / 160k (mean of prose and code) | 6.3 s / 39.0 s | 5.7 s / 36.1 s |

| check | result |
| --- | --- |
| code word at 30 / 60 / 85% of 20k / 80k / 158k-token prompts | 3 / 3 |
| code word at 50% of a 404,655-token prompt (67.5 s) | 1 / 1 |
| short gates | 7 / 7 |
| nucleus, nucleus + min_p, `top_k` 40,000 and 32,000, `top_k` 20, JSON nucleus | 6 / 6 |
| image question (a 64×64 PNG, red and blue halves) | "Red and blue" |
| `/v1/model_info` | `max_model_len` 420000, `max_num_seqs` 4 |
| greedy reply vs the G13 build | byte-identical |

Every check passed and nothing was slower, so the window promoted the candidate (`tp4.env`; the old file is
`pf/tp4.env.before-g19`). The first try (2026-10-05) failed at start: one node's cache volume lacked the image
routing bias (its download had failed); copied from another node, checksum checked.

## TP=2: Jay's main vs main + the PR #6 patch (2026-10-06)

Jay's merge conditions for PR #6 include TP=2 evidence on G19. Two of our Sparks (forge, anvil), his
`scripts/serve.sh` and `config/prod.env.example` (placeholders filled), images built with his Dockerfile from fresh
clones: main `4b235ad` and the fork's `four-sparks` branch `27502c1` (main + `0003`, four ranks and the review's
fixes only). Each: prebuild, start (preflight + canary), canary, nine greedy requests, a streamed decode rate.

- canary (chat, thinking, tool, json, tokenize): passes on both
- greedy replies, 9 / 9 identical (essay, code, math, list, thinking with reasoning, forced tool call, JSON
  schema, 20k-token prose and code prompts), the same token counts; only a tool call's random `call_` id differs
- decode, a code prompt streamed three times: main 76.9 / 78.1 / 78.2, main + 0003 77.4 / 77.6 / 77.7 tok/s
