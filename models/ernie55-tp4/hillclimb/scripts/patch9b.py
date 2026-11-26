import sys
p = sys.argv[1]
s = open(p).read()
anchor = 'print("Patched flashindexer.py (**kwargs forwarding) cleanly!")'
assert anchor in s and "# 9b." not in s
add = r'''
# 9b. vLLM 0.34 made the 6th positional arg max_seqlen_k (int) and dropped clean_logits; the plugin wrapper
# still forwarded it as clean_logits=..., so enabling FlashIndexer died at warm-up. Forward positionals instead.
src9 = open(p9).read()
_n = src9.count("clean_logits=clean_logits,")
src9 = src9.replace("cu_seqlen_ke, clean_logits=True, **kwargs\n):", "cu_seqlen_ke, *args, **kwargs\n):", 1)
src9 = src9.replace("clean_logits=clean_logits,", "*args,")
_body = src9.split("def _flashindexer_fp8_fp4_mqa_logits")[1].split("def patch_sparse")[0]
assert _n == 2 and "clean_logits" not in _body and "*args, **kwargs" in _body, "9b targets"
open(p9, "w").write(src9)
print("Patched flashindexer.py (vLLM 0.34 positional max_seqlen_k) cleanly!")
'''
s = s.replace(anchor, anchor + "\n" + add, 1)
open(p, "w").write(s)
print("ok")
