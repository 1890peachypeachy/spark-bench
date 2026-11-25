#!/usr/bin/env python3
"""Byte sizes of ERNIE-5.5-Flash-Preview tensors by category, from safetensors headers only (no weights read)."""
import json, os, re, struct, sys, collections

D = sys.argv[1]
cfg = json.load(open(os.path.join(D, "config.json")))
idx = json.load(open(os.path.join(D, "model.safetensors.index.json")))["weight_map"]
files = sorted(set(idx.values()))
sizes = {}
dtypes = collections.Counter()
for f in files:
    with open(os.path.join(D, f), "rb") as fh:
        n = struct.unpack("<Q", fh.read(8))[0]
        h = json.loads(fh.read(n))
    for k, v in h.items():
        if k == "__metadata__":
            continue
        a, b = v["data_offsets"]
        sizes[k] = (b - a, v["dtype"], v["shape"])
        dtypes[v["dtype"]] += b - a

def cat(k):
    if re.search(r"mtp|dspark|draft|spec", k, re.I):
        return "draft"
    if "lm_head" in k:
        return "lm_head"
    if "embed_tokens" in k or "word_embeddings" in k:
        return "embed"
    if re.search(r"\.experts\.\d+\.", k):
        return "routed_experts"
    if re.search(r"shared_expert", k):
        return "shared_experts"
    if re.search(r"\.(gate|router)\.", k) or k.endswith(".gate.weight") or "e_score_correction" in k:
        return "router"
    if re.search(r"self_attn|attention|indexer|compress", k):
        return "attention"
    if re.search(r"\.mlp\.", k):
        return "dense_mlp"
    return "other"

tot = collections.Counter()
cnt = collections.Counter()
for k, (b, dt, sh) in sizes.items():
    c = cat(k)
    tot[c] += b
    cnt[c] += 1
print("config keys of interest:")
for key in ["num_hidden_layers", "hidden_size", "vocab_size", "num_attention_heads", "moe_num_experts", "n_routed_experts",
            "num_experts", "moe_k", "num_experts_per_tok", "moe_intermediate_size", "intermediate_size", "tie_word_embeddings",
            "kv_lora_rank", "q_lora_rank", "compress_ratios", "num_nextn_predict_layers", "dspark_config", "draft_config"]:
    if key in cfg:
        v = cfg[key]
        print(f"  {key} = {str(v)[:160]}")
print("\nbytes by category (GB = 1e9):")
for c, b in sorted(tot.items(), key=lambda x: -x[1]):
    print(f"  {c:16s} {b/1e9:9.3f} GB   tensors={cnt[c]}")
print(f"  {'TOTAL':16s} {sum(tot.values())/1e9:9.3f} GB")
print("\ndtypes:", {k: round(v / 1e9, 2) for k, v in dtypes.items()})
print("\nsample names per category:")
seen = collections.defaultdict(list)
for k in sorted(sizes):
    c = cat(k)
    if len(seen[c]) < 4:
        seen[c].append(f"{k} {sizes[k][1]} {sizes[k][2]}")
for c, v in seen.items():
    print(" ", c)
    for s in v:
        print("     ", s)
json.dump({c: b for c, b in tot.items()}, open(sys.argv[2], "w"))
