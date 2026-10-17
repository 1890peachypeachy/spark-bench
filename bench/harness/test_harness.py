#!/usr/bin/env python3
"""The harness bench's tap and task builder, offline (stdlib only):  python3 bench/harness/test_harness.py"""
import http.server, json, pathlib, sys, threading, unittest, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run  # noqa: E402
import tap  # noqa: E402

OA_SSE = "".join("data: " + json.dumps(d) + "\n\n" for d in [
    {"choices": [{"delta": {"content": "hi"}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "write", "arguments": "{"}}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}}]},
    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 7}}]) + "data: [DONE]\n\n"
AN_SSE = "".join(f"event: {d['type']}\ndata: " + json.dumps(d) + "\n\n" for d in [
    {"type": "message_start", "message": {"usage": {"input_tokens": 50, "cache_read_input_tokens": 10}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "name": "Write", "input": {}}},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}}])


class Upstream(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Upstream.seen.append((self.path, body))
        out = (AN_SSE if self.path.endswith("/messages") else OA_SSE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class T(unittest.TestCase):
    def test_parse_openai_sse(self):
        r = tap.parse_reply(OA_SSE.encode(), "text/event-stream")
        self.assertEqual((r["prompt_tokens"], r["completion_tokens"], r["tool_calls"]), (100, 7, 1))
        self.assertEqual((r["tool_names"], r["finish"], r["content_chars"]), (["write"], "tool_calls", 2))

    def test_parse_anthropic_sse(self):
        r = tap.parse_reply(AN_SSE.encode(), "text/event-stream")
        self.assertEqual((r["prompt_tokens"], r["completion_tokens"], r["tool_calls"]), (60, 9, 1))
        self.assertEqual(r["finish"], "tool_use")

    def test_thinking_asked(self):
        self.assertIs(tap.thinking_asked({"chat_template_kwargs": {"enable_thinking": False}}), False)
        self.assertIs(tap.thinking_asked({"thinking": {"type": "disabled"}}), False)
        self.assertIs(tap.thinking_asked({"thinking": {"type": "adaptive"}}), True)
        self.assertIs(tap.thinking_asked({"reasoning_effort": "none"}), False)
        self.assertIsNone(tap.thinking_asked({"messages": []}))

    def test_passthrough_unchanged(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        body = {"model": "m", "messages": [{"role": "user", "content": "x"}], "stream": True,
                "chat_template_kwargs": {"enable_thinking": False}}
        with tap.Tap(f"http://127.0.0.1:{srv.server_address[1]}/v1") as t:
            for path in ("/v1/chat/completions", "/v1/messages"):
                req = urllib.request.Request(t.base + path, data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                got = urllib.request.urlopen(req, timeout=10).read().decode()
                self.assertEqual(got, AN_SSE if path.endswith("messages") else OA_SSE)
        srv.shutdown()
        self.assertEqual([p for p, _ in Upstream.seen[-2:]], ["/v1/chat/completions", "/v1/messages"])
        self.assertEqual(Upstream.seen[-1][1], body)  # body forwarded as sent
        s = t.summary()
        self.assertEqual((s["llm_requests"], s["tool_calls"], s["prompt_tokens"]), (2, 2, 160))
        self.assertEqual(s["thinking_asked"], ["False"])

    def test_tasks(self):
        ts = run.build_tasks(run.AREAS)
        self.assertEqual({a: sum(t["area"] == a for t in ts) for a in run.AREAS},
                         {"coding": 5, "math": 30, "mmlu": 50, "if": 20, "json": 6})
        self.assertTrue(all(t["full_prompt"].endswith(run.INSTRUCTION.format(file=t["file"])) for t in ts))
        mm = [t for t in ts if t["area"] == "mmlu"][0]
        self.assertEqual(mm["grade"]("D\n")[0], mm["grade"](" d")[0])


if __name__ == "__main__":
    unittest.main()
