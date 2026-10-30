# Harness effect on the same weights: DeepSeek-V4.1-Flash-1017 under raw API / pi / DeepSeek harness / Claude Code (2026-10-17)

One served model (DeepSeek-V4.1-Flash-1017, EXL3 2.9 on the TensorFold Zig engine, four Sparks), one task set, one set of
graders. The only thing that changes between rows B–D1 is the agent harness. Row D2 is Claude Code with its own model, as a
reference point.

| row | harness | version | model | coding | math | MMLU-50 | IF | JSON | total | wall | LLM calls | tool calls | engine tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | raw API, no harness (qbench) | qbench v1 | 1017 | 4/5 | 30/30 | 43/50 | 18/20 | 6/6 | **101/111** | 85 s (incl. all 200 MMLU) | 1 per task | – | – |
| B | pi coding agent | 0.99.1 | 1017 | 4/5 | 30/30 | 41/50 | 20/20 | 6/6 | **101/111** | 264 s | 234 | 123 | prompt 406,146 (cached 205,792) / completion 14,012 |
| C | DeepSeek harness (dsh), sdk-minimal | dsh-v0.2.1-rc.2 (687f282e86) | 1017 | 4/5 | 30/30 | 41/50 | 20/20 | 6/6 | **101/111** | 214 s | 261 | 135 | prompt 231,650 (cached 130,688) / completion 12,293 |
| D1 | Claude Code + our Anthropic shim | 2.1.301 | 1017 | 4/5 | 30/30 | 39/50 | 18/20 | 6/6 | **97/111** | 1101 s | 762 | 652 | prompt 33,737,373 (cached 31,946,896) / completion 70,375 |
| D2 | Claude Code, native (reference) | 2.1.301 | Claude Opus | 4/5 | 30/30 | 46/50 | 20/20 | 6/6 | **106/111** | 166 s | – | 113 | (not on the Sparks) prompt 3,395,314 / completion 23,086, as Claude Code reports them |

**Answer:** the harness hardly moves this model's score: A, B and C all land on 101/111. Coding, math and JSON are identical
in every row. The only movement is a few MMLU items in each direction (43 vs 41) and two IF items that the agent rows fix by
checking their own file. Claude Code + shim is the one outlier at 97/111. Two MMLU answers came back in chat instead of the
file, and both were correct, so knowledge is the same 41/50. One IF lipogram task ran 542 self-check turns into the 600 s
timeout. It costs 4–5× the wall time and 80–150× the prompt tokens of pi/dsh, because its ~20 tool definitions and system prompt are resent with every call.

Extra point on the old weights (Venice, full-precision old V4.1, same method): raw qbench 103/111 vs pi 99/111 (MMLU-50 44
vs 41, math 30 vs 29). That is the same small MMLU dip under a harness.

## Method
- Tasks: qbench's coding (5, hidden tests), math (GSM8K-30), MMLU (every 4th item of MMLU-200 = 50, fixed and the same
  for every row; row A is rescored on that subset from its full run), IF (20), JSON (6). The graders are qbench's own
  functions (`grade_coding`, `grade_math`, `grade_mmlu`, `check_if`, `grade_json`), imported, not rewritten.
- Each task is a fresh workspace and a fresh session. The prompt is the qbench prompt plus one fixed instruction: write
  exactly what the reply would have been to `answer.txt` (`solution.py` for code, `answer.json` for JSON). The file is
  graded. Timeout is 600 s per task in every row, with 4 sessions in parallel.
- Thinking is OFF in every 1017 row, as in qbench's default: pi sends `chat_template_kwargs.enable_thinking=false`, dsh
  sends `thinking: {type: disabled}` (reasoning_effort `off`), and Claude Code sends no `thinking` field, which the
  engine's Anthropic route treats as disabled. The tap logged the switch on every request. With thinking off, numeric
  effort does not apply: the engine renders effort `none`.
- Every agent request went through a byte-for-byte passthrough tap (`bench/harness/tap.py`). It counted LLM calls, tool
  calls and the thinking switch, and capped requests in flight at 4. Engine tokens are `/metrics` deltas over each row.
  The rows ran one after another with nothing else on the engine: each row's engine request delta equals its tap count
  (234, 261, 762).
- Harness configs: pi uses an isolated agent dir (no extensions, skills, context files or prompt templates) and the 4
  built-in tools. dsh runs the local checkout's CLI through its Python SDK with profile `sdk-minimal` (bash, read_image,
  working_directory), and its default upload of session logs inside every request body switched off. Claude Code runs
  `claude -p --safe-mode` with its own config dir, `ANTHROPIC_BASE_URL` pointing at the engine's `/v1/messages` and a
  dummy key (D1), or the default login (D2).

## Not comparable / caveats
- **Sampling differs by harness.** qbench and pi send `temperature: 0` (greedy). dsh and Claude Code send no temperature,
  so the engine's default applies. Measured: an omitted temperature gives the same text as `temperature: 1` (seeded per
  prompt) and different text from `temperature: 0`. Part of the C/D1 vs A/B difference can be sampling, not the harness.
  The control rows with temperature forced to 0 at the tap (`--force-temperature 0`) were not run: the engine went to
  the next test first.
- **Tools area skipped.** qbench's tool area scores the raw API's `tool_calls` against a fixed tool list. Inside a harness
  the harness brings its own tools, so there is no honest mapping.
- **JSON is an instruction here.** An agent harness has no API-level `response_format`, so the harness rows write
  `answer.json` as instructed. Row A uses `response_format`.
- **MMLU is a 50-item subset** in every row, so a 1-item change is 2 points.
- **D1 measures the shim too.** The engine's Anthropic route translates Claude Code's requests. Its streamed
  `usage` reads 0 tokens, so Claude Code sees zero context use.
- **D2 is a different model.** It runs with Claude Code's native defaults, including adaptive thinking (not forced
  off), and is not run on the Sparks.

Files: `B-pi.json`, `C-dsh.json`, `D1-claude-code-shim.json`, `D2-claude-code-opus.json`, `extra-pi-venice-old-v41.json`
(per task: answer, grade, wall, tap counts, harness-reported tool calls). Runner: `bench/harness/run.py`. Table:
`bench/harness/table.py`. Row A: `../qbench-dsv41-1017-zig-20261017.json`.
