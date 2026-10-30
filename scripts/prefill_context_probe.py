#!/usr/bin/env python3
"""Cold-prefill probe against the live TP=4 TensorFold engine.

Builds a unique ~200k-token prompt (no prefix-cache reuse possible), sends ONE
streaming chat request, and prints time-to-first-token (= cold prefill time),
the server's own prompt_tokens count, and whether the request succeeded.
"""
import json, random, string, sys, time, urllib.request

URL = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "DeepSeek-V4.1-Flash-TF"
LINES = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
OUT = "/home/jun/tf4/logs/prefill-200k-prompt.txt"

vocab = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
         "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
         "xray yankee zulu amber basalt cedar dune ember flint granite hazel ivory "
         "jasper kelp lantern marble nimbus onyx pebble quartz ridge slate thistle "
         "umber verdant willow xenon yarrow zinc acorn birch cirrus dew elder fern "
         "gale heather inlet juniper knoll lagoon mist nook orchard pine quill reed "
         "sandstone tide upland vale wren yew ashen brook cobble drift flintstone glen "
         "hollow ironstone junction kettle lichen meadow nutmeg oak umbra violet wave").split()
rnd = random.Random(20261014)

parts = ["The following is a numbered inventory of mineral and plant sample codes.",
         "Read it completely, then answer the question at the very end.", ""]
for i in range(LINES):
    words = " ".join(rnd.choice(vocab) for _ in range(8))
    parts.append(f"{i:06d}: {words}")
parts.append("")
parts.append("Question: how many numbered lines are in the inventory above? "
             "Answer with the number only.")
prompt = "\n".join(parts)

print(f"[probe] lines={LINES} chars={len(prompt)} (~{len(prompt)//5} tokens by chars/5)", flush=True)
with open(OUT, "w") as fh:
    fh.write(prompt)

body = json.dumps({
    "model": MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 16, "temperature": 0, "stream": True,
    "stream_options": {"include_usage": True},
    "chat_template_kwargs": {"enable_thinking": False},
}).encode()
req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})

t0 = time.monotonic()
first = None
chunks = 0
usage = None
delta_t0 = None
text = ""
try:
    with urllib.request.urlopen(req, timeout=3600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            d = json.loads(payload)
            chunks += 1
            if d.get("usage"):
                usage = d["usage"]
            if first is None:
                first = time.monotonic() - t0
                print(f"[probe] TTFT(first stream chunk, = prefill done)={first:.3f}s", flush=True)
            delta = ((d.get("choices") or [{}])[0].get("delta") or {})
            piece = delta.get("content") or delta.get("reasoning_content") or ""
            if piece and delta_t0 is None:
                delta_t0 = time.monotonic() - t0
                print(f"[probe] first real token (delta) at {delta_t0:.3f}s", flush=True)
            text += piece
except Exception as exc:  # noqa: BLE001 - report the failure, that is the point
    print(f"[probe] FAILED after {time.monotonic()-t0:.1f}s: {type(exc).__name__}: {exc}", flush=True)
    sys.exit(1)

total = time.monotonic() - t0
print(f"[probe] SUCCESS total={total:.3f}s first_chunk={first} first_token={delta_t0} chunks={chunks}", flush=True)
print(f"[probe] usage={json.dumps(usage)}", flush=True)
print(f"[probe] answer={text!r}", flush=True)
