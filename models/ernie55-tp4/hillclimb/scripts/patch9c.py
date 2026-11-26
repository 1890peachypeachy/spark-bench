import sys
p = sys.argv[1]
s = open(p).read()
anchor = 'print("Patched flashindexer.py (vLLM 0.34 positional max_seqlen_k) cleanly!")'
assert anchor in s and "# 9c." not in s
add = r'''
# 9c. GB10's DeepGEMM MQA-logits kernel only takes 16/32/64 heads (csrc/apis/attention.hpp:142); FlashIndexer keeps 8.
# Pad the 8 selected heads to 16 by repeating them with weight exactly 0: relu(q.k) * 0 adds nothing, so the logits are
# the 8-head selection's, computed by a 16-head kernel (4x fewer heads than the full 64 instead of 8x).
src9 = open(p9).read()
old9c = "    return _orig_mqa_logits(\n        (q_sel, q_sf_sel),"
new9c = """    if q_sel.shape[1] < 16:
        _pad = 16 - q_sel.shape[1]
        _qb = q_sel.contiguous().view(torch.uint8)
        q_sel = torch.cat([_qb, _qb[:, :_pad]], dim=1).view(q_sel.dtype)
        if q_sf_sel is not None:
            q_sf_sel = torch.cat([q_sf_sel, q_sf_sel[:, :_pad]], dim=1)
        w_sel = torch.cat([w_sel, torch.zeros_like(w_sel[:, :_pad])], dim=1)
""" + old9c
assert src9.count(old9c) == 1, "9c target"
src9 = src9.replace(old9c, new9c, 1)
open(p9, "w").write(src9)
print("Patched flashindexer.py (GB10 16-head pad) cleanly!")
'''
s = s.replace(anchor, anchor + "\n" + add, 1)
open(p, "w").write(s)
print("ok")
