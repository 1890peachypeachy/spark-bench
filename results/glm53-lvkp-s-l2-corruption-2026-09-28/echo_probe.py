"""Verbatim-echo KV corruption probe.

Builds a long prefix of uniquely-identifiable records, then asks the lane to echo
a specific window back verbatim. Runs the SAME task at concurrency 1 and at
concurrency 8. If c1 echoes clean and c8 corrupts, the corruption is caused by
batching/prefix-cache reuse, not by model retrieval limits.
"""

import json, urllib.request, re, sys, threading, time

URL = "http://127.0.0.1:8888/v1/chat/completions"
MODEL = "GLM-5.3-Flash-EXL3"

NREC = 2600
# Record format is rigid and self-checking: index, a fixed token, and t=index*7.
RECORDS = [
    "REC%04d owner=worker-%02d retries=%d t=%ds" % (i, i % 37, i % 5, i * 7)
    for i in range(NREC)
]
PREFIX = "Dataset (one record per line):\n" + "\n".join(RECORDS) + "\n\n"

# Ask for windows at different depths in the prompt.
WINDOWS = [(200, 12), (630, 12), (1200, 12), (1800, 12), (2400, 12)]


def ask(start, n):
    task = (
        "Echo back, verbatim and with no commentary, records REC%04d through REC%04d "
        "exactly as they appear above. One per line. Do not reformat, do not fix "
        "anything, do not add text." % (start, start + n - 1)
    )
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PREFIX + task}],
        "temperature": 0.0,
        "max_tokens": 900,
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    d = json.load(urllib.request.urlopen(req, timeout=2400))
    return d["choices"][0]["message"].get("content") or ""


def score(start, n, text):
    """Return (n_correct, n_expected, list of mismatches)."""
    got = {}
    for line in text.splitlines():
        m = re.search(r"(REC\d{4})\s+owner=worker-(\d+)\s+retries=(\d+)\s+t=(\d+)s", line)
        if m:
            got[m.group(1)] = (m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    bad = []
    ok = 0
    for i in range(start, start + n):
        key = "REC%04d" % i
        exp = (key, i % 37, i % 5, i * 7)
        if key not in got:
            bad.append((key, "MISSING", ""))
        elif got[key] != exp:
            bad.append((key, "exp=%s" % (exp,), "got=%s" % (got[key],)))
        else:
            ok += 1
    return ok, n, bad


def arm(label, concurrency):
    out = []

    def work(start, n):
        try:
            t = ask(start, n)
            out.append((start, score(start, n, t)))
        except Exception as e:
            out.append((start, ("ERR", repr(e)[:90], [])))

    if concurrency == 1:
        for start, n in WINDOWS:
            work(start, n)
    else:
        # Fire all windows concurrently, padded to `concurrency` by repeating.
        jobs = (WINDOWS * ((concurrency // len(WINDOWS)) + 1))[:concurrency]
        ths = [threading.Thread(target=work, args=(s, n)) for s, n in jobs]
        for t in ths:
            t.start()
        for t in ths:
            t.join()

    print("\n===== ARM %s (concurrency=%d) =====" % (label, concurrency))
    tot_ok = tot_exp = 0
    for start, res in sorted(out, key=lambda x: x[0]):
        if res[0] == "ERR":
            print("  REC%04d..: ERROR %s" % (start, res[1]))
            continue
        ok, exp, bad = res
        tot_ok += ok
        tot_exp += exp
        print("  REC%04d..: %d/%d exact" % (start, ok, exp))
        for b in bad[:6]:
            print("      MISMATCH %s %s %s" % b)
    print("  ARM TOTAL: %d/%d exact" % (tot_ok, tot_exp))
    sys.stdout.flush()
    return tot_ok, tot_exp


t0 = time.time()
a1 = arm("SEQUENTIAL", 1)
a8 = arm("CONCURRENT", 8)
print(
    "\n=== VERDICT ===\nsequential %d/%d   concurrent %d/%d   (%.0fs)"
    % (a1[0], a1[1], a8[0], a8[1], time.time() - t0)
)
