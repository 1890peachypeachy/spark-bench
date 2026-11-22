import json, sys, threading, time, urllib.request
base, model, n, maxtok = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
P = ["Write a clear five-paragraph explanation of how solid-state drives wear out over time.",
     "Write a complete Python module implementing a thread-safe LRU cache with TTL per entry, with docstrings and unittests.",
     "Explain how TCP congestion control works, covering slow start, congestion avoidance and fast recovery in detail.",
     "Write a detailed guide to setting up a home network with VLANs, including firewall rules and examples.",
     "Describe in depth how a transformer's attention mechanism works, with a worked numeric example.",
     "Write a long essay on the history of the printing press and its effect on European society."]
res = [None]*n
def run(i):
    body = json.dumps({"model": model, "messages":[{"role":"user","content":P[i%len(P)]}], "max_tokens": maxtok,
                       "temperature": 0, "stream": True, "stream_options":{"include_usage": True}, "reasoning_effort":"low"}).encode()
    req = urllib.request.Request(base+"/chat/completions", body, {"Content-Type":"application/json"})
    t0=time.time(); first=None; toks=0
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            line=line.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"): continue
            try: d=json.loads(line[5:])
            except Exception: continue
            if d.get("usage"): toks=d["usage"].get("completion_tokens",toks)
            ch=d.get("choices") or []
            if ch and (ch[0].get("delta",{}).get("content") or ch[0].get("delta",{}).get("reasoning_content") or ch[0].get("delta",{}).get("reasoning")):
                if first is None: first=time.time()
    res[i]=(t0, first, time.time(), toks)
th=[threading.Thread(target=run,args=(i,)) for i in range(n)]
T0=time.time(); [t.start() for t in th]; [t.join() for t in th]; T1=time.time()
ok=[r for r in res if r and r[1]]
tot=sum(r[3] for r in ok)
per=[r[3]/(r[2]-r[1]) for r in ok if r[2]>r[1]]
span=max(r[2] for r in ok)-min(r[1] for r in ok)
print(json.dumps({"streams":n,"ok":len(ok),"total_tokens":tot,"aggregate_tok_s_overlap":round(tot/span,1),
  "per_stream_tok_s":[round(x,1) for x in per],"mean_per_stream":round(sum(per)/len(per),1),"ttft_s":[round(r[1]-r[0],2) for r in ok]}))
