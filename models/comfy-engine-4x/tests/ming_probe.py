#!/usr/bin/env python3
"""Probe: can Ming-Image-0.1 design do text-to-image on this ComfyUI build?

Ming has no recipe graph in the Studios repo -- only the vendor's edit workflow -- and
its text encoder is auto-detected from the checkpoint (MING_IMAGE), so the clip_type is
not the thing that decides it. This walks the graph in cheap stages so a wrong guess
fails on the stage it is wrong at instead of timing out on a full sample.
"""
import json, sys, time, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8188"
UNET = "ming_image_0.1_design_int8_convrot.safetensors"
TE = "ming_image_0.1_ling_mini_2.0_int8_convrot.safetensors"
VAE = "ming_image_vae_bf16.safetensors"

PROMPT = ("Editorial poster design for a parenting blog: soft peach and sage palette, "
          "clean geometric grid, generous negative space, a hand-drawn peach motif "
          "in the lower third, no text")


def post(path, obj, timeout=120):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.load(f)


def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as f:
        return json.loads(f.read())


def run(graph, label, wait=600):
    t0 = time.time()
    try:
        r = post("/prompt", {"prompt": graph, "client_id": "mingprobe"})
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:600]
        print(f"  {label}: REJECTED {e.code} {body}")
        return None
    pid = r.get("prompt_id")
    while time.time() - t0 < wait:
        h = get(f"/history/{pid}")
        if h.get(pid):
            e = h[pid]
            st = (e.get("status") or {}).get("status_str")
            msgs = (e.get("status") or {}).get("messages") or []
            err = [m for m in msgs if m[0] == "execution_error"]
            print(f"  {label}: {st} in {time.time()-t0:.1f}s")
            if err:
                print("   ERROR:", json.dumps(err[0][1])[:500])
            return e
        time.sleep(3)
    print(f"  {label}: TIMEOUT")
    return None


def files(entry):
    out = []
    for _, node_out in (entry.get("outputs") or {}).items():
        for _, val in node_out.items():
            if isinstance(val, list):
                for i in val:
                    if isinstance(i, dict) and "filename" in i:
                        out.append(i["filename"])
    return out


print(f"== probe {BASE}")
print("== stage 1: load unet + ming text encoder, empty prompt")
g = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TE, "type": "qwen_image", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
    "4": {"class_type": "TextEncodeMingImageEdit", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": PROMPT, "images": {}}},
    "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "6": {"class_type": "PreviewImage", "inputs": {"images": ["7", 0]}},
    "7": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
    "8": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["4", 0],
                                               "latent_image": ["5", 0], "seed": 771001, "steps": 20, "cfg": 1.0,
                                               "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
}
e = run(g, "ming t2i 1024")
if e:
    print("  files:", files(e))

print("== stage 2: same but with a real SaveImage")
g["9"] = {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "studio/MING"}}
e = run(g, "ming t2i saved")
if e:
    print("  files:", files(e))
