# GLM-5.3-Flash-EXL3 TP3 — adapted launcher

`start-tp3.sh` here is our adapted copy of Mia's TP3 launcher
(`MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks`), deployed to
`spark3:/home/spark3/GLM53-TP3/start-tp3.sh` and invoked by
`spark-bench/ops/spark-lane` as lane `glm53-tp3` (`GLM53_CLI="./start-tp3.sh"`).

## Base commit

Adapted from upstream `cbaaeea` (2026-09-17, *"fix(tp3): keep ABLIT off and do not
inherit TP2 FAST/FAT"*), which is what was deployed on spark3. An audit on
2026-09-27 blob-matched the deployed file byte-for-byte against `cbaaeea`:
**there were no local customizations in this launcher.** Its ~127-line drift from
repo HEAD is purely "deployed is 6 days older", not local work.

## Our change: DEFAULT_MAX_NEW_TOKENS (2026-09-27)

Ported from Mia's two-node `start.sh`, which scopes the feature deliberately —
the source carries `# Two-node start.sh only; start-tp4.sh is unchanged`. The TP3
path never had it upstream, and still does not at HEAD.

**It is not a cap.** An explicit client `max_tokens` always wins. It only supplies
a fallback when the client *omits* the field, which is the case that let a stuck
agent turn generate unbounded output and monopolise the whole lane.

Default `65536`, via unset-only expansion (`${DEFAULT_MAX_NEW_TOKENS-65536}`), so
exporting an explicit empty value preserves stock server limits.
`overlay/patch_default_max_new_tokens.py` reads the env var at *runtime* and
no-ops when empty, so the mount and the apply call are unconditional.

Eight insertions were required:

| # | Where | What |
|---|---|---|
| 1 | after `FLASHKDA_PATCH_HOST` | `DEFAULT_TOKENS_PATCH_HOST` + `DEFAULT_MAX_NEW_TOKENS` |
| 2 | `_tp3_scp_runtime()` | scp the patch to each worker's `/tmp` |
| 3 | worker `docker run` | mount `/tmp/patch_default_max_new_tokens.py` |
| 4 | head `docker run` | mount `$DEFAULT_TOKENS_PATCH_HOST` |
| 5 | head `docker run` | `-e DEFAULT_MAX_NEW_TOKENS` |
| 6 | worker `docker run` | `-e DEFAULT_MAX_NEW_TOKENS` |
| 7,8 | **both** generated start scripts | `python3 /opt/glm53/patch_default_max_new_tokens.py` |

### Two traps in this launcher (cost real time — read before editing)

1. **Lines 1847–1875 are dead code.** They sit inside `: <<'TP3_SKIP_OLD_SCP'`,
   a disabled heredoc. The `${WORKER_SSH}` scp fan-out in that block never runs.
   The live fan-out is `_tp3_scp_runtime()` (~line 1732) using `${ssh_t}`.
   Inserting into the obvious-looking block would silently never reach workers.
2. **The in-container apply sequence appears TWICE** (head script and worker
   script). A single insertion leaves the workers unpatched. Anchor on
   `patch_kpool_tail_slotmap.py` and expect exactly 2 matches.

Unlike the two-node `start.sh`, TP3 open-codes every `if [ -f ... ]` apply block
instead of generating them from an ordered array (`GLM53_OVERLAY_ORDER`), which is
why a one-line feature needs edits in four separate places.

## Verification status

`bash -n` clean locally and on spark3; checksums match. **Not runtime-verified** —
TP3 was down (TP4 holds all four nodes) and could not be launched without
displacing it. Previous launcher saved as `start-tp3.sh.bak-20260927-preCap`.

## Upstream items worth adopting (audit 2026-09-27, none applied)

Deliberately NOT taken, to keep this a minimal delta on a known-good base:

- `b5178ac` — `USER="${USER:-$(id -un)}"`; two-line robustness fix for cron/systemd
  invocations that lack `USER`. Safe.
- `9bc0ab9` — `pull_image_keeping_repo_stamp()`; stops a GHCR pull of the floating
  `:exl3-instanttensor` tag silently replacing a stamp-matched local image.
  Highest operational value. Note it also skips worker pulls on stamp mismatch, so
  inventory `docker images` stamps on spark1/2/3 before the first restart under it.
- `GLM53_KV_CAPACITY_LOG` (+ `patch_kv_capacity_log.py`) — log-only honest KV
  capacity accounting, default-on for TP2, never ported to TP3. Zero runtime risk
  and most valuable on a `MAX_MODEL_LEN=1000000` lane.
- `patch_tool_choice_none.py` — makes `tool_choice:"none"` actually suppress
  `<tool_call>` output; needs `--reasoning-parser glm45`. Relevant to agent use.
- `GLM53_DEFAULT_REASONING_EFFORT`, `GLM53_APC_NO_STORE`, `GLM53_EXTRA_ENV`.

### Do not adopt blind

- **Mamba align patches** (`fd329d2`) are applied **unconditionally, no env gate**,
  and change prefill chunk boundaries plus block-release timing on first restart.
  The chunking patch requires decode-floor **v5** — verify the deployed
  `patch_scheduler_decode_floor.py` version first. This is the only HEAD change
  that alters scheduler/memory behaviour with no opt-out.
- **`GLM53_KDA_BF16_LARGE_M`** — port the knob, leave it `0`. Repo figures for its
  memory cost disagree by ~30x (~3.26 GiB/rank in CHANGELOG vs +68.2 MiB/rank
  measured). On 128 GB UMA at 1M context that is NVRM-OOM territory.
- **`GLM53_DRAFT_KV_COMPACT`** — port the knob, leave it `0`; TP3 evidence upstream
  is "geometry confirmation" only.
- `patch_sparse_mla_slice.py` is TP4-only. `GLM53_EXL3_MOE_FAST` is explicitly
  unset on TP3 (`:168`) and inert by design.

### Open question before any resync to HEAD

`overlay/exl3.py` is locally modified on spark3 **and was not diffed**. TP3
bind-mounts it (`start-tp3.sh:2184`), so it is the one place real local work could
be hiding. Diff it before resyncing. Same for spark3's modified `Dockerfile`,
`ablit_runtime.py`, `start.sh`, `start-tp4.sh`, `tests/*`.

Config that must survive any resync: `/home/spark3/GLM53-TP3/.env.tp3` sets
`MAX_MODEL_LEN=1000000` and `SPEC_METHOD=dflash`.
