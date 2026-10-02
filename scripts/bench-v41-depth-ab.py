#!/usr/bin/env python3
"""Matched V4.1 context-depth benchmark. Standard library; synthetic public prompts.

SSE timing is a decode-rate proxy, not exact token timestamps: speculative chunks
may carry multiple tokens. Cold TTFT is kept separate from warm repeats.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request

MODEL = 'deepseek-v4.1-flash'
DEPTHS = [1000, 20000, 40000, 80000, 160000]
TASKS = {
    'prose': 'Write a long, detailed essay explaining the history of lighthouses: ancient origins, the Fresnel lens, electrification, automation, maintenance and GPS redundancy. Use connected prose and concrete examples. Aim for at least 1500 words. Begin the essay immediately.',
    'code': 'Write a complete Python module implementing a thread-safe LRU cache with per-entry TTL, capacity eviction, an injectable clock, type hints, detailed docstrings, statistics, unit tests and ten usage examples. Return code only. Implement each part fully, without placeholders.',
}


def post(base, route, body, timeout=900):
    req = urllib.request.Request(base + route, json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if route == '/flush_cache':
            if not raw.startswith(b'Cache flushed.'):
                raise RuntimeError('Cache flush did not confirm success')
            return None
        return json.loads(raw)


def body_for(content):
    return {'model': MODEL, 'messages': [{'role': 'user', 'content': content}],
            'chat_template_kwargs': {'thinking': False, 'enable_thinking': False}}


def build(base, output):
    # Vary entries while keeping the corpus deterministic and reusable on both arms.
    topics = ['maintenance', 'shipping', 'training', 'fuel', 'weather', 'communications', 'inspection']
    corpus = ''.join(
        f'Record {i}: The coastal committee discussed {topics[i % len(topics)]} at station {i % 97}. '
        f'The monthly report listed {(i * 17) % 113 + 1} completed checks and {(i * 7) % 31} pending items. '
        'Staff documented the schedule, the equipment condition, the budget and the handover procedure. '
        'An independent reviewer compared the log with the previous report and requested clear explanations '
        'for any changes. The committee retained the original records for its next review.\n'
        for i in range(13000))
    fixtures = []
    for target in DEPTHS:
        for kind, task in TASKS.items():
            prefix = f'Benchmark reference archive, depth {target}, task {kind}. This is background material.\n<archive>\n'
            suffix = '\n</archive>\n\nTask: ' + task
            lo, hi, best = 0, len(corpus), None
            for _ in range(24):
                cut = (lo + hi) // 2
                body = body_for(prefix + corpus[:cut] + suffix)
                actual = post(base, '/v1/tokenize', body)['count']
                if best is None or abs(actual - target) < abs(best[0] - target):
                    best = (actual, body)
                if abs(actual - target) <= 1:
                    break
                if actual < target:
                    lo = cut + 1
                else:
                    hi = cut - 1
                if lo > hi:
                    break
            actual, body = best
            if abs(actual - target) > max(2, target * 0.001):
                raise ValueError(f'Could not calibrate {kind} to {target}: got {actual}')
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            fixtures.append(dict(target_tokens=target, kind=kind, tokenized_prompt_tokens=actual,
                                 request_sha256=digest, body=body))
            print(json.dumps({k: fixtures[-1][k] for k in ('target_tokens', 'kind', 'tokenized_prompt_tokens', 'request_sha256')}), flush=True)
    output.write_text(json.dumps(fixtures, indent=2) + '\n')


def idle(base):
    with urllib.request.urlopen(base + '/v1/loads', timeout=10) as r:
        loads = json.load(r).get('loads')
    if not loads:
        raise RuntimeError('Server returned no load state')
    return all(x.get('num_running_reqs', 0) == 0 and x.get('num_waiting_reqs', 0) == 0 for x in loads)


def wait_idle(base):
    for _ in range(90):
        if idle(base):
            return
        time.sleep(2)
    raise RuntimeError('Cluster did not become idle; benchmark not run')


def request(base, body, tokens):
    req_body = dict(body, max_tokens=tokens, temperature=0, seed=0, stream=True,
                    stream_options={'include_usage': True})
    req = urllib.request.Request(base + '/v1/chat/completions', json.dumps(req_body).encode(),
                                 {'Content-Type': 'application/json'})
    start = time.perf_counter()
    first = last = None
    usage = finish = None
    content, reasoning, events = [], [], []
    done = False
    with urllib.request.urlopen(req, timeout=900) as response:
        for raw in response:
            if not raw.startswith(b'data:'):
                continue
            data = raw[5:].strip()
            if data == b'[DONE]':
                done = True
                break
            chunk = json.loads(data)
            if 'error' in chunk:
                raise RuntimeError(str(chunk['error']))
            if chunk.get('usage'):
                usage = chunk['usage']
            for choice in chunk.get('choices', []):
                delta = choice.get('delta') or {}
                text = delta.get('content') or ''
                thought = delta.get('reasoning_content') or delta.get('reasoning') or ''
                if text or thought:
                    now = time.perf_counter()
                    first = first if first is not None else now
                    last = now
                    content.append(text)
                    reasoning.append(thought)
                    events.append([now - start, len(text), len(thought)])
                finish = choice.get('finish_reason') or finish
    end = time.perf_counter()
    if not done or not usage or first is None or last <= first or not finish:
        raise RuntimeError('Incomplete stream, missing usage, finish reason or timing span')
    n = usage['completion_tokens']
    if n < 256:
        raise RuntimeError(f'Only {n} completion tokens; cannot compare a short answer with the requested window')
    text, thought = ''.join(content), ''.join(reasoning)
    if thought:
        raise RuntimeError('Thinking was not disabled by the requested template settings')
    return dict(prompt_tokens=usage['prompt_tokens'], completion_tokens=n, usage=usage,
                ttft_s=first-start, decode_span_s=last-first, wall_s=end-start,
                decode_proxy_tps=(n-1)/(last-first), legacy_decode_proxy_tps=n/(last-first),
                request_tps=n/(end-start), finish_reason=finish,
                output_sha256=hashlib.sha256(text.encode()).hexdigest(), output=text, events=events)


def run(args):
    fixtures = json.loads(args.fixtures.read_text())
    if args.depths:
        selected = {int(x) for x in args.depths.split(',')}
        if not selected or not selected.issubset(set(DEPTHS)):
            raise ValueError('Unsupported depth filter')
        fixtures = [f for f in fixtures if f['target_tokens'] in selected]
    wait_idle(args.base)
    # Warm the small verify shapes; this row is explicitly not a measured trial.
    request(args.base, fixtures[0]['body'], args.tokens)
    for fixture in fixtures:
        wait_idle(args.base)
        post(args.base, '/flush_cache', {})
        for rep in range(args.reps):
            result = request(args.base, fixture['body'], args.tokens)
            if abs(result['prompt_tokens'] - fixture['tokenized_prompt_tokens']) > 2:
                raise RuntimeError('Generation and tokenization disagree on prompt length')
            row = dict(label=args.label, target_tokens=fixture['target_tokens'], kind=fixture['kind'],
                       request_sha256=fixture['request_sha256'], trial=rep,
                       cache_condition='cold' if rep == 0 else 'repeat', **result)
            with args.output.open('a', encoding='utf-8') as out:
                out.write(json.dumps(row) + '\n')
            print(json.dumps({k: row[k] for k in ('label', 'target_tokens', 'kind', 'trial', 'cache_condition',
                            'prompt_tokens', 'completion_tokens', 'ttft_s', 'decode_proxy_tps', 'output_sha256')}), flush=True)
            wait_idle(args.base)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['build', 'run'])
    p.add_argument('--base', default='http://127.0.0.1:8000')
    p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--label', default='unlabeled')
    p.add_argument('--tokens', type=int, default=512)
    p.add_argument('--reps', type=int, default=3)
    p.add_argument('--depths', default='', help='Optional comma-separated subset for repeated-boot controls')
    args = p.parse_args()
    if args.mode == 'build':
        build(args.base, args.fixtures)
    else:
        if not args.output or args.output.exists():
            p.error('--output must name a new file for a measured run')
        run(args)


if __name__ == '__main__':
    main()
