# Hermes Profile Model/Delegation Audit — 2026-09-14

Read-only audit (finishing the 2026-09-09 pass) of all 14 profile `config.yaml` files under
`/Users/agent/.hermes/profiles/` against the live DGX Spark lanes. **No files were edited,
no gateways restarted.**

## Live lane ground truth (probed 2026-09-14 via `/v1/models`)

| Lane | base_url | Served model id | max_model_len | Status |
|---|---|---|---|---|
| Spark2 TP2 (Qwen3.8-Flash-Next, Spark1+2) | `http://100.71.248.116:8000/v1` | `qwen3.8-flash-next-spark12` | 262144 | LIVE (confirmed) |
| Spark3 TP2 (GLM-5.3-Flash-EXL3, Spark3+4) | `http://100.99.120.29:8888/v1` | `GLM-5.3-Flash-EXL3` | 850000 | LIVE (confirmed) |
| DeepSeek-V4 Flash Vision-Exp TP4 | `http://100.106.81.35:8888/v1` | `deepseek-v4-flash-vision-exp` | — | DOWN at probe (curl rc=56, connection reset) |
| crash local vLLM | `http://127.0.0.1:8001/v1` | `spark-qwen36` | — | DOWN at probe (curl rc=7, connection refused) |

DeepSeek-V4.1 TP3 lane is DEAD (stopped ~2026-09-09) and was repointed 2026-09-12 as an alias —
see `spark3-deepseek-v41` below.

## Canonical provider set (present in all 14 profiles)

| Provider key | base_url | default_model | Classification |
|---|---|---|---|
| `spark4-flashnext` | `http://100.71.248.116:8000/v1` | `qwen3.8-flash-next-spark12` | LIVE (key name says "spark4", actually the Spark1+2 TP2 lane per its own `name` field) |
| `spark3-glm53-exl3` | `http://100.99.120.29:8888/v1` | `GLM-5.3-Flash-EXL3` | LIVE |
| `spark3-deepseek-v41` | `http://100.99.120.29:8888/v1` | `GLM-5.3-Flash-EXL3` | **ALIAS** — repointed 2026-09-12 from the dead DeepSeek-V4.1 TP3 lane; functionally identical to `spark3-glm53-exl3`; duplicated in both `providers:` and `model_overrides:` in all 14 configs |

`model_overrides` in every profile carries the same two entries: the `spark3-deepseek-v41` alias block and
`spark4-flashnext → qwen3.8-flash-next-spark12 {context_window: 262144}` — 262144 matches the live lane. ✓

## Per-profile findings

| Profile | model.default | model.provider (lane status) | delegation → | Extra providers | Flags |
|---|---|---|---|---|---|
| astrid | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓, model id matches ✓) | `spark4-flashnext`/`qwen3.8-flash-next-spark12` ✓ | none (canonical 3) | alias dup; cosmetic key naming |
| crash | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | `spark-dsv4-vision` → `100.106.81.35:8888` **DOWN** at probe; `crash-vllm` → `127.0.0.1:8001` **DOWN** (refused) | 2 dead secondary lanes (not on default/delegation path); `fallback_model` → `cursor-acp` (`acp://cursor`, EXTERNAL ACP — not Spark, unverifiable here); alias dup |
| didi | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | alias dup; cosmetic key naming |
| eden | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | alias dup; cosmetic key naming |
| freud | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | `fallback_model` → `cursor-acp` (EXTERNAL ACP); alias dup |
| jarvis | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | alias dup; cosmetic key naming |
| librarian | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | alias dup; cosmetic key naming |
| momo | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | **moa** refs provider `alibaba-coding-plan` (undefined) ×4 refs + aggregator; moa `enabled: false` → dormant; alias dup |
| ollie | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | alias dup; cosmetic key naming |
| pandy | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | same as momo: moa refs undefined `alibaba-coding-plan`, moa disabled → dormant; alias dup |
| peachy | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | **moa enabled** — all refs/aggregator = `spark4-flashnext` + `spark3-glm53-exl3`, both LIVE ✓ (works); typo preset key `defauly:` (enabled: true) — cosmetic; alias dup |
| sila | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ | none | no `fallback_model` set; alias dup; cosmetic key naming |
| **spark** | `GLM-5.3-Flash-EXL3` | `spark3-deepseek-v41` (ALIAS → LIVE GLM lane ✓, model id matches ✓) | `spark4-flashnext`/`qwen3.8-flash-next-spark12` ✓ | `nous` (cloud, no base_url — EXTERNAL) | **`fallback_providers[1]` references provider `openai-codex` (gpt-5.5) which is NOT defined in this config** (only therapyconsult defines it) → failover path broken; alias dup |
| therapyconsult | `qwen3.8-flash-next-spark12` | `spark4-flashnext` (LIVE ✓) | ✓ (adds max_iterations 250, max_concurrent_children 10, depth 1 — fine) | `openai-codex` → `https://api.openai.com/v1` gpt-5.5 (EXTERNAL, defined ✓) | alias dup; cosmetic key naming |

