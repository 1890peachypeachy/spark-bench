#!/usr/bin/env python3
"""v2.0.2 acceptance: GIF frame-zero support + rolling-image checkpoint reuse.

These are the two fixes this release ships, and the checks upstream's first live
swap (2026-10-05 17:37Z) FAILED before being rolled back. Run with the lane idle.
"""
import base64, io, json, urllib.request

URL = "http://100.99.120.29:8888/v1/chat/completions"
MODEL = "GLM-5.3-Flash-EXL3"
COLORS = ["red", "lime", "blue", "yellow", "magenta", "cyan", "white",
          "orange", "purple", "brown", "pink", "gray"]
RGB = {"red": (255, 0, 0), "lime": (0, 255, 0), "blue": (0, 0, 255),
       "yellow": (255, 255, 0), "magenta": (255, 0, 255), "cyan": (0, 255, 255),
       "white": (255, 255, 255), "orange": (255, 165, 0), "purple": (128, 0, 128),
       "brown": (139, 69, 19), "pink": (255, 192, 203), "gray": (128, 128, 128)}


def png(color, size=112):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (size, size), RGB[color]).save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def animated_gif(first="red", second="blue", size=112):
    """Palette-mode animation; frame zero is `first`. Pre-fix this was a 400."""
    from PIL import Image
    f0 = Image.new("P", (size, size))
    pal = []
    for c in (first, second):
        pal += list(RGB[c])
    f0.putpalette(pal + [0] * (768 - len(pal)))
    f0.paste(0, (0, 0, size, size))
    f1 = f0.copy()
    f1.paste(1, (0, 0, size, size))
    b = io.BytesIO()
    f0.save(b, "GIF", save_all=True, append_images=[f1], duration=200, loop=0)
    return "data:image/gif;base64," + base64.b64encode(b.getvalue()).decode()


def post(messages, max_tokens=40):
    body = json.dumps({"model": MODEL, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"


def cached_of(resp):
    """v2.0.2 reports reuse as tensorfold.cached (known issue 15)."""
    u = resp.get("usage", {}) or {}
    tf = resp.get("tensorfold") or u.get("tensorfold") or {}
    if isinstance(tf, dict) and "cached" in tf:
        return tf["cached"]
    d = u.get("prompt_tokens_details") or {}
    return d.get("cached_tokens", "n/a")


def img_part(url):
    return {"type": "image_url", "image_url": {"url": url}}


results = []

# ---- check 1: GIF is accepted and frame zero is interpreted ----------------
print("=" * 62)
print("CHECK 1 — GIF frame-zero (pre-fix: HTTP 400)")
msgs = [{"role": "user", "content": [
    img_part(animated_gif("red", "blue")),
    {"type": "text", "text": "What single colour fills this image? Answer with one word."}]}]
resp, err = post(msgs)
if err:
    print("  FAIL", err)
    results.append(("gif-accepted", False))
else:
    ans = resp["choices"][0]["message"].get("content", "") or ""
    print(f"  HTTP 200; answer={ans.strip()[:60]!r}")
    results.append(("gif-accepted", True))
    # frame zero is red; the second frame is blue
    saw_red = "red" in ans.lower()
    print(f"  frame-zero interpreted as red: {saw_red}")
    results.append(("gif-frame-zero-red", saw_red))

# ---- check 2: rolling-image checkpoint reuse -------------------------------
# Emulate the client upstream describes: keep the newest 8 images, replace older
# image blocks with archive text. Reuse must be NONZERO once rotation begins.
print("=" * 62)
print("CHECK 2 — rolling-image resume (8 -> 9 -> 10 images)")
print("  upstream measured cached 0 -> 68 -> 174 (first is cold by design)")
KEEP = 8
history = []
row = []
for n in (8, 9, 10):
    history = []
    for i in range(n):
        keep = i >= n - KEEP
        color = COLORS[i]
        if keep:
            content = [img_part(png(color)),
                       {"type": "text", "text": f"Image {i + 1}."}]
        else:
            content = [{"type": "text",
                        "text": f"[archived image {i + 1}]"}]
        history.append({"role": "user", "content": content})
        history.append({"role": "assistant",
                        "content": f"Noted image {i + 1}."})
    history.append({"role": "user", "content":
                    "What colour was the most recent image? One word."})
    resp, err = post(history)
    if err:
        print(f"  {n} images: FAIL {err}")
        row.append((n, None, None))
        continue
    c = cached_of(resp)
    pt = resp.get("usage", {}).get("prompt_tokens")
    ans = (resp["choices"][0]["message"].get("content") or "").strip()
    expect = COLORS[n - 1]
    ok_colour = expect in ans.lower()
    print(f"  {n:2d} images: cached={c} prompt_tokens={pt} "
          f"answer={ans[:40]!r} expected={expect} match={ok_colour}")
    row.append((n, c, ok_colour))

nums = [c for _, c, _ in row if isinstance(c, int)]
rotated = [c for n, c, _ in row if isinstance(c, int) and n > 8]
reuse_ok = bool(rotated) and any(c > 0 for c in rotated)
print(f"  -> nonzero reuse after rotation: {reuse_ok} (rotated cached={rotated})")
results.append(("rolling-image-reuse", reuse_ok))
# Upstream's failure mode was a tool call instead of the colour.
colour_ok = all(ok for _, c, ok in row if ok is not None)
results.append(("rolling-image-answers-colour", colour_ok))

print("=" * 62)
for name, ok in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
print(f"V202 IMAGE CHECKS {sum(1 for _, o in results if o)}/{len(results)}")
