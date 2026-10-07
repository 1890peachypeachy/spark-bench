#!/usr/bin/env python3
"""v2.0.2 rolling-image reuse — strictly append-only chain.

Attempt 2 kept a trailing question message that MOVED every turn, so the shared
prefix diverged there and every request reported session_miss_reason='fork'
with a flat cached=9 (the system prompt only). A real agent client is
append-only: each turn appends one user message and one assistant reply.

Here each turn appends ONE user message (image + its question) and then the
assistant's real reply, so turn N+1's prefix is exactly turn N's prompt plus
that reply. Rotation (keep newest 8 images, archive older ones) still rewrites
earlier turns once past the cap, which is the case v2.0.2 fixes.
"""
import base64, io, json, urllib.request

URL = "http://100.99.120.29:8888/v1/chat/completions"
MODEL = "GLM-5.3-Flash-EXL3"
KEEP, TURNS = 8, 10
NAMES = ["red", "lime", "blue", "yellow", "magenta", "cyan", "white",
         "orange", "purple", "brown"]
RGB = {"red": (255, 0, 0), "lime": (0, 255, 0), "blue": (0, 0, 255),
       "yellow": (255, 255, 0), "magenta": (255, 0, 255), "cyan": (0, 255, 255),
       "white": (255, 255, 255), "orange": (255, 165, 0),
       "purple": (128, 0, 128), "brown": (139, 69, 19)}


def png(name, size=160):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (size, size), RGB[name]).save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


CACHE = {n: png(n) for n in NAMES}
# Padding makes each turn substantial, so reuse has something to show.
PAD = ("Context note: this is a colour-identification session. Keep answers to "
       "one word. ") * 12


def post(messages, max_tokens=24):
    body = json.dumps({"model": MODEL, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


SYSTEM = {"role": "system", "content":
          "You identify colours. Answer with exactly one word. " + PAD}

turns = []       # [(name, reply_or_None)]
rows = []

for t in range(1, TURNS + 1):
    turns.append((NAMES[t - 1], None))
    msgs = [SYSTEM]
    for i, (name, reply) in enumerate(turns):
        keep = i >= len(turns) - KEEP
        if keep:
            content = [{"type": "image_url", "image_url": {"url": CACHE[name]}},
                       {"type": "text", "text":
                        f"Image {i + 1}. {PAD}Name this colour."}]
        else:
            content = [{"type": "text", "text":
                        f"[archived image {i + 1}] {PAD}Name this colour."}]
        msgs.append({"role": "user", "content": content})
        if reply is not None:
            msgs.append({"role": "assistant", "content": reply})

    resp = post(msgs)
    tf = resp.get("tensorfold", {}) or {}
    m = resp["choices"][0]["message"]
    ans = (m.get("content") or "").strip()
    turns[-1] = (NAMES[t - 1], ans)
    rows.append({"t": t, "rot": t > KEEP, "cached": tf.get("cached"),
                 "miss": tf.get("session_miss_reason"),
                 "src": tf.get("session_cache_source"),
                 "tool": bool(m.get("tool_calls")), "ans": ans})
    print(f"turn {t:2d} rotating={str(t > KEEP):5s} cached={str(tf.get('cached')):>7s} "
          f"src={str(tf.get('session_cache_source')):>5s} "
          f"miss={str(tf.get('session_miss_reason')):>24s} "
          f"tool={m.get('tool_calls') is not None} ans={ans[:20]!r}")

print("=" * 80)
cached = [r["cached"] for r in rows if isinstance(r["cached"], int)]
rot = [r["cached"] for r in rows if r["rot"] and isinstance(r["cached"], int)]
pre = [r["cached"] for r in rows if not r["rot"] and isinstance(r["cached"], int)]
grew = len(cached) > 1 and max(cached) > min(cached)
resumed = any(r["miss"] in (None, "", "none") or r["miss"] is None for r in rows)
rot_nonzero = bool(rot) and all(c > 0 for c in rot)
no_tool = not any(r["tool"] for r in rows)

print(f"cached by turn: {cached}")
print(f"pre-rotation:   {pre}")
print(f"rotated turns:  {rot}")
print(f"{'PASS' if grew else 'FAIL'}  reuse GROWS across turns "
      f"(flat = no history resume, only the system prefix)")
print(f"{'PASS' if rot_nonzero else 'FAIL'}  reuse nonzero on every rotated turn")
print(f"{'PASS' if no_tool else 'FAIL'}  no spurious tool_call "
      f"(upstream's 2026-10-05 failure mode)")
print(f"ROLLING IMAGE {sum([grew, rot_nonzero, no_tool])}/3")
