import json, os, re, shutil, urllib.request

T = "/usr/local/lib/python3.12/dist-packages/comfyui_workflow_templates_json/templates"
DEST = "/opt/ComfyUI/user/default/workflows/Creation Lane"

M = {
    "1 - Music (YuE2)": [
        ("audio_yue2_text2music", "YuE2 - Text to Music"),
        ("audio_yue2_music_cover", "YuE2 - Music Cover"),
    ],
    "2 - Image (Qwen-Image 2.1)": [
        ("image_qwen_image_2_1_t2i", "Qwen-Image 2.1 - Text to Image"),
        ("image_qwen_image_2_1_image_edit", "Qwen-Image 2.1 - Image Edit"),
        ("image_qwen_image_2_1_background_removal", "Qwen-Image 2.1 - Background Removal"),
    ],
    "3 - Design (Ming)": [
        ("image_ming_image_01_design_t2i", "Ming Design - Text to Image"),
        ("image_ming_image_01_design_image_edit", "Ming Design - Image Edit"),
    ],
    "4 - Video (MiniMax H3)": [
        ("video_fastvideo_fasth3_t2v", "FastH3 Turbo - Text to Video"),
        ("video_fastvideo_fasth3_i2v", "FastH3 Turbo - Image to Video"),
        ("video_minimax_h3_t2v", "H3 - Text to Video"),
        ("video_minimax_h3_i2v", "H3 - Image to Video"),
        ("video_minimax_h3_r2v", "H3 - Reference to Video"),
        ("video_minimax_h3_i2v_continuation", "H3 - I2V Continuation"),
        ("video_minimax_h3_multiframe_reference", "H3 - Multiframe Reference"),
        ("video_minimax_h3_fun_controlnet_union", "H3 - Fun ControlNet Union"),
    ],
}

oi = json.load(urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=120))
have = set()
for node, fld in [
    ("UNETLoader", "unet_name"), ("CLIPLoader", "clip_name"), ("VAELoader", "vae_name"),
    ("CheckpointLoaderSimple", "ckpt_name"), ("LoraLoaderModelOnly", "lora_name"),
    ("LoraLoader", "lora_name"), ("AudioEncoderLoader", "audio_encoder_name"),
    ("ModelPatchLoader", "name"), ("CLIPVisionLoader", "clip_name"),
]:
    try:
        spec = oi[node]["input"]["required"][fld]
        first = spec[0]
        if isinstance(first, list):          # classic COMBO: [[opt, ...], {...}]
            have.update(first)
        elif first == "COMBO":               # new COMBO: ["COMBO", {"options": [...]}]
            have.update(spec[1].get("options", []))
    except Exception:
        pass
have_base = {os.path.basename(h) for h in have}


def refs(o, acc):
    if isinstance(o, dict):
        for v in o.values():
            refs(v, acc)
    elif isinstance(o, list):
        for v in o:
            refs(v, acc)
    elif isinstance(o, str) and re.search(r"\.(safetensors|sft|gguf|pt)$", o):
        acc.add(o)
    return acc


os.makedirs(DEST, exist_ok=True)
tot = 0
report = []
for folder, items in M.items():
    os.makedirs(os.path.join(DEST, folder), exist_ok=True)
    for src, nice in items:
        sp = os.path.join(T, src + ".json")
        if not os.path.exists(sp):
            report.append((folder, nice, "MISSING TEMPLATE", []))
            continue
        shutil.copy2(sp, os.path.join(DEST, folder, nice + ".json"))
        tot += 1
        d = json.load(open(sp))
        need = refs(d, set())
        missing = sorted(n for n in need if os.path.basename(n) not in have_base)
        report.append((folder, nice, "ok", missing))

print("copied %d workflows -> %s\n" % (tot, DEST))
cur = None
for folder, nice, status, missing in report:
    if folder != cur:
        print("## " + folder)
        cur = folder
    flag = "OK" if status == "ok" and not missing else ("!!" if missing else "ERR")
    print("  [%s] %s" % (flag, nice))
    for m in missing:
        print("        needs: %s" % m)
