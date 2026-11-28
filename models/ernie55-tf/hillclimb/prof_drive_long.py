"""Long-context decode profile: nsys records rank 0 per phase while each stream decodes on its own warm ~64K context.

Usage: python3 -I prof_drive_long.py <session> <outdir> [ctx_tokens=64000]
Outside any phase: one hello, then 4 cold ~64K documents (each prompt-cached).
Phases: dec1_64k (1 stream, 256 tok), dec4_64k (4 streams, 256 tok each), dec4 (4 short-prompt streams, 256 tok).
Requests sent: 1 + 4 + 1 + 4 + 4 = 14 (the chain's contamination check expects exactly that).
"""
import concurrent.futures as cf
import json
import random
import subprocess
import sys
import time
import urllib.request

SESSION, OUT = sys.argv[1], sys.argv[2]
CTX = int(sys.argv[3]) if len(sys.argv) > 3 else 64000
URL = "http://127.0.0.1:8888/v1/chat/completions"
MODEL = "GLM-5.3-Flash-EXL3"
NSYS = "/usr/local/bin/nsys"
WORDS = ("alpha river stone cloud ember quartz maple orbit cedar delta falcon harbor iris juniper kepler lumen "
         "meadow nickel onyx prism quill raven sierra tundra umber violet willow xenon yarrow zephyr").split()


def chat(content, max_tokens):
    body = {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": 0.6, "top_p": 0.95, "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    usage = {}
    with urllib.request.urlopen(req, timeout=1200) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:") and line[5:].strip() != "[DONE]":
                obj = json.loads(line[5:].strip())
                if obj.get("usage"):
                    usage = obj["usage"]
    return round(time.perf_counter() - t0, 2), usage.get("prompt_tokens"), usage.get("completion_tokens")


def doc(tag):
    rng = random.Random(tag)
    n_words, lines, words, i = int(CTX / 1.3), [], 0, 0
    while words < n_words:
        k = rng.randint(8, 16)
        lines.append(f"{i}. " + " ".join(rng.choice(WORDS) for _ in range(k)) + ".")
        words += k + 1
        i += 1
    return f"[doc {tag}]\n" + "\n".join(lines)


def phase(name, fn):
    subprocess.run([NSYS, "start", f"--session={SESSION}", f"--output={OUT}/prof_{name}", "--force-overwrite=true"], check=True)
    t0 = time.time()
    fn()
    dt = time.time() - t0
    subprocess.run([NSYS, "stop", f"--session={SESSION}"], check=True)
    print(f"phase {name}: {dt:.1f}s", flush=True)


run = "%08x" % random.getrandbits(32)
docs = [doc(f"{run}-{i}") for i in range(4)]
print(chat(f"[{run}] Say hello.", 16), flush=True)  # warm graphs outside any phase
for d in docs:  # cold prefill of each context, outside any phase
    print("warm", chat(d + "\n\nReply with the single word OK.", 8), flush=True)


def turn(i, long_ctx):
    q = f"\n\n[turn {run}-{i}-{int(long_ctx)}] Using the document above only as background, write a detailed essay about bridges."
    return chat((docs[i] if long_ctx else f"[{run}-{i}] Topic {i}.") + q, 256)


def dec1_64k():
    print(turn(0, True), flush=True)


def dec4_64k():
    with cf.ThreadPoolExecutor(4) as ex:
        for r in ex.map(lambda i: turn(i, True), range(4)):
            print(r, flush=True)


def dec4():
    with cf.ThreadPoolExecutor(4) as ex:
        for r in ex.map(lambda i: turn(i, False), range(4)):
            print(r, flush=True)


for nm, f in (("dec1_64k", dec1_64k), ("dec4_64k", dec4_64k), ("dec4", dec4)):
    phase(nm, f)
print("DONE", flush=True)
