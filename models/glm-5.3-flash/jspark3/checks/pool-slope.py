#!/usr/bin/env python3
"""Marginal memory cost per pool token, from the engine's OWN geometry function.

Runs inside the serving container (tensorfold importable). Pure arithmetic:
mla_geometry(...).bytes_at(n) and draft_geometry(...).bytes_at(n) are closed-form
size calculations, they allocate nothing on the device.

Replicates engine.py:target_plan/draft_plan exactly (lines 238-257):
    g = with_fixed(mla_geometry(padded_config(text, world), world, verify_rows,
                                minimum_slots=DENSE_CAPACITY, latent=LATENT,
                                sequences=max(1, parallel), pooled=parallel > 1,
                                decode_rows=verify_rows, prefill_rows=prefill_rows), extra)
    draft: Geometry(lambda slots: g.bytes_at(slots + pool_padding), ...)

`with_fixed`'s extra and the weight bytes are CONSTANT in capacity, so they
cancel out of a difference and the slope below is the true marginal cost.
"""
import json
import os
from pathlib import Path

from tensorfold.cuda.geometry import draft_geometry, mla_geometry
from tensorfold.families.glm5_next.cuda import LATENT
from tensorfold.families.glm5_next.cuda.engine import DENSE_CAPACITY, MAX_ROWS
from tensorfold.families.glm5_next.cuda.split import padded_config

MODEL = os.environ["MODEL_DIR"]
WORLD = int(os.environ.get("WORLD", "3"))
PARALLEL = int(os.environ.get("PARALLEL", "8"))
PREFILL_ROWS = int(os.environ.get("TF_GLM_PREFILL_ROWS", "4096"))
VERIFY_ROWS = MAX_ROWS

raw = json.loads((Path(MODEL) / "config.json").read_text())
text = dict(raw.get("text_config") or raw)
cfg = padded_config(text, WORLD)

tgt = mla_geometry(cfg, WORLD, VERIFY_ROWS, minimum_slots=DENSE_CAPACITY,
                   latent=LATENT, sequences=max(1, PARALLEL),
                   pooled=PARALLEL > 1, decode_rows=VERIFY_ROWS,
                   prefill_rows=PREFILL_ROWS)
pool_padding = (PARALLEL - 1) * 64
draft_g = draft_geometry(cfg, WORLD, MAX_ROWS, bounded=True, streams=PARALLEL)

GiB = 1 << 30
print(f"LATENT={LATENT} world={WORLD} parallel={PARALLEL} "
      f"prefill_rows={PREFILL_ROWS} reserve={tgt.reserve}")


def workspace(tokens):
    """engine.fit_shared_pool.workspace"""
    slots = max(tgt.minimum_slots, tokens + tgt.reserve)
    return tgt.bytes_at(slots) + draft_g.bytes_at(slots + pool_padding)


pts = [262144, 360448, 524288, 786432, 1048576, 1572864, 2097152]
print(f"\n{'pool tokens':>12} {'xctx':>6} {'workspace GiB':>14} {'delta vs now GiB':>18}")
base = workspace(360448)
for n in pts:
    w = workspace(n)
    print(f"{n:>12,} {n/262144:>5.2f}x {w/GiB:>13.2f} {(w-base)/GiB:>+17.2f}")

# marginal slope
a, b = 400000, 500000
slope = (workspace(b) - workspace(a)) / (b - a)
print(f"\nmarginal cost: {slope:,.0f} bytes/token = {slope/1024:.2f} KiB/token")
print(f"  -> 1 GiB buys {GiB/slope:,.0f} pool tokens")
print(f"  -> 100K extra tokens costs {100000*slope/GiB:.2f} GiB")

HEADROOM = float(os.environ.get("HEADROOM_GIB", "17.5"))
extra = HEADROOM * GiB / slope
print(f"\nwith {HEADROOM} GiB headroom on the binding rank:")
print(f"  extra pool tokens affordable : ~{extra:,.0f}")
print(f"  new pool would be            : ~{360448+extra:,.0f} tokens "
      f"({(360448+extra)/262144:.2f}x context)")
print(f"  concurrent 256K sessions     : {(360448+extra)/262144:.1f} "
      f"(now {360448/262144:.1f})")
print(f"  concurrent 156K sessions     : {(360448+extra)/156000:.1f} "
      f"(now {360448/156000:.1f})")
