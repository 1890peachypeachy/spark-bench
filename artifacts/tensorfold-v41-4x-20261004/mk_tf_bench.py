"""Write bench-v41-depth-tf.py from the published bench-v41-depth-ab.py (two edits only)."""
import sys
s = open(sys.argv[1]).read()
a = """def idle(base):
    with urllib.request.urlopen(base + '/v1/loads', timeout=10) as r:
        loads = json.load(r).get('loads')
    if not loads:
        raise RuntimeError('Server returned no load state')
    return all(x.get('num_running_reqs', 0) == 0 and x.get('num_waiting_reqs', 0) == 0 for x in loads)"""
b = """def idle(base):
    # TensorFold: /health carries in-flight requests (no /v1/loads).
    with urllib.request.urlopen(base + '/health', timeout=10) as r:
        h = json.load(r)
    return h.get('inflight', 1) == 0 and not h.get('busy', True)"""
assert a in s
s = s.replace(a, b)
a = "        post(args.base, '/flush_cache', {})\n"
assert a in s
s = s.replace(a, "        # TensorFold has no /flush_cache: each fixture is a new prompt, so trial 0 is cold as on SGLang.\n")
open(sys.argv[2], "w").write(s)
print("written")
