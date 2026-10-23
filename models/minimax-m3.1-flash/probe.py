#!/usr/bin/env python3
"""Parallel range-GET probe: measure aggregate throughput of N concurrent 2 MiB chunks.
Used to decide between a per-file stream downloader and chunkdl (short parallel ranges).
usage: probe.py <n_threads> <seconds>
"""
import sys, threading, time, urllib.request

URL = ("https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash/resolve/"
       "9e7ebacac350497ad4a1272a2e817639bf11561c/model-00020-of-00048.safetensors")
N = int(sys.argv[1]); SECS = float(sys.argv[2])
lock = threading.Lock()
bytes_total = [0]
stop = time.time() + SECS
counter = [0]


def worker():
    while time.time() < stop:
        with lock:
            i = counter[0]; counter[0] += 1
        start = i * 2 * 1024 * 1024
        end = start + 2 * 1024 * 1024 - 1
        req = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}",
                                                  "User-Agent": "probe/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read()
            with lock:
                bytes_total[0] += len(data)
        except Exception:
            time.sleep(1)


ts = [threading.Thread(target=worker, daemon=True) for _ in range(N)]
t0 = time.time()
for t in ts: t.start()
for t in ts: t.join()
dt = time.time() - t0
print(f"threads={N} {bytes_total[0]/1024**2:.1f} MiB in {dt:.0f}s "
      f"=> {bytes_total[0]/dt/1024**2:.1f} MB/s aggregate")