#!/bin/bash
# ablit_node.sh RANK: on one node, a patched COPY of its TensorFold rank cache with the Keys 1017 wo_b overlay
# (cache-ablit/, same file name). The live cache is only READ (direct IO), never written.
# Adapted from tonyd2wild runs/2026-10-18-1017-tensorfold-uncensored/tools/ablit_node.sh for our paths:
#   cache root /var/tmp/tf1017/cache, patched copy /var/tmp/tf1017/cache-ablit.
set -euo pipefail
g=${1:?rank}; W=/var/tmp/tf1017-ablit; C=/var/tmp/tf1017/cache; A=/var/tmp/tf1017/cache-ablit
src=$(ls $C/rank-cache/rank${g}of4-*.bin); [ $(echo "$src" | wc -l) = 1 ]
mkdir -p $A/rank-cache; dst=$A/rank-cache/$(basename "$src")
[ -e "$dst" ] && { echo "rank $g: $dst already there"; exit 0; }
echo "rank $g: copy $(basename "$src") $(date -u +%T)"
dd if="$src" of="$dst.part" bs=64M iflag=direct oflag=direct status=none
[ $(stat -c %s "$src") = $(stat -c %s "$dst.part") ] || { echo "rank $g: size mismatch"; exit 1; }
cp $C/dsv41_token_map.json $A/
python3 $W/overlay/apply_rank_blobs.py --bin "$dst.part" --manifest $W/blobs/r$g/manifest.json
python3 - "$dst.part" "$src" $W/blobs/r$g/manifest.json <<'PY'
import json, sys, os
dst, src, man = sys.argv[1:4]; rows = json.load(open(man)); d = open(dst, "rb"); s = open(src, "rb"); bad = changed = 0
for r in rows:
    blob = open(os.path.join(os.path.dirname(man), r["file"]), "rb").read()
    d.seek(r["off"]); got = d.read(r["nbytes"]); s.seek(r["off"]); old = s.read(r["nbytes"])
    bad += got != blob; changed += old != blob
# spot-check unpatched regions: just before and after each patched slice
for r in rows[:: max(1, len(rows) // 8)]:
    for o in (max(0, r["off"] - 4096), r["off"] + r["nbytes"]):
        d.seek(o); s.seek(o); bad += d.read(4096) != s.read(4096)
print(f"VERIFY rows {len(rows)} written-ok {len(rows) - bad if bad <= len(rows) else 0} changed-vs-stock {changed} bad {bad}")
sys.exit(1 if bad else 0)
PY
mv "$dst.part" "$dst"
echo "rank $g: done $(date -u +%T)"
