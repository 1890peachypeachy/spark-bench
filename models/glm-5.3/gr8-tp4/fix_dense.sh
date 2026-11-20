#!/bin/bash
cd /var/tmp/gr8/recipe
M=$(echo /var/tmp/gr8/cache/hf/kindlingai--glm-5.3-exlr8-k2-k3-k4/*)
python3 - "$M" <<'PY'
import json,os,sys
root=sys.argv[1]
t=json.load(open(os.path.join(root,'.tree.json')))
bad=[]
for k,v in t.items():
    if not k.startswith('dense/'): continue
    want=v[1]; p=os.path.join(root,k)
    if not os.path.exists(p) or os.path.getsize(p)!=want:
        bad.append(k)
        try: os.remove(p)
        except Exception as e: print('rm fail',k,e)
print('removed',len(bad),'stale dense files')
PY
setsid nohup ./fetch > /var/tmp/gr8/fetch.log 2>&1 < /dev/null &
echo "restarted fetch"
