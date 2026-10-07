#!/usr/bin/env python3
"""Does rotated-turn reuse appear once the boundary checkpoint is durable?

v202-rolling-check2 showed reuse collapse to the system prefix (cached=9,
miss='fork') on the first rotated turn. Upstream states the image-boundary
checkpoint must be SAVED before a later rotation can reuse it, and that
"continuous traffic can still skip optional saves under the existing bounded
writer policy". So: send the SAME rotated prompt twice with a pause between.

If attempt 2 reuses, the collapse is checkpoint-save latency (expected, benign).
If attempt 2 also forks, rotated-turn reuse is not working on this lane.
"""
import base64, io, json, time, urllib.request

URL = "http://100.99.120.29:8888/v1/chat/completions"
MODEL = "GLM-5.3-Flash-EXL3"
KEEP = 8
NAMES = ["red", "lime", "blue", "yellow", "magenta", "cyan", "white",
         "orange", "purple", "brown"]
RGB = {"red": (255, 0, 0), "lime": (0, 255, 0), "blue": (0, 0, 255),
       "yellow": (255, 255, 0), "magenta": (255, 0, 255), "cyan": (0, 255, 255),
       "white": (255, 255, 255), "orange": (255, 165, 0),
       "purple": (128, 0, 128), "brown": (139, 69, 19)}
PAD = ("Context note: this is a colour-identification session. Keep answers to "
       "one word. ") * 12


def png(name, size=160):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (size, size), RGB[name]).save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


CACHE = {n: png(n) for n in NAMES}
SYSTEM = {"role": "system", "content":
          "You identify colours. Answer with exactly one word. " + PAD}
REPLIES = ["Red", "Green", "Blue", "Yellow", "Magenta", "Cyan", "White",
           "Orange", "Purple", "Brown"]


def build(n_turns):
    """The rotated conversation at n_turns images, newest KEEP kept."""
    msgs = [SYSTEM]
    for i in range(n_turns):
        keep = i >= n_turns - KEEP
        if keep:
            content = [{"type": "image_url",
                        "image_url": {"url": CACHE[NAMES[i]]}},
                       {"type": "text", "text":
                        f"Image {i + 1}. {PAD}Name this colour."}]
        else:
            content = [{"type": "text", "text":
                        f"[archived image {i + 1}] {PAD}Name this colour."}]
        msgs.append({"role": "user", "content": content})
        if i < n_turns - 1:
            msgs.append({"role": "assistant", "content": REPLIES[i]})
    return msgs


def post(messages, max_tokens=24):
    body = json.dumps({"model": MODEL, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def probe(label, msgs):
    r = post(msgs)
    tf = r.get("tensorfold", {}) or {}
    ans = (r["choices"][0]["message"].get("content") or "").strip()
    print(f"  {label:28s} cached={str(tf.get('cached')):>7s} "
          f"src={str(tf.get('session_cache_source')):>6s} "
          f"miss={str(tf.get('session_miss_reason')):>22s} "
          f"evid={str(tf.get('session_reason_evidence'))[:26]:>26s} ans={ans[:14]!r}")
    return tf.get("cached"), tf.get("session_miss_reason")


# Warm the chain up to turn 8 (pre-rotation) so history exists on the lane.
print("warming the pre-rotation chain (turns 1..8)")
for t in range(1, KEEP + 1):
    post(build(t))
print()

print("ROTATED TURN 9 — first attempt, then after a pause")
c1, m1 = probe("attempt 1 (immediate)", build(9))
time.sleep(25)
c2, m2 = probe("attempt 2 (+25s)", build(9))
time.sleep(40)
c3, m3 = probe("attempt 3 (+65s)", build(9))

print()
print("=" * 78)
vals = [v for v in (c1, c2, c3) if isinstance(v, int)]
best = max(vals) if vals else 0
improved = best > 9
print(f"rotated-turn cached across attempts: {[c1, c2, c3]}")
print(f"miss reasons:                        {[m1, m2, m3]}")
if improved:
    print("VERDICT: rotated-turn reuse DOES engage once the checkpoint is durable")
    print("         -> the first-attempt collapse is save latency, benign")
else:
    print("VERDICT: rotated-turn reuse did NOT engage on repeat attempts")
    print("         -> v2.0.2's headline image-rotation fix is NOT demonstrable")
    print("            on this lane with this fixture; non-rotating reuse is fine")
