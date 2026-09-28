import json, urllib.request, re, sys, threading, time

URL = "http://127.0.0.1:8888/v1/chat/completions"


def make_prefix(salt):
    lines = []
    for i in range(2600):
        lines.append(
            "Job %d status=dead queue=autopilot lock_owner=worker-%d retries=%d "
            "note=heartbeat missed at t=%ds; lease lock held then released. salt=%s"
            % (34000 + i, i % 37, i % 5, i * 7, salt)
        )
    return "Here is a minion_jobs dump:\n" + "\n".join(lines) + "\n\n"


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


def longest_repeat(t):
    toks = re.findall(r"\w+|\S", t)
    mx = cur = 1
    span = ""
    for a, b in zip(toks, toks[1:]):
        cur = cur + 1 if a == b else 1
        if cur > mx:
            mx = cur
            span = a
    return mx, span


def run_round(arm, rnd, results):
    def worker(idx, task, prefix):
        body = {
            "model": "GLM-5.3-Flash-EXL3",
            "messages": [{"role": "user", "content": prefix + task}],
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
            t = d["choices"][0]["message"].get("content") or ""
            mx, span = longest_repeat(t)
            results.append((arm, rnd, idx, mx, span))
        except Exception as e:
            results.append((arm, rnd, idx, -1, repr(e)[:80]))

    if arm == "shared":
        prefixes = [make_prefix("S")] * len(TASKS)
    else:
        prefixes = [make_prefix("U%d-%d" % (rnd, i)) for i in range(len(TASKS))]

    ths = [
        threading.Thread(target=worker, args=(i, t, prefixes[i]))
        for i, t in enumerate(TASKS)
    ]
    for t in ths:
        t.start()
    for t in ths:
        t.join()


results = []
for rnd in range(3):
    for arm in ("shared", "unique"):
        t0 = time.time()
        run_round(arm, rnd, results)
        print("done arm=%s round=%d in %.0fs" % (arm, rnd, time.time() - t0))
        sys.stdout.flush()

print("\n=== RAW ===")
for r in results:
    flag = " <<<< DEGENERATE" if r[3] >= 8 else (" ERR" if r[3] == -1 else "")
    print("arm=%-6s rnd=%d req%d max_repeat=%s span=%r%s" % (r[0], r[1], r[2], r[3], r[4], flag))

print("\n=== SUMMARY ===")
for arm in ("shared", "unique"):
    rs = [r for r in results if r[0] == arm]
    bad = [r for r in rs if r[3] >= 8]
    err = [r for r in rs if r[3] == -1]
    print("%s: degenerate %d/%d  errors %d" % (arm, len(bad), len(rs), len(err)))
