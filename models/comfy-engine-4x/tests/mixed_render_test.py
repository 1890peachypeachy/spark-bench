#!/usr/bin/env python3
"""Four DIFFERENT workloads on four nodes at the same instant: video, image, song, design.

The earlier four-way test sent the SAME song graph to all four nodes. That proves
throughput but not isolation: every node loaded the identical model set, so any
cross-node model conflict would be invisible. This sends a different model stack to
each node -- 20 GB video DiT + audio VAE, a 7 GB image DiT, YuE2 music, and Ming-Image
with its 19 GB text encoder -- so shared-resource collisions have somewhere to show up.

Also samples TP4 decode throughout, because the serving lane is what pays for this.
"""
import json, os, time, urllib.request

NODES = {
    "spark1": "http://100.106.81.35:8188",
    "spark2": "http://100.71.248.116:8188",
    "spark3": "http://100.99.120.29:8188",
    "spark4": "http://100.91.114.22:8188",
}
TP4 = "http://100.99.120.29:8888/v1/chat/completions"
SKILL = os.path.expanduser("~/.hermes/skills/creative/yue2-music")
SEED = 902101

# --- graph builders -------------------------------------------------------------
QWEN_TURBO = "qwen_image_2.1_turbo_int8_convrot.safetensors"
QWEN_CLIP = "qwen3vl_8b_int8_convrot.safetensors"
QWEN_VAE = "qwen_image_2.1_vae_bf16.safetensors"
QWEN_SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"
H3_UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
H3_CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
H3_VVAE = "minimax_h3_video_vae_fp16.safetensors"
H3_AVAE = "minimax_h3_audio_vae_fp32.safetensors"
MING_UNET = "ming_image_0.1_design_int8_convrot.safetensors"
MING_TE = "ming_image_0.1_ling_mini_2.0_int8_convrot.safetensors"
MING_VAE = "ming_image_vae_bf16.safetensors"


def graph_image():
    """Qwen-Image-2.1 turbo text-to-image, 1328 square."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN_TURBO, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN_CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text":
             "A serene peach orchard at golden hour, loose watercolor, warm light, "
             "a mother and toddler walking between the trees, soft grain"}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1328, "height": 1328, "batch_size": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "studio/MIX_IMG"}},
        "11": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "12": {"class_type": "ManualSigmas", "inputs": {"sigmas": QWEN_SIGMAS}},
        "13": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "14": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
        "8": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["14", 0], "guider": ["11", 0],
                                                                 "sampler": ["13", 0], "sigmas": ["12", 0],
                                                                 "latent_image": ["6", 0]}},
    }


def graph_video():
    """MiniMax H3 text-to-video with audio, 2.3 s."""
    return {
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": H3_UNET, "weight_dtype": "default"}},
        "13": {"class_type": "CLIPLoader", "inputs": {"clip_name": H3_CLIP, "type": "minimax", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": H3_VVAE}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": H3_AVAE}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0],
                                                                  "prompt": "A single peach rolling slowly across "
                                                                            "a pale linen tablecloth, soft window "
                                                                            "light, shallow depth of field, quiet "
                                                                            "and still",
                                                                  "width": 960, "height": 544, "length": 56}},
        "16": {"class_type": "BasicGuider", "inputs": {"model": ["6", 0], "conditioning": ["104", 0]}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["6", 0], "scheduler": "simple", "steps": 20,
                                                          "denoise": 1.0}},
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["15", 0], "guider": ["16", 0],
                                                                 "sampler": ["17", 0], "sigmas": ["9", 0],
                                                                 "latent_image": ["104", 1]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["11", 0]}},
        "23": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["24", 0]}},
        "91": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "audio": ["23", 0], "fps": 24.0}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["91", 0], "filename_prefix": "studio/MIX_VID",
                                                      "format": "auto", "codec": "auto"}},
    }


def graph_design():
    """Ming-Image-0.1 design, text-to-image via its edit encoder with no references."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MING_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": MING_TE, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": MING_VAE}},
        "4": {"class_type": "TextEncodeMingImageEdit", "inputs": {"clip": ["2", 0], "vae": ["3", 0],
                                                                   "prompt": "Editorial poster: soft peach and sage "
                                                                             "palette, clean geometric grid, generous "
                                                                             "negative space, hand-drawn peach motif "
                                                                             "lower third, flat vector, no text",
                                                                   "images": {}}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["4", 0],
                                                   "latent_image": ["5", 0], "seed": SEED, "steps": 20, "cfg": 1.0,
                                                   "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "studio/MIX_DSGN"}},
    }