No profile has a default or delegation target naming a model id that its lane does not serve.
Delegation blocks in all 14 profiles point at the live Spark2 TP2 lane with the exact served model id.

## Severity summary

- **Blocking: 1**
  1. `spark/config.yaml` `fallback_providers`: entry `{provider: openai-codex, model: gpt-5.5}` references a provider not defined in that config. When the GLM lane is down, failover to this entry will not resolve.
     **Recommended patch:** add the `openai-codex` provider block (as in therapyconsult: base_url `https://api.openai.com/v1`, default_model gpt-5.5, own auth) to spark's `providers:`, or drop the fallback entry.
- **Cosmetic / hygiene: 6**
  2. `spark3-deepseek-v41` ALIAS duplicated across all 14 profiles (`providers:` + `model_overrides:`), now identical to `spark3-glm53-exl3`. **Patch:** after any config still invoking `--provider spark3-deepseek-v41` is migrated, delete the alias entry from all 14 (archive configs to `backups/` first).
  3. Provider key naming misleading: `spark4-flashnext` serves the Spark1+Spark2 TP2 lane (its own `name` field says "Spark2 …"). **Patch:** rename key to `spark2-flashnext-tp2` (or similar) in one sweep with the alias cleanup — key name is user-facing in picker/history.
  4. `crash`: `spark-dsv4-vision` (100.106.81.35:8888, TP4 vision lane) DOWN at probe. Not on default/delegation path. **Patch:** leave until vision lane is re-launched per `deepseek-v4-flash-vision-exp-tp4-recipe`; note Tailscale IP may have changed — re-verify before use.
  5. `crash`: `crash-vllm` (127.0.0.1:8001, `spark-qwen36`) DOWN (refused). **Patch:** remove the provider or relaunch the local lane; it was a benchmark-only lane.
  6. `momo` + `pandy`: disabled `moa` presets reference undefined provider `alibaba-coding-plan` (4+ refs each). Dormant today, would fail on enable. **Patch:** delete the stale moa blocks or define the provider before ever enabling.
  7. `peachy`: typo'd preset key `defauly:` (enabled: true) alongside `default` (whose refs are all individually disabled). Functional today (live lanes), confusing. **Patch:** rename `defauly` → merge into `default`, delete the disabled refs.

## Verification notes
- All 14 `config.yaml` parsed with PyYAML; every `provider:` reference checked against defined provider keys.
- Live status confirmed by direct `curl /v1/models` at audit time (both primary lanes serving the exact ids above); lane state is volatile per AGENTS.md — re-verify before acting on this table.
- Other non-model URLs in configs (MCP servers: huggingface, cloudflare, openseo, canva, composio, indesign, palmier-pro, open-design daemon 127.0.0.1:7456, model-catalog) are not model lanes — out of scope, no flags.
- `hindsight`, `openrouter`, `auto`, `edge`, `groq`, `local` appear as `provider:` values in auxiliary/memory/tts/stt subsystems — built-in subsystem providers, not lane references; not flagged.
