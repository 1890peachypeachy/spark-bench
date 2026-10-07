# jspark3 v2.0.1 -> v2.0.2 cutover window runbook

Staged 2026-10-06. Run ONLY when the Hermes default profile has finished its work
(the lane serves live agent traffic on http://100.99.120.29:8888/v1).

Ranks: spark3=rank0/head, spark1=rank1, spark4=rank2.
Staged kit: /var/tmp/jspark3/jspark3-v202   Staged DATA: /var/tmp/jspark3/data-v202
Live kit:   /var/tmp/jspark3/jspark3        Live DATA:   /var/tmp/jspark3/data

## Why these steps are NOT pre-staged

INSTALL.md step 3/5: building the wheel and verifying the split "churn through
memory, and on a box that is serving, the kernel's background memory compaction
can then stall the server." spark4 idles at ~2.3 GiB MemFree. So build AFTER stop.

## Step 1 — stop the whole v2.0.1 ring (mixed-version rings are unsupported)

Containers are retained for rollback; v2.0.2 scripts never touch a container they
did not start.

    for n in spark4 spark1 spark3; do
      ssh $n 'cd /var/tmp/jspark3/jspark3 && scripts/stop.sh'
    done
    for n in spark3 spark1 spark4; do ssh $n 'docker ps --format "{{.Names}}"'; done   # no jspark3-rank*
    for n in spark3 spark1 spark4; do ssh $n 'nvidia-smi --query-compute-apps=pid,used_memory --format=csv'; done

## Step 2 — build the engine wheel on each node (was deferred)

    for n in spark3 spark1 spark4; do
      ssh $n 'cd /var/tmp/jspark3/jspark3-v202 && scripts/fetch-wheels.sh --verify-only && scripts/build-wheel.sh'
    done

Must print a content digest matching pins.env WHEEL_CONTENT_SHA256:
  35b0ccd7ee67e4f0a1b22db95566c8924425045552a8e08b3ca49454d3571e60
A different digest = STOP, do not serve.

## Step 3 — verify the symlinked weights under the new DATA

    for n in spark3 spark1 spark4; do
      ssh $n 'cd /var/tmp/jspark3/jspark3-v202 && scripts/split.sh --verify-only'
    done

(wheels.lock and manifests/{inputs,base} are byte-identical v2.0.1..v2.0.2, so the
v2.0.1 weights are valid for this release; rank dirs are symlinked, not copied.)

## Step 4 — preflight

    for n in spark3 spark1 spark4; do
      ssh $n 'cd /var/tmp/jspark3/jspark3-v202 && python3 scripts/preflight.py'
    done

Expected-benign FAIL: "PREV_IFACE is up" — enp1s0f0np0 is NO-CARRIER on all three
nodes because our fabric is the switched CRS504 on enp1s0f1np1 only, not the
recipe's direct-cable ring. The live v2.0.1 ring serves on this same config.
Any OTHER FAIL must be resolved before starting.

## Step 5 — start ranks 2, 1, then 0

    ssh spark4 'cd /var/tmp/jspark3/jspark3-v202 && scripts/serve.sh'
    ssh spark1 'cd /var/tmp/jspark3/jspark3-v202 && scripts/serve.sh'
    ssh spark3 'cd /var/tmp/jspark3/jspark3-v202 && scripts/serve.sh'
    ssh spark3 'cd /var/tmp/jspark3/jspark3-v202 && scripts/wait-ready.sh'

## Step 6 — verify

    ssh spark3 'cd /var/tmp/jspark3/jspark3-v202 && scripts/smoke.sh'
    curl -s http://100.99.120.29:8888/v1/models    # id must be GLM-5.3-Flash-EXL3

smoke's `models` check FAILS BY DESIGN: we pin SERVE_NAME=GLM-5.3-Flash-EXL3 for
fleet identity while smoke expects the stock `glm53`. Expect 5/6, as at the
v2.0.1 cutover. Then the v2.0.2-specific checks:
  - a GIF request is answered (was a 400 before this release)
  - rolling-image resume: 8/9/10-image requests should resume nonzero tokens
    (upstream measured 0 -> 68 -> 174); first request is cold by design, the
    session namespace changed with the wheel digest.
  - scripts/cache-check.py and scripts/prefill-check.py as at the last cutover.

## Step 7 — spark-lane registry

The lane id `jspark3` in ~/recipe-db/spark-bench/ops/spark-lane points at the
v2.0.1 kit path. Update the kit path after a successful cutover, re-run
`spark-lane verify jspark3`, and commit to the fork.

## Rollback

    for n in spark4 spark1 spark3; do ssh $n 'cd /var/tmp/jspark3/jspark3-v202 && scripts/stop.sh'; done
    ssh spark4 'cd /var/tmp/jspark3/jspark3 && scripts/serve.sh'
    ssh spark1 'cd /var/tmp/jspark3/jspark3 && scripts/serve.sh'
    ssh spark3 'cd /var/tmp/jspark3/jspark3 && scripts/serve.sh && scripts/wait-ready.sh && scripts/smoke.sh'

Delete neither release's sessions as part of this upgrade. Upstream's own first
live v2.0.2 swap failed its image check and was rolled back; the corrected
acceptance passed 2026-10-05 18:37Z. Upstream states no clean install of the
final v2.0.2 recipe has been demonstrated.
