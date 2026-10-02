#!/usr/bin/env python3
"""Compare complete, matched context-depth result files; never fill missing cells."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def load(path, depths=(1000,20000,40000,80000,160000)):
    groups=defaultdict(list)
    for line in path.read_text().splitlines():
        row=json.loads(line)
        groups[(row['target_tokens'],row['kind'])].append(row)
    expected={(n,k) for n in depths for k in ('prose','code')}
    if set(groups)!=expected: raise ValueError('Incomplete or unexpected context/workload cells')
    for key,rows in groups.items():
        if sorted(r['trial'] for r in rows)!=[0,1,2]: raise ValueError(f'{key}: need exactly three trials')
        if len({r['request_sha256'] for r in rows})!=1: raise ValueError('Prompt changed between repeats')
        if len({r['prompt_tokens'] for r in rows})!=1: raise ValueError('Prompt length changed between repeats')
        if any(r['completion_tokens']!=512 for r in rows): raise ValueError('Output window differs from 512 tokens')
    return groups


def summarize(rows):
    cold=next(r for r in rows if r['trial']==0)
    rates=[r['decode_proxy_tps'] for r in rows]
    return dict(prompt_tokens=cold['prompt_tokens'],decode_tps_median=statistics.median(rates),
                decode_tps_min=min(rates),decode_tps_max=max(rates),decode_tps_trials=rates,
                cold_ttft_s=cold['ttft_s'],warm_ttft_s_median=statistics.median(r['ttft_s'] for r in rows if r['trial']>0),
                cold_prompt_tokens_per_ttft_s=cold['prompt_tokens']/cold['ttft_s'],
                unique_output_hashes=len({r['output_sha256'] for r in rows}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path); p.add_argument('candidate',type=Path); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--control',type=Path,help='Restored EP4 endpoint checks at 1k and 160k')
    a=p.parse_args(); baseline,candidate=load(a.baseline),load(a.candidate)
    control=load(a.control, (1000,160000)) if a.control else {}
    out=[]
    for key in sorted(baseline):
        left,right=baseline[key],candidate[key]
        if left[0]['request_sha256']!=right[0]['request_sha256'] or left[0]['prompt_tokens']!=right[0]['prompt_tokens']:
            raise ValueError(f'{key}: baseline and candidate prompts do not match')
        b,c=summarize(left),summarize(right)
        out.append(dict(target_tokens=key[0],kind=key[1],baseline=b,candidate=c,
                        decode_change_pct=(c['decode_tps_median']/b['decode_tps_median']-1)*100,
                        cold_ttft_change_pct=(c['cold_ttft_s']/b['cold_ttft_s']-1)*100))
        if key in control:
            check=control[key]
            if check[0]['request_sha256']!=left[0]['request_sha256'] or check[0]['prompt_tokens']!=left[0]['prompt_tokens']:
                raise ValueError('Restored control prompt mismatch')
            restored=summarize(check)
            out[-1]['restored_ep4']=restored
            out[-1]['decode_change_vs_restored_pct']=(c['decode_tps_median']/restored['decode_tps_median']-1)*100
    a.output.write_text(json.dumps({'cells':out,'limitations':[
        'One full sweep per configuration, with a restored EP4 endpoint control when provided; requests within a boot are not independent boots.',
        'One cold request and two repeats per cell; cold TTFT is a single observation.',
        'SSE timing measures a rate proxy; events may contain multiple tokens.',
        'Greedy outputs may differ across repeats/configurations; hashes and raw outputs are retained.',
        'This sweep measures single-stream decoding, not four-stream throughput at depth.'
    ]},indent=2)+'\n')
    for r in out:
        print(f"{r['target_tokens']:6} {r['kind']:5} {r['baseline']['decode_tps_median']:6.2f} -> {r['candidate']['decode_tps_median']:6.2f} ({r['decode_change_pct']:+.1f}%) cold TTFT {r['baseline']['cold_ttft_s']:.2f} -> {r['candidate']['cold_ttft_s']:.2f}s")


if __name__=='__main__': main()
