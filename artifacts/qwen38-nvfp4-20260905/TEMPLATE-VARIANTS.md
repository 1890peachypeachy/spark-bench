# Chat template variants (opt-in, bench-gated)

Launcher flag: `TEMPLATE_VARIANT=stock|froggeric` (default `stock`).

- **stock** — the checkpoint's built-in template. This is the serving default.
- **froggeric** — `chat_template_froggeric_v22.5.jinja`, from
  https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates (repo commit
  `855bffc49448e299789730ff92c9b8d834d6cc14`, file sha256
  `e57684bae4156211a55473c5a63be976a405a37ab5be5ae0e5abf1df5349c4b2`,
  Apache-2.0, fetched 2026-09-05). The launcher hash-verifies the file before
  boot and fails closed on drift.

Why it exists: tool-call token parity across consecutive `<tool_call>` history
blocks (prefix-KV-cache stability in multi-tool agent turns) and broader
reasoning-history extraction (including vLLM's `message.reasoning`).

**Rejected:** peculiar-ragdoll/Qwen-Sharp-Chat-Templates (the froggeric base +
a force-appended terseness system prompt). Persona change wearing infra
clothes; invalidates the role-bench baseline; trust surface of a one-maintainer
default template. Review thread: Eva/Depths, #general 2026-09-05.

**Adoption gate (owner: Eva):** role suite + tool-heavy fixture, control=stock
vs treatment=froggeric, one relaunch window, back to stock after. Primary
metrics: prefix-cache hit rate + pi tool-loop parse success; quality parity is
the gate. If neither primary metric moves meaningfully, stock stays even at
quality parity — no external artifact for zero gain.

Validated before staging: renders cleanly with the serving image's jinja across
default / enable_thinking=false / enable_thinking=true, including multi-tool
history and `message.reasoning` extraction. NOT yet validated: live-serve
behavior, parser interplay under load — that is the bench.
