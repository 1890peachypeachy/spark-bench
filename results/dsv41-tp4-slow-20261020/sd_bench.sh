#!/usr/bin/env bash
# sparkDash DecodeBench, knapcio protocol: 256 tok, thinking off, 2 discarded prose c1 warm-ups,
# prose c1 x3, c4 x2, c8/c16 x1, code+json c1. Output: OUTDIR/sparkdash.txt
OUT=${1:-.}; PORT=${2:-8888}; DASH=http://127.0.0.1:5555/api/sparks/spark3/llm
mkdir -p "$OUT"; : > "$OUT/sparkdash.txt"
sd() {  # promptType concurrency
  id=$(curl -s -X POST "$DASH/bench" -H 'Content-Type: application/json' \
    -d "{\"port\":$PORT,\"concurrencies\":[$2],\"maxTokens\":256,\"promptType\":\"$1\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("benchId",""))')
  [[ -z $id ]] && { echo "REFUSED $1 c$2" | tee -a "$OUT/sparkdash.txt"; return; }
  for i in $(seq 1 150); do sleep 4; curl -s "$DASH/bench" | python3 -c 'import json,sys; sys.exit(1 if json.load(sys.stdin)["active"] else 0)' && break; done
  curl -s "$DASH/bench" > "$OUT/raw-$1-c$2-$id.json"
  python3 - "$OUT/raw-$1-c$2-$id.json" "$1" "$2" <<'E' | tee -a "$OUT/sparkdash.txt"
import json,sys
d=json.load(open(sys.argv[1]))["last"]
for r in d.get("results",[]):
    print(sys.argv[2],"c%s"%sys.argv[3],{k:v for k,v in r.items() if "tok" in k.lower() or k=="concurrency"})
E
}
sd prose 1 >/dev/null; sd prose 1 >/dev/null
echo "# measured"
for i in 1 2 3; do sd prose 1; done
for i in 1 2; do sd prose 4; done
sd prose 8; sd prose 16
sd code 1; sd json 1
