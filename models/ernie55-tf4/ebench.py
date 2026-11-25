"""Tiny bench helper for the ERNIE TensorFold lane (spark3 :8888)."""
import json, time, random, urllib.request, concurrent.futures as cf

U = "http://100.99.120.29:8888/v1/chat/completions"
M = "GLM-5.3-Flash-EXL3"
NT = {"chat_template_kwargs": {"enable_thinking": False}}
WORDS = ["alpha", "river", "stone", "cloud", "ember", "maple", "orbit", "quartz", "delta", "fable"]


def call(msgs, mt=512, extra=None, to=900):
    b = {"model": M, "messages": msgs, "max_tokens": mt}
    if extra:
        b.update(extra)
    t = time.time()
    r = urllib.request.Request(U, json.dumps(b).encode(), {"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(r, timeout=to))
        return time.time() - t, d, None
    except Exception as e:
        return time.time() - t, None, str(e)[:300]


def filler(n, seed=1):
    random.seed(seed)
    return " ".join(random.choice(WORDS) for _ in range(n))


def decode(prompt, mt=400):
    dt, d, e = call([{"role": "user", "content": prompt}], mt, dict(NT, temperature=0))
    if e:
        return {"err": e}
    n = d["usage"]["completion_tokens"]
    return {"tok": n, "s": round(dt, 2), "tok_s": round(n / dt, 1)}


def prefill(nwords, seed=3):
    doc = filler(nwords, seed)
    mid = len(doc) // 2
    doc = doc[:mid] + " The secret code is COBALT-FALCON-94721. " + doc[mid:]
    dt, d, e = call([{"role": "user", "content": doc + "\n\nWhat is the secret code? Reply with the code only."}], 40, NT)
    if e:
        return {"err": e}
    p = d["usage"]["prompt_tokens"]
    return {"prompt": p, "s": round(dt, 2), "pf_tok_s": round(p / dt), "ok": "COBALT-FALCON-94721" in (d["choices"][0]["message"]["content"] or "")}


TOPICS = ["volcanoes", "bees", "trains", "glaciers", "owls", "deserts", "comets", "coral"]


def conc(n, mt=300):
    def one(i):
        return call([{"role": "user", "content": f"Write a 250-word paragraph about {TOPICS[i % 8]}."}], mt, NT)
    t = time.time()
    with cf.ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(one, range(n)))
    wall = time.time() - t
    toks = sum(r[1]["usage"]["completion_tokens"] for r in rs if r[1])
    return {"c": n, "wall": round(wall, 1), "ok": sum(1 for r in rs if r[1]), "agg_tok_s": round(toks / wall, 1),
            "errs": [r[2] for r in rs if r[2]][:2]}


PROSE = "Write a 300-word story about a lighthouse keeper."
CODE = "Write a Python function that parses an ISO-8601 date string without using datetime, with tests."
