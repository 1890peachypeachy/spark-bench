# 🔥 Catch-up sidecar (optional)

Keeps a long chat warm in the local model's prefix cache while you talk to another model. Moved here from the top-level README on 2026-10-05.

**The problem:** after a long chat on a hosted model, switching to your local
model means it must re-read the whole conversation first — seconds to minutes.

**The trick:** while you chat elsewhere, a tiny helper sends each new message
to the local model in the background asking for a one-token reply. That is
enough to keep the conversation in its prefix cache. When you switch, the
answer starts instantly.

**In engineer terms:** after every turn (and every compact), the sidecar POSTs
the exact OpenAI body the local engine will see later, with `max_tokens=1`.
vLLM prefix-caches it. When you switch to `sparks/auto`, the prompt is already
KV — TTFT is decode, not a 150k–330k prefill.

```text
you finish a turn on any model
        │
        ▼
 harness POST /v1/snapshot   ──►  sidecar  ──►  vLLM warmup (max_tokens=1)
        │
        ▼
 GET /v1/status  →  grey / orange / green / red
        │
        ▼
 switch to local model  →  same body  →  cache hit
```

| Color | State | Meaning |
|---|---|---|
| grey | `idle` | No snapshot yet, or sidecar off |
| orange | `warming` / `stale` | Warmup in flight, or transcript changed since last warm |
| green | `warm` | Last successful warmup hash equals the current snapshot |
| red | `error` | Last warmup failed (engine down, 400, too big) |

Green is **hash match after a finished warmup**, not "vLLM is idle."
`cached_tokens` on the warmup call itself is often ~0 (that call *is* the
prefill).

**Rolling 1M.** Reserve a window (default 1M tokens). Append-only growth is a
cheap delta; sliding the window off the front is a **new** prefix — the
sidecar recomputes the kept tail in the background. Cut in big chunks or
compact; do not drip-drop 1k tokens every turn past the cap.

**What the harness must get right.** Warmup and the real turn must use the
**same prompt builder** (same messages, tools, chat-template kwargs). One extra
clock line at the front of the system prompt misses the whole cache. Bridges
for Pi / Eva-core / Hermes: [`docs/BRIDGES.md`](BRIDGES.md). Protocol:
[`docs/PROTOCOL.md`](PROTOCOL.md).

```bash
python3 -m catchup --listen 127.0.0.1:18900 --vllm http://HEAD:18888/v1
python3 -m unittest discover -s catchup -v
```

The serving recipes never reference the sidecar; nothing fails without it.
