#!/bin/bash
# Run chunkdl for THIS node's file slice, then stamp HALF_DONE_<node>.
# Used when the HF hub downloader is starved (single flow ~1-3 MB/s) and short
# parallel range requests pass (measured 13-16 MB/s aggregate).
# usage: x35_chunkdl.sh <node-tag> <dest-dir> <state-dir>
set -u
NODE="$1"; DEST="$2"; STATE="$3"
REPO="LibertAIDAI/DeepSeek-V4.1-Flash-1017-EXL3-3.5bpw"
REV="04a492fc3b4d25ddbab8f2d2f07f235ec77c9010"

cd "$STATE" || exit 1
python3 - "$STATE/split-$NODE.json" "$STATE/manifest-$NODE.json" <<'EOF'
import json, sys
want = set(json.load(open(sys.argv[1])))
all_ = json.load(open("manifest.json"))
sub = [e for e in all_ if e["name"] in want]
assert len(sub) == len(want), (len(sub), len(want))
json.dump(sub, open(sys.argv[2], "w"), indent=1)
print(f"{len(sub)} files, {sum(e['size'] for e in sub)/1024**3:.1f} GiB")
EOF

python3 chunkdl.py --repo "$REPO" --revision "$REV" \
    --dest "$DEST" --manifest "$STATE/manifest-$NODE.json" \
    --workers 64 --chunk-mib 2
rc=$?
if [ $rc -eq 0 ]; then
  date -u +%FT%TZ > "$STATE/HALF_DONE_$NODE"
  echo "HALF_DONE_$NODE stamped"
else
  echo "chunkdl FAILED rc=$rc for $NODE"
fi
exit $rc