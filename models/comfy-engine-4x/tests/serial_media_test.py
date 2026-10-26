#!/usr/bin/env python3
"""Serial per-node test with the native TF4 lane up: image -> design -> song, one job at a time, POST /free between.
Records the lowest ram_free seen per job. Skips a job if ram_free < 8 GB before it starts (guard floor is 4)."""
import json, sys, time, threading
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import mixed_render_test as m

NODES = {k: v for k, v in m.NODES.items() if k in sys.argv[1:]} or m.NODES
JOBS = [("image", m.graph_image), ("design", m.graph_design), ("song", m.graph_song), ("video", m.graph_video)]


def run(node, base, res):
    for kind, fn in JOBS:
        free0 = m.mem(base)
        if free0 is None or free0 < (30 if kind == "video" else 8):
            res.append((node, kind, "SKIPPED low ram", free0, None, None))
            continue
        low = [free0]
        stop = [False]

        def sampler():
            while not stop[0]:
                v = m.mem(base)
                if v is not None:
                    low[0] = min(low[0], v)
                time.sleep(1)

        t = threading.Thread(target=sampler, daemon=True)
        t.start()
        t0 = time.time()
        status = "?"
        try:
            pid = m.post(f"{base}/prompt", {"prompt": fn(), "client_id": f"ser-{node}"})["prompt_id"]
            while time.time() - t0 < 900:
                time.sleep(3)
                try:
                    h = m.get(f"{base}/history/{pid}", 20)
                except Exception:
                    continue
                if h.get(pid):
                    status = h[pid]["status"]["status_str"]
                    break
            else:
                status = "TIMEOUT"
        except Exception as e:
            status = f"ERR {str(e)[:120]}"
        stop[0] = True
        t.join()
        res.append((node, kind, status, free0, low[0], round(time.time() - t0, 1)))
        print(res[-1], flush=True)
        try:
            m.post(f"{base}/free", {"unload_models": True, "free_memory": True}, 30)
        except Exception:
            pass
        time.sleep(5)


res = []
for node, base in NODES.items():  # nodes one after another: one render on the fleet at a time
    run(node, base, res)
print("node  job  status  ram_free_start  lowest  secs")
for r in res:
    print(*r, sep="  ")
json.dump(res, open("/tmp/serial_media.json", "w"))
