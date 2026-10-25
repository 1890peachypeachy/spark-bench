#!/bin/bash
# Finalize cache-ablit on one node: re-verify ONLY patched slices against the blobs, plus the gaps BETWEEN them
# against the stock cache, then rename .part -> final. The earlier inline check counted a false positive:
# it sampled "after" = off+nbytes, which is the START of the next patched slice (rows are contiguous),
# so of course it differed from stock. That is why all four ranks reported exactly 9 "bad".
set -euo pipefail
g=${1:?rank}; W=/var/tmp/tf1017-ablit; C=/var/tmp/tf1017/cache; A=/var/tmp/tf1017/cache-ablit
src=$(ls $C/rank-cache/rank${g}of4-*.bin)
part=$(ls $A/rank-cache/rank${g}of4-*.bin.part)
python3 - "$part" "$src" $W/blobs/r$g/manifest.json <<'PY'
import json, sys, os
dst, src, man = sys.argv[1:4]
rows = sorted(json.load(open(man)), key=lambda r: r["off"])
d = open(dst, "rb"); s = open(src, "rb")
base = os.path.dirname(man)
patched_bad = gap_bad = changed = 0
for r in rows:
    blob = open(os.path.join(base, r["file"]), "rb").read()
    d.seek(r["off"]); got = d.read(r["nbytes"])
    s.seek(r["off"]); old = s.read(r["nbytes"])
    patched_bad += got != blob
    changed += old != blob
# gaps between consecutive patched rows must be byte-identical to stock
prev_end = 0
for r in rows:
    if r["off"] > prev_end:
        n = min(r["off"] - prev_end, 1 << 20)   # up to 1 MB at the head of each gap
        d.seek(prev_end); s.seek(prev_end)
        gap_bad += d.read(n) != s.read(n)
    prev_end = r["off"] + r["nbytes"]
print(f"VERIFY rank slices {len(rows)} patched_bad {patched_bad} changed_vs_stock {changed} gap_bad {gap_bad}")
sys.exit(1 if (patched_bad or gap_bad) else 0)
PY
final=${part%.part}
mv "$part" "$final"
echo "FINAL $(basename "$final") $(stat -c %s "$final") bytes  $(date -u +%T)"
