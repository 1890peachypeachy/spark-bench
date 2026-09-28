import json, urllib.request, re, sys, threading

URL = "http://127.0.0.1:8888/v1/chat/completions"

# Shared long prefix -> high prefix-cache hit, like a real agent loop.
PREFIX_LINES = []
for i in range(2600):
    PREFIX_LINES.append(
        "Job %d status=dead queue=autopilot lock_owner=worker-%d retries=%d "
        "note=heartbeat missed at t=%ds; lease lock held then released."
        % (34000 + i, i % 37, i % 5, i * 7)
    )
PREFIX = "Here is a minion_jobs dump:\n" + "\n".join(PREFIX_LINES) + "\n\n"

TASKS = [
    "Triage this. List the 5 dead autopilot jobs with IDs and a one-line reason each.",
    "Summarise the lock_owner distribution and name the top 3 offenders.",
    "Write a 10-bullet incident timeline from this dump.",
    "List every distinct retries value and how many jobs have it.",
    "Draft a short alert message describing the failure mode.",
    "Explain in 8 bullets why the heartbeats are missing.",
    "Produce a markdown table of 12 representative jobs.",
    "Give a numbered remediation plan with 10 steps.",
]

results = {}


def longest_repeat(t):
    toks = re.findall(r"\w+|\S", t)
    mx = cur = 1
    for a, b in zip(toks, toks[1:]):
        cur = cur + 1 if a == b else 1
        if cur > mx:
            mx = cur
    return mx


def worker(idx, task):
    body = {
        "model": "GLM-5.3-Flash-EXL3",
        "messages": [{"role": "user", "content": PREFIX + task}],
        "temperature": 0.8,
        "top_p": 0.95,
        "max_tokens": 1200,
    }
    try:
        req = urllib.request.Request(
            URL,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        d = json.load(urllib.request.urlopen(req, timeout=2400))
        c = d["choices"][0]
        t = c["message"].get("content") or ""
        results[idx] = (
            d["usage"]["prompt_tokens"],
            d["usage"]["completion_tokens"],
            c["finish_reason"],
            longest_repeat(t),
            t[-200:],
        )
    except Exception as e:
        results[idx] = ("ERR", repr(e), "", 0, "")


ths = [threading.Thread(target=worker, args=(i, t)) for i, t in enumerate(TASKS)]
for t in ths:
    t.start()
for t in ths:
    t.join()

bad = 0
for i in sorted(results):
    r = results[i]
    flag = "  <<<< DEGENERATE" if isinstance(r[3], int) and r[3] >= 8 else ""
    if flag:
        bad += 1
    print("req%d prompt=%s completion=%s finish=%s MAX_REPEAT=%s%s" % (i, r[0], r[1], r[2], r[3], flag))
    print("   tail:", repr(r[4]))
    sys.stdout.flush()
print("\nDEGENERATE_REQUESTS=%d/%d" % (bad, len(TASKS)))
