# Model lanes — start here

One shared four-DGX-Spark cluster. **These deployments are mutually exclusive.**
Status below is dated 2026-10-05, not a live health signal. Each model folder has a recipe (`README.md`) and a dated history of every change and measurement (`JOURNAL.md`).

| Model | Status | Entry point |
|---|---|---|
| DeepSeek V4.1 Flash | Serving on TensorFold, four Sparks (TP=4), 2.9-bit EXL3, since 2026-10-04 (pipelined prompt reading since 2026-10-05: cold 160k prompt 39 s); SGLang TP4/EP2 kept as rollback | [TensorFold guide](deepseek-v4.1-flash/tensorfold-4x/README.md) · [recipe (our fork)](https://github.com/neko-legends/deepseek-v41-tensorfold-spark) · [V4.1 guide](deepseek-v4.1-flash/README.md) · [journal](deepseek-v4.1-flash/JOURNAL.md) |
| Qwen 3.8 Flash Next | Stopped; archived recipe | [Qwen guide](qwen-3.8-flash-next/README.md) · [journal](qwen-3.8-flash-next/JOURNAL.md) |
| GLM 5.3 Flash | Stopped; archived recipes | [GLM guide](glm-5.3-flash/README.md) · [journal](glm-5.3-flash/JOURNAL.md) |
| DeepSeek V4 Flash | Not serving; archived recipe | [DeepSeek guide](deepseek-v4-flash/README.md) · [journal](deepseek-v4-flash/JOURNAL.md) |

## Instructions for a new operator or agent

1. Read the selected model's guide and recipe, then the shared [fabric runbook](../docs/FABRIC.md).
2. Verify image/checkpoint identity, local weights on every node, architecture support,
   fabric addresses, mount paths and available memory. Host names and paths in these
   recipes describe our lab; they are not universal defaults.
3. Check live containers and recovery automation before doing anything destructive.
   Obtain operator approval for a model switch. Do not start a second model on occupied GPUs.
4. Distinguish a documented configuration from a complete packaged deployment.
   Qwen's patched image/build inputs are not yet published here; see its explicit recovery checklist.
5. Run correctness checks before throughput tests, then test mixed load and stability.
   An HTTP health response or short successful benchmark is not production qualification.
6. Preserve raw dated results under `results/`; record boot configuration, workload,
   thinking mode, timing definition and failures. Never overwrite historical evidence.

## Layout rules

- Model entry points and model-specific benchmarks belong under `models/<model>/`.
- Shared benchmark tooling remains in `scripts/`; shared operating docs in `docs/`.
- Historical measurements remain in `results/`, preserving existing URLs.
- Qwen's former documentation path forwards here; old benchmark paths are symlinks.
- DeepSeek entry scripts in its recipe directory delegate to the original `scripts/`
  implementations. Those and the root Compose/patch layout remain intentionally in place:
  their staging and bind-mount paths are coupled. Do not move them without deployment tests.
- Untracked investigation artifacts are not part of the public recipe. Do not assume
  they exist in a fresh clone, or publish vendored patches without license review.
