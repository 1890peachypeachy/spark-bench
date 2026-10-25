#!/usr/bin/env python3
"""Submit the SAME song graph to ALL FOUR ComfyUI instances at the same instant.

Answers the question "can we run multiple renderings at once" with evidence:
  - all four must accept the prompt and reach a finished artifact
  - TP4 decode is sampled throughout, so we learn what simultaneous creative load
    costs the serving lane (one render at a time cost 29-154 tok/s; four at once
    is the untested case)
  - per-node memory floor is recorded, because the guard kills ComfyUI under 4 GB
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

STYLE = ("90s grunge rock, detuned distorted guitars, raw garage drum sound, "
         "sludgy bass, angsty shouted male vocal with harmonies on the chorus, "
         "lo-fi, aggressive, 118 BPM, in 4/4, driving backbeat")

LYRICS = """[Verse]
The printer says it needs more ink
I know exactly what it means
I bought the cartridge, three of them
It still will not print again

[Chorus]
Paper jam, paper jam
Nothing ever goes to plan
Paper jam, paper jam
I am doing all I can

[Verse]
The tray is full, the light is green
The truest lie I have ever seen
It pulls the sheet and eats it whole
The printer has a hungry soul

[Chorus]
Paper jam, paper jam
Nothing ever goes to plan
Paper jam, paper jam
I am doing all I can

[Outro]
Just print
Please print"""


def post(url, obj, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.load(f)


def get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as f:
        return json.loads(f.read())


def build(tag):
    wf = json.load(open(f"{SKILL}/templates/text_to_music_workflow_api.json"))
    ins = wf["2"]["inputs"]
    ins["style"] = STYLE
    ins["lyrics"] = LYRICS
    ins["seed"] = 777001
    ins["mode"] = "full"
    ins["max_duration"] = 240.0
    ins["cfg_scale"] = 1.5
    wf["5"]["inputs"]["seed"] = 777001
    wf["7"]["inputs"]["filename_prefix"] = f"audio/fourway_{tag}"
    return wf


def tp4_probe(label):
    body = {"model": "GLM-5.3-Flash-EXL3", "max_tokens": 120, "temperature": 0,
            "messages": [{"role": "user", "content": "Count from 1 to 60, one number per line."}]}
    t0 = time.time()
    try:
        d = post(TP4, body, timeout=300)
        secs = round(time.time() - t0, 2)
        ct = d.get("usage", {}).get("completion_tokens", 0)
        tps = round(ct / secs, 1) if ct else None
        print(f"    TP4[{label}]: {secs}s {ct} tok {tps} tok/s")
        return {"label": label, "secs": secs, "tok_per_s": tps}
    except Exception as e:
        print(f"    TP4[{label}]: FAILED {e}")
        return {"label": label, "error": str(e)}


def memfree(base):
    try:
        s = get_json(f"{base}/system_stats", 10)
        return round(s["system"]["ram_free"] / 1e9, 1)
    except Exception:
        return None


def main():
    out = {"style": STYLE, "submitted": {}, "measurements": [], "results": {}}
    print("== 0. all four reachable?")
    for n, b in NODES.items():
        print(f"    {n}: ram_free={memfree(b)} GB")

    out["measurements"].append(tp4_probe("baseline"))

    print("== 1. submit to ALL FOUR at the same instant")
    pids = {}
    for n, b in NODES.items():
        try:
            r = post(f"{b}/prompt", {"prompt": build(n), "client_id": f"fourway-{n}"})
            pids[n] = r.get("prompt_id")
            print(f"    {n}: queued {pids[n]}")
        except Exception as e:
            print(f"    {n}: SUBMIT FAILED {e}")
            pids[n] = None
    out["submitted"] = pids

    print("== 2. sample TP4 while all four render")
    pending = {n: p for n, p in pids.items() if p}
    deadline = time.time() + 1800
    sample = 0
    while pending and time.time() < deadline:
        time.sleep(25)
        sample += 1
        out["measurements"].append(tp4_probe(f"during4-{sample}"))
        for n in list(pending):
            try:
                h = get_json(f"{NODES[n]}/history/{pending[n]}", 20)
                if h.get(pending[n]):
                    print(f"    {n}: finished")
                    out["results"][n] = h[pending[n]]
                    del pending[n]
            except Exception:
                pass
    if pending:
        print("    TIMEOUT waiting on:", list(pending))

    out["measurements"].append(tp4_probe("after"))
    print("== 3. memory after")
    for n, b in NODES.items():
        print(f"    {n}: ram_free={memfree(b)} GB")

    print("== 4. artifacts")
    for n in NODES:
        entry = out["results"].get(n) or {}
        status = (entry.get("status") or {}).get("status_str")
        files = []
        for _, node_out in (entry.get("outputs") or {}).items():
            for _, val in node_out.items():
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and "filename" in item:
                            files.append(item["filename"])
        print(f"    {n}: status={status} files={files}")

    json.dump(out, open("/tmp/fourway.json", "w"), indent=1)
    print("saved /tmp/fourway.json")


if __name__ == "__main__":
    main()
