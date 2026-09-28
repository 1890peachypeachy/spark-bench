import json, urllib.request, sys, re

URL = "http://127.0.0.1:8888/v1/chat/completions"


def run(ntok, label, temp=0.8):
    filler = []
    for i in range(ntok // 12):
        filler.append(
            "Job %d status=dead queue=autopilot lock_owner=worker-%d retries=%d "
            "note=heartbeat missed at t=%ds; lease lock held then released."
            % (34000 + i, i % 37, i % 5, i * 7)
        )
    prompt = (
        "Here is a minion_jobs dump:\n"
        + "\n".join(filler)
        + "\n\nTriage this. List the 5 dead autopilot jobs with IDs and a one-line "
        "reason each, then state whether action is needed."
    )
    body = {
        "model": "GLM-5.3-Flash-EXL3",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temp,
        "top_p": 0.95,
        "max_tokens": 900,
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    d = json.load(urllib.request.urlopen(req, timeout=1800))
    c = d["choices"][0]
    t = c["message"].get("content") or ""
    pt = d["usage"]["prompt_tokens"]
    ct = d["usage"]["completion_tokens"]
    toks = re.findall(r"\w+|\S", t)
    mx = cur = 1
    for a, b in zip(toks, toks[1:]):
        cur = cur + 1 if a == b else 1
        if cur > mx:
            mx = cur
    print(
        "[%s] prompt_tok=%d completion_tok=%d finish=%s MAX_CONSEC_REPEAT=%d"
        % (label, pt, ct, c["finish_reason"], mx)
    )
    print("   tail:", repr(t[-220:]))
    sys.stdout.flush()


for n, l in [(8000, "~8K"), (30000, "~30K"), (70000, "~70K")]:
    try:
        run(n, l)
    except Exception as e:
        print(l, "ERR", repr(e))
        sys.stdout.flush()
