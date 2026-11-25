"""Split the DSpark draft (model.mtp.*) tensor bytes into experts / head+embed / other, from headers only."""
import json, os, re, struct, collections

D = "/var/tmp/models/ERNIE-5.5-Flash-Preview"
idx = json.load(open(os.path.join(D, "model.safetensors.index.json")))["weight_map"]
tot = collections.Counter()
names = collections.defaultdict(list)
for f in sorted(set(v for k, v in idx.items() if k.startswith("model.mtp"))):
    with open(os.path.join(D, f), "rb") as fh:
        n = struct.unpack("<Q", fh.read(8))[0]
        h = json.loads(fh.read(n))
    for k, v in h.items():
        if not k.startswith("model.mtp"):
            continue
        a, b = v["data_offsets"]
        c = "experts" if re.search(r"\.experts\.\d+\.", k) else ("head/embed" if re.search(r"head|embed", k) else "other")
        tot[c] += b - a
        if len(names[c]) < 5:
            names[c].append("%s %s %s" % (k, v["dtype"], v["shape"]))
print("draft prefixes:", sorted({".".join(k.split(".")[:3]) for k in idx if k.startswith("model.mtp")})[:12])
for c, b in tot.items():
    print("  %-12s %7.3f GB" % (c, b / 1e9))
    for s in names[c]:
        print("      ", s)
cfg = json.load(open(os.path.join(D, "config.json")))
for k in cfg:
    if re.search(r"dspark|mtp|draft|spec|markov|block", k, re.I):
        print(" cfg", k, "=", str(cfg[k])[:220])
