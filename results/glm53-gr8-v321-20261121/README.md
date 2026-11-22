# glm53-gr8 v3.2.1 (recipe f94ccfd, gr8 v1.1.1 a3f44a0 + attic client) — cutover 2026-11-21

Before: v3 af95a2e, gr8:ca7e874-attic, SESS 6, CAP 776,704. After: recipe f94ccfd, gr8:a3f44a0-attic (id 5ea8f8507c98 on all 4),
SESS 8, CAP 1,048,576, max_model_len 1,048,562. Same weights (release v0.7 9e25c28a), same bit280 manifest (sha 748cdc59), same DFlash2 drafter.
Busy guard kept at BUSY_IDLE_SECS=120 BUSY_RETRY_AFTER=20 (our .env lines). Rollback: GR8_IMAGE=gr8:ca7e874-attic in .env on all 4 + spark-lane down/up
(old image still on every node; .env backups .env.bak-pre-v321-20261121).

## How the image was made (attic client is in NO published gr8 image)
Attic client = bertholomus/gr8 branch attic-client commit 382a62d6 ("GR8_ATTIC_SOCK"), cherry-picked onto kindlingai/gr8 a3f44a0.
Conflicts only in generated knob tables -> take upstream, regenerate with `cargo run ... knobs -- gen` in a rust:1-slim container
(no cargo on Mac or Sparks). Do NOT take 64b00d6f: it moves to the native dispram client and removes the GR8_ATTIC_* knobs the recipe's overlay uses.
Built on spark3 with the lane down (~11.5 min), copied to spark1/2/4 over RoCE 10.73.0.x (13 s). Patches + build script in models/glm-5.3/gr8-tp4/attic/.

## Our measurements (own harness, one boot, idle lane; NOT RigMark — do not set beside upstream rows)
conc.py: 600 max tok, mixed prompts, usage tokens incl. reasoning, effort low.
| streams | v3 (SESS 6) agg / per-stream | v3.2.1 (SESS 8) agg / per-stream |
|---|---|---|
| 1 | 39.8 | 43.9 (3 re-runs of the same prose prompt: 42.2 / 44.1 / 43.6) |
| 4 | 85.0 / 21.9 | 98.1 / 25.3 |
| 6 | 92.1 / 16.6 | 121.2 / 22.2 |
| 8 | n/a | 142.5 / 19.7 |
c1_decode_screen.py medians: prose 29.7 (single sample, not reproduced: re-runs ~43) / code 46.3 / structured 76.8 (v3: 40.7 / 48.6 / 74.2).
Lowest MemAvailable sampled during the 8-stream run: 11.6 / 11.9 / 11.9 / 11.7 GiB (spark1..4). Upstream's "free under load" metric may differ.
Upstream claims (v3.2.1 post, RigMark, their boot): 8 chats 173 tok/s total, ~23 each; 1-chat structured 80; 9 GiB free. Not reproduced on our harness
(ours 142.5 / 19.7). Gap may be harness (prompts, reasoning tokens counted) or rig; unresolved. Need RigMark 770c310 for like-for-like.

## Checks
spark-lane verify PASS; recipe smoke 14/14 (context_limit_refused at 1,048,562); show-config: SESS 8, CAP 1048576, sha 748cdc59, GR8_ATTIC_SOCK/KEY_FILE + busy 120/20 in engine env;
attic G.embed lease (1815 MiB of the display carveout) logged on all four ranks.
Lesson: `spark-lane up` canary 503 'engine not connected' appears ~10 s after start; poll real completions, do not restart (engine ready ~40 s).
Lesson: before any "we are on latest" claim, `git fetch` and diff the recipe, and treat a second post from the author as a supersede signal.
