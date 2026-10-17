#!/usr/bin/env python3
"""One DeepSeek-harness (dsh) agent session via its Python SDK, the path the harness's BENCHMARK.md documents
(profile ``sdk-minimal`` = the jsonrpc-agent minimal variant: persistent bash, read_image, working_directory).

    <venv>/bin/python bench/harness/dsh_session.py --base-url http://127.0.0.1:PORT/v1 --model ID \
        --workspace WS --home HOME --effort off --max-tokens 32768 "prompt"

Run by bench/harness/run.py (``--harness dsh``) in a venv with ``deepseek-harness-sdk``. The patch turns off the
default upload of the full session log and plugin inventory inside every request body (DeepSeek's defaults), so
the requests carry only the conversation. Prints each session event as a JSON line, then a ``result`` line.
"""
import argparse
import json
import sys
from pathlib import Path

from deepseek_harness import DeepSeekHarness

PATCH = """- id: session-log-deepseek
  config:
    enabled: false
- id: plugin-package-inventory-deepseek
  disabled: true
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--effort", default="off", help="off | low | high | max (dsh's levels)")
    ap.add_argument("--max-tokens", type=int, default=32768)
    ap.add_argument("--profile", default="sdk-minimal")
    ap.add_argument("--dsh-bin", default=None, help="dsh executable (default: the SDK wheel's bundled runtime)")
    ap.add_argument("--runtime-cwd", default=None, help="where the dsh process starts (a source checkout: its root)")
    ap.add_argument("prompt")
    a = ap.parse_args()
    home = Path(a.home)
    home.mkdir(parents=True, exist_ok=True)
    patch = home.parent / "bench-off.patch.yml"
    patch.write_text(PATCH)
    with DeepSeekHarness(provider="deepseek-official", model=a.model, reasoning_effort=a.effort,
                         max_tokens=a.max_tokens, cwd=a.workspace, dsh_bin=a.dsh_bin,
                         runtime_cwd=a.runtime_cwd, dsh_home=str(home), profile=a.profile,
                         patches=(str(patch),), base_url=a.base_url, api_key="sk-dummy-not-a-key") as h:
        r = h.run(a.prompt, session_id=f"bench-{Path(a.workspace).name}")
    for e in r.events:
        print(json.dumps({"type": "dsh_event", "event": e}, default=str))
    print(json.dumps({"type": "result", "subtype": r.finish_reason, "final_response": r.final_response[:2000]}))


if __name__ == "__main__":
    sys.exit(main())
