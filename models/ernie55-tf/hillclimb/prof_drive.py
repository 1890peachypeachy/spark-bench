"""Drive phase-separated workloads against :8888 while nsys sessions record each phase (rank 0 under `nsys launch`).

Usage: python3 -I prof_drive.py <session> <outdir>
Phases: dec1 (1 stream x 2 requests x 256 tok), dec4 (4 streams x 256 tok), pre16k (one cold ~16K prompt, 1 token).
Each phase: nsys start -> workload -> nsys stop (one .nsys-rep per phase).
"""
import concurrent.futures as cf
import json
import random
import string
import subprocess
import sys
import time
import urllib.request

SESSION, OUT = sys.argv[1], sys.argv[2]
URL = "http://127.0.0.1:8888/v1/chat/completions"
MODEL = "GLM-5.3-Flash-EXL3"
NSYS = "/usr/local/bin/nsys"


def chat(content, max_tokens):
    body = {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": 0.6, "top_p": 0.95, "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    n = 0
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:") and line[5:].strip() != "[DONE]":
                n += 1
    return time.perf_counter() - t0, n


def tag():
    return "".join(random.choice(string.ascii_lowercase) for _ in range(12))


def phase(name, fn):
    subprocess.run([NSYS, "start", f"--session={SESSION}", f"--output={OUT}/prof_{name}", "--force-overwrite=true"], check=True)
    t0 = time.time()
    fn()
    dt = time.time() - t0
    subprocess.run([NSYS, "stop", f"--session={SESSION}"], check=True)
    print(f"phase {name}: {dt:.1f}s", flush=True)


def dec1():
    for _ in range(2):
        print(chat(f"[{tag()}] Write a detailed explanation of how a hash map handles collisions, with examples.", 256), flush=True)


def dec4():
    with cf.ThreadPoolExecutor(4) as ex:
        for r in ex.map(lambda i: chat(f"[{tag()}] Explain topic {i}: the history of the printing press in depth.", 256), range(4)):
            print(r, flush=True)


def pre16k():
    words = " ".join(random.choice(["alpha", "river", "stone", "cloud", "ember", "quartz", "maple", "orbit"]) for _ in range(12500))
    print(chat(f"[{tag()}] Summarize in one word: {words}", 1), flush=True)


print(chat(f"[{tag()}] Say hello.", 16), flush=True)  # warm graphs outside any phase
for nm, f in (("dec1", dec1), ("dec4", dec4), ("pre16k", pre16k)):
    phase(nm, f)
print("DONE", flush=True)
