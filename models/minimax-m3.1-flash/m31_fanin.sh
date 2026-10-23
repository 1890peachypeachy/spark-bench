#!/bin/bash
# Helper-node fan-in: wait for this node's HALF_DONE marker, rsync its slice to the
# landing node (spark2) over the CX7 fabric, then stamp FANIN_DONE on spark2.
# Runs detached on spark1 / spark4. Gates on artifact markers, never process liveness.
set -u
NODE="$1"                 # this node's tag, e.g. spark1
STAGE="$2"                # local staging root (contains the model subdir contents)
STATE="$HOME/m31-state"
LANDING_USER="spark2"
LANDING_FABRIC="10.73.0.2"
LANDING_DIR="/home/spark2/models/MiniMax-M3.1-Flash"
LIST="$STATE/split-$NODE.json"
LOG="$STATE/fanin-$NODE.log"

exec >>"$LOG" 2>&1
echo "=== fanin $NODE $(date -u +%FT%TZ) ==="

while [ ! -f "$STATE/HALF_DONE_$NODE" ]; do sleep 60; done
echo "HALF_DONE seen"

# rsync --files-from keeps subdir layout (docs/, figures/, dspark/)
python3 - "$LIST" > "$STATE/files-$NODE.txt" <<'EOF'
import json,sys
for p in json.load(open(sys.argv[1])): print(p)
EOF

for attempt in 1 2 3 4 5; do
  if rsync -a --copy-links --files-from="$STATE/files-$NODE.txt" "$STAGE"/ \
       "$LANDING_USER@$LANDING_FABRIC:$LANDING_DIR"/ ; then
    echo "rsync OK attempt $attempt"
    ssh -o BatchMode=yes "$LANDING_USER@$LANDING_FABRIC" \
        "mkdir -p ~/m31-state && touch ~/m31-state/FANIN_DONE_$NODE"
    echo "FANIN_DONE_$NODE stamped"
    exit 0
  fi
  echo "rsync failed attempt $attempt, retry in 60s"
  sleep 60
done
echo "FANIN FAILED for $NODE"
exit 1