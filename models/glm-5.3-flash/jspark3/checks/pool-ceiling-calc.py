#!/usr/bin/env python3
"""Rank-0 weight/staging bytes, then solve the true pool ceiling by hand.

From capacity.py:Plan.receipt the definitions are exact:
    weight_bytes_estimate  = weights.resident
    loading_bytes_estimate = weights.staging
    total_bytes_estimate   = resident + max(staging, geometry.needed(window))

The startup log printed total = 79.70 GiB. So if staging > workspace(pool),
total is pinned by the loading transient and extra pool tokens are FREE until
workspace overtakes staging. estimate_weights reads the safetensors index only
(no device query), so this works on a live lane.
"""
import json
import math
import os
from pathlib import Path

from tensorfold.cuda.capacity import SIZES, Weights, estimate_weights
from tensorfold.families.glm5_next.cuda import LATENT
from tensorfold.families.glm5_next.cuda.engine import DENSE_CAPACITY, MAX_ROWS
from tensorfold.families.glm5_next.cuda.split import (padded_config, rank_files,
                                                      rule)
from tensorfold.cuda.geometry import (Geometry, draft_geometry, mla_geometry,
                                      split_weights, with_fixed)

MODEL = Path(os.environ["MODEL_DIR"])
DRAFT = Path(os.environ["DRAFT_DIR"]) if os.environ.get("DRAFT_DIR") else None
WORLD = int(os.environ.get("WORLD", "3"))
RANK = int(os.environ.get("RANK", "0"))
PARALLEL = int(os.environ.get("PARALLEL", "8"))
PREFILL_ROWS = int(os.environ.get("TF_GLM_PREFILL_ROWS", "4096"))
CONTEXT = int(os.environ.get("CONTEXT", "262144"))
GiB = 1 << 30
pool_padding = (PARALLEL - 1) * 64

raw = json.loads((MODEL / "config.json").read_text())
text = dict(raw.get("text_config") or raw)

w = estimate_weights(MODEL, split_weights(rule, WORLD, text), rank=RANK,
                     files=rank_files(MODEL, RANK, WORLD) or None)
if DRAFT is not None:
    d = estimate_weights(DRAFT, lambda name, info: (
        math.prod(info["shape"]) * max(4, SIZES[info["dtype"]]), 0))
    w = Weights(w.resident + d.resident, w.staging + d.staging, w.mapped)

print(f"rank {RANK}: resident {w.resident/GiB:.2f} GiB | staging "
      f"{w.staging/GiB:.2f} GiB | mapped {w.mapped/GiB:.2f} GiB")

tgt = with_fixed(mla_geometry(padded_config(text, WORLD), WORLD, MAX_ROWS,
                              minimum_slots=DENSE_CAPACITY, latent=LATENT,
                              sequences=max(1, PARALLEL), pooled=PARALLEL > 1,
                              decode_rows=MAX_ROWS, prefill_rows=PREFILL_ROWS), 0)
dg = draft_geometry(text, WORLD, MAX_ROWS, bounded=True, streams=PARALLEL)
drf = Geometry(lambda s: dg.bytes_at(s + pool_padding), dg.reserve, dg.minimum_slots)


def workspace(tokens):
    slots = max(tgt.minimum_slots, tokens + tgt.reserve)
    return tgt.bytes_at(slots) + drf.bytes_at(slots)


def total(tokens):
    return w.resident + max(w.staging, workspace(tokens))


cur = 360448
print(f"\nworkspace({cur:,}) = {workspace(cur)/GiB:.2f} GiB")
print(f"total({cur:,})     = {total(cur)/GiB:.2f} GiB   "
      f"(startup log said 79.70 GiB)")
print(f"dominant term: {'staging/loading' if w.staging > workspace(cur) else 'workspace'}")
if w.staging > workspace(cur):
    lo, hi = CONTEXT, PARALLEL * CONTEXT
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if workspace(mid) <= w.staging:
            lo = mid
        else:
            hi = mid - 1
    print(f"  -> pool growth is FREE (no extra peak) up to ~{lo:,} tokens "
          f"({lo/CONTEXT:.2f}x context)")

BUDGET = float(os.environ.get("BUDGET_GIB", "102.16")) * GiB
KEPT = float(os.environ.get("TF_GLM_CACHE_GIB", "5")) * GiB
ceiling = BUDGET - KEPT
print(f"\nceiling = {BUDGET/GiB:.2f} - {KEPT/GiB:.2f} = {ceiling/GiB:.2f} GiB")
lo, hi = CONTEXT, PARALLEL * CONTEXT
while lo < hi:
    mid = (lo + hi + 1) // 2
    if total(mid) <= ceiling:
        lo = mid
    else:
        hi = mid - 1
print(f"largest pool that fits: {lo:,} tokens ({lo/CONTEXT:.2f}x context, "
      f"{lo/360448:.2f}x current)")
print(f"  total at that pool: {total(lo)/GiB:.2f} GiB")
print(f"  concurrent 256K sessions: {lo/262144:.1f}  (now {360448/262144:.1f})")
print(f"  concurrent 156K sessions: {lo/156000:.1f}  (now {360448/156000:.1f})")
if lo >= PARALLEL * CONTEXT:
    print("  NOTE: hit the LEGAL max (parallel x context), not a memory wall")

# ---- calibrated solve -------------------------------------------------------
# engine.py passes with_fixed(..., seeing + session/reply reserves + draft slot
# graphs). That extra is CONSTANT in pool size, so pin it from the engine's own
# logged total instead of re-deriving it.
LOGGED = float(os.environ.get("LOGGED_TOTAL_GIB", "79.70")) * GiB
const = LOGGED - total(cur)
print(f"\ncalibration constant (vision tower + reserves + slot graphs): {const/GiB:.2f} GiB")

def total_cal(tokens):
    return total(tokens) + const

lo, hi = CONTEXT, PARALLEL * CONTEXT
while lo < hi:
    mid = (lo + hi + 1) // 2
    if total_cal(mid) <= ceiling:
        lo = mid
    else:
        hi = mid - 1
print(f"CALIBRATED largest pool that fits: {lo:,} tokens "
      f"({lo/CONTEXT:.2f}x context, {lo/360448:.2f}x current)")
print(f"  total at that pool: {total_cal(lo)/GiB:.2f} GiB of {ceiling/GiB:.2f} GiB ceiling")
print(f"  concurrent 256K sessions: {lo/262144:.1f}  (now {360448/262144:.1f})")
print(f"  concurrent 156K sessions: {lo/156000:.1f}  (now {360448/156000:.1f})")
for safety in (0.90, 0.80):
    c2 = ceiling * safety
    a, b = CONTEXT, PARALLEL * CONTEXT
    while a < b:
        m = (a + b + 1) // 2
        if total_cal(m) <= c2: a = m
        else: b = m - 1
    print(f"  at {int(safety*100)}% of ceiling ({c2/GiB:.1f} GiB): {a:,} tokens "
          f"({a/CONTEXT:.2f}x ctx) -> {a/156000:.1f} concurrent 156K")
