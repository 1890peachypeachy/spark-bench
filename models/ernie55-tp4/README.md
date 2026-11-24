# ernie55-tp4 (ERNIE-5.5-Flash-Preview, 4x DGX Spark, vLLM TP4)

Our deployment of the public recipe https://github.com/1890peachypeachy/ERNIE-5.5-Flash-Preview-4x-DGX-Sparks .
The recipe repo holds every flag (launcher, Dockerfile, patch); this folder only holds the fleet glue.

- `our-sparks.local.sh` is the recipe's `scripts/local.sh` for our nodes (rank order spark3, spark1, spark2, spark4; fabric addresses;
  fleet identity :8888 / GLM-5.3-Flash-EXL3). Copy it to `spark3:/var/tmp/ernie55/recipe/scripts/local.sh` after cloning the recipe there.
- Registered in `ops/spark-lane` as `ernie55-tp4` (EXCLUSIVE, all four nodes). `spark-lane up|down|verify|logs ernie55-tp4`; sparkDash Lane Control
  shows it with no dashboard change. `up` is a thin wrapper over the recipe's `start.sh` (the lane's own preflight, image build and /health wait);
  `down` runs the recipe's `stop.sh`.
- Detection keys on the container name `ernie55-tp4` (both stages of `node_occupant`). Verified with the lane live: census names it on all four
  nodes, a competing `up` is refused with `holder: ernie55-tp4`, and `up` on the live lane is `PASS (already up, unchanged)` in ~3 s.
- NOT exercised: `down`, and a cold `up` through the harness. Do not press them while a client depends on :8888.

## Other files in this folder (not mine, NOT committed)

`start.sh`, `env.conf` (+ `.bak`, `.bak-baseline-20261124`), `status.sh`, `stop.sh` are the launcher the operator's agent used to stand the lane up by hand.
They were untracked when this folder was registered and are left untracked here; commit them deliberately if they should be kept.
`env.conf.bak-baseline-20261124` is the pre-tuning snapshot: `MOE_BACKEND=auto`, `DSPARK_TOKENS=7`, `MAX_NUM_BATCHED_TOKENS=4096`; the
tuned `env.conf` has `b12x`, 3, 8192. (A README the agent had written in this folder was overwritten when this one was created, 2026-11-24.)