def graph_song():
    wf = json.load(open(f"{SKILL}/templates/text_to_music_workflow_api.json"))
    ins = wf["2"]["inputs"]
    ins["style"] = ("dream pop, shimmering chorused guitars, soft analog synth pads, "
                    "breathy female vocal, slow tempo, hazy and warm, 82 BPM, in 4/4")
    ins["lyrics"] = ("[Verse]\nThe kettle sings a quiet song\n"
                     "The morning takes its time\n\n"
                     "[Chorus]\nSlow down, slow down\n"
                     "Everything is fine\n\n"
                     "[Verse]\nPeach light on the kitchen wall\n"
                     "Nothing here to find\n\n"
                     "[Chorus]\nSlow down, slow down\n"
                     "Everything is fine")
    ins["seed"] = SEED
    ins["mode"] = "full"
    ins["max_duration"] = 180.0
    ins["cfg_scale"] = 1.5
    wf["5"]["inputs"]["seed"] = SEED
    wf["7"]["inputs"]["filename_prefix"] = "audio/MIX_SONG"
    return wf


PLAN = {
    "spark1": ("video", graph_video),
    "spark2": ("image", graph_image),
    "spark3": ("song", graph_song),
    "spark4": ("design", graph_design),
}


def post(url, obj, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.load(f)


def get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as f:
        return json.loads(f.read())


def tp4(label):
    body = {"model": "GLM-5.3-Flash-EXL3", "max_tokens": 120, "temperature": 0,
            "messages": [{"role": "user", "content": "Count from 1 to 60, one number per line."}]}
    t0 = time.time()
    try:
        d = post(TP4, body, timeout=300)
        s = round(time.time() - t0, 2)
        ct = d.get("usage", {}).get("completion_tokens", 0)
        print(f"    TP4[{label}]: {s}s {ct} tok {round(ct/s,1) if ct else None} tok/s")
        return {"label": label, "secs": s, "tps": round(ct / s, 1) if ct else None}
    except Exception as e:
        print(f"    TP4[{label}]: FAILED {e}")
        return {"label": label, "error": str(e)}


def mem(b):
    try:
        return round(get(f"{b}/system_stats", 10)["system"]["ram_free"] / 1e9, 1)
    except Exception:
        return None


def main():
    out = {"plan": {n: v[0] for n, v in PLAN.items()}, "pids": {}, "meas": [], "results": {}}
    print("== 0. reachability + free RAM")
    for n, b in NODES.items():
        print(f"    {n} [{PLAN[n][0]}]: ram_free={mem(b)} GB")

    out["meas"].append(tp4("baseline"))

    print("== 1. submit four DIFFERENT graphs simultaneously")
    pids = {}
    for n, b in NODES.items():
        kind, fn = PLAN[n]
        try:
            r = post(f"{b}/prompt", {"prompt": fn(), "client_id": f"mix-{n}"})
            pids[n] = r.get("prompt_id")
            print(f"    {n} <- {kind}: {pids[n]}")
        except urllib.error.HTTPError as e:
            print(f"    {n} <- {kind}: REJECTED {e.read().decode()[:300]}")
            pids[n] = None
        except Exception as e:
            print(f"    {n} <- {kind}: FAILED {e}")
            pids[n] = None
    out["pids"] = pids

    print("== 2. sample TP4 while all four work")
    pending = {n: p for n, p in pids.items() if p}
    deadline, i = time.time() + 2400, 0
    while pending and time.time() < deadline:
        time.sleep(20)
        i += 1
        out["meas"].append(tp4(f"during-{i}"))
        for n in list(pending):
            try:
                h = get(f"{NODES[n]}/history/{pending[n]}", 20)
                if h.get(pending[n]):
                    print(f"    {n} [{PLAN[n][0]}]: finished")
                    out["results"][n] = h[pending[n]]
                    del pending[n]
            except Exception:
                pass
    if pending:
        print("    TIMEOUT:", {n: PLAN[n][0] for n in pending})

    out["meas"].append(tp4("after"))
    print("== 3. free RAM after")
    for n, b in NODES.items():
        print(f"    {n}: ram_free={mem(b)} GB")

    print("== 4. outcomes")
    for n in NODES:
        e = out["results"].get(n) or {}
        st = (e.get("status") or {}).get("status_str")
        msgs = (e.get("status") or {}).get("messages") or []
        err = [m for m in msgs if m[0] == "execution_error"]
        fl = []
        for _, no in (e.get("outputs") or {}).items():
            for _, v in no.items():
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict) and "filename" in it:
                            fl.append(it["filename"])
        print(f"    {n} [{PLAN[n][0]}]: status={st} files={fl}")
        if err:
            print("      ERROR:", json.dumps(err[0][1])[:400])

    print("== 5. wall clock per job")
    for n, e in out["results"].items():
        msgs = (e.get("status") or {}).get("messages") or []
        a = b = None
        for name, p in msgs:
            if name == "execution_start":
                a = p.get("timestamp")
            if name == "execution_success":
                b = p.get("timestamp")
        if a and b:
            print(f"    {n} [{PLAN[n][0]}]: {round((b-a)/1000,1)}s")

    json.dump(out, open("/tmp/mixed.json", "w"), indent=1)
    print("saved /tmp/mixed.json")


if __name__ == "__main__":
    main()
