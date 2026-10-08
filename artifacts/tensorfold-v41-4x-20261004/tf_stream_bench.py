"""Streamed single-request TensorFold measurement on exact prompt token IDs (the SGLang bench's twin).

Same cases file as dsv41_sglang_stream_bench.py ({name: prompt_ids}); sends the ids to TensorFold's
/v1/completions (``prompt`` as a token list: no chat template, like SGLang's /generate), greedy, max_tokens N,
streamed. Reports TTFT (first content chunk) and the decode rate between the first and last content chunks:
(completion_tokens - 1) / (t_last - t_first), plus the engine's own per-request stats. Standard library only.
"""
import argparse
import json
import time
import urllib.request


def stream(url, ids, max_new, model):
    body = json.dumps(dict(model=model, prompt=ids, stream=True, temperature=0, max_tokens=max_new,
                           stream_options=dict(include_usage=True))).encode()
    req = urllib.request.Request(url + "/v1/completions", data=body, headers={"Content-Type": "application/json"})
    began = time.perf_counter()
    marks, text, end = [], "", {}
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            ev = json.loads(line[5:])
            if "error" in ev:
                raise RuntimeError(ev["error"])
            ch = (ev.get("choices") or [{}])[0]
            piece = ch.get("text") or (ch.get("delta") or {}).get("content") or ""
            if piece:
                marks.append(time.perf_counter() - began)
                text += piece
            if ev.get("usage") or ev.get("tensorfold"):
                end = ev
    return marks, text, end


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8001")
    p.add_argument("--model", default="deepseek-v4.1-flash")
    p.add_argument("--cases", required=True)
    p.add_argument("--max-new", type=int, default=256)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--only", default="")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    cases = json.load(open(a.cases))
    if a.only:
        cases = {k: v for k, v in cases.items() if k in a.only.split(",")}
    results = []
    for name, ids in cases.items():
        for rep in range(a.reps):
            marks, text, end = stream(a.url, ids, a.max_new, a.model)
            n = int((end.get("usage") or {}).get("completion_tokens") or 0)
            rate = (n - 1) / (marks[-1] - marks[0]) if len(marks) > 1 and marks[-1] > marks[0] else None
            results.append(dict(case=name, rep=rep, prompt_tokens=len(ids), completion_tokens=n,
                                ttft_s=marks[0] if marks else None, decode_tok_s=rate,
                                total_s=marks[-1] if marks else None, text=text, engine=end.get("tensorfold"),
                                finish=((end.get("choices") or [{}])[0]).get("finish_reason")))
            print(json.dumps({k: v for k, v in results[-1].items() if k not in ("text", "engine")}), flush=True)
    json.dump(results, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
