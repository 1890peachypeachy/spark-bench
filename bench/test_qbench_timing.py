#!/usr/bin/env python3
"""qbench's speed numbers against a fake OpenAI stream (stdlib only):  python3 bench/test_qbench_timing.py

- no server timing block (an engine that sends none): TTFT and decode tok/s come from the chunks' arrival times;
- a ``tensorfold`` block (DeepSeek's Spark server, Nemotron's TensorFold server): the block's numbers, exactly as
  qbench at origin/main (9adc5fb) computed them.
"""
import http.server, importlib.util, json, pathlib, subprocess, sys, threading, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("qbench", HERE / "qbench.py")
qbench = importlib.util.module_from_spec(spec); spec.loader.exec_module(qbench)

FIRST_DELAY, GAP, TOKENS = 0.40, 0.01, 50
BLOCK = {"prompt": 37, "ttft_s": 0.1234, "prefill_s": 0.05, "decode_s": 0.5, "completion": TOKENS}


class Fake(http.server.BaseHTTPRequestHandler):
    block = None

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        usage = {"prompt_tokens": 37, "completion_tokens": TOKENS, "total_tokens": 37 + TOKENS}
        if not body.get("stream"):
            out = {"choices": [{"message": {"content": "x" * TOKENS}, "finish_reason": "length"}], "usage": usage}
            if Fake.block:
                out["tensorfold"] = Fake.block
            data = json.dumps(out).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        def ev(d):
            self.wfile.write(b"data: " + json.dumps(d).encode() + b"\n\n"); self.wfile.flush()
        ev({"choices": [{"delta": {"role": "assistant"}}]})
        time.sleep(FIRST_DELAY)  # the prompt pass
        for _ in range(TOKENS):
            ev({"choices": [{"delta": {"content": "x"}}]}); time.sleep(GAP)
        last = {"choices": [{"delta": {}, "finish_reason": "length"}]}
        if Fake.block:
            last["tensorfold"] = Fake.block
        ev(last); ev({"choices": [], "usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")


class Timing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_stream_timestamps_without_a_block(self):
        Fake.block = None
        m = qbench.measured(qbench.Engine(self.url, "m", "k", False, 30), "p", TOKENS)
        self.assertEqual(m["timing"], "stream")
        self.assertAlmostEqual(m["ttft_s"], FIRST_DELAY, delta=0.15)       # was the whole reply's time
        self.assertGreater(m["decode_s"], TOKENS * GAP * 0.8)                # was ~0
        self.assertLess(m["decode_tok_s"], 1.0 / GAP * 1.25)                 # was ~10^5..10^6

    def test_server_block_is_unchanged(self):
        Fake.block = dict(BLOCK)
        m = qbench.measured(qbench.Engine(self.url, "m", "k", False, 30), "p", TOKENS)
        self.assertEqual(m["timing"], "server")
        self.assertEqual((m["ttft_s"], m["decode_s"], m["decode_tok_s"], m["prefill_tok_s"]),
                         (0.123, 0.5, 100.0, 740.0))
        # the same request through qbench as it was at origin/main 9adc5fb: identical fields but the new `timing`
        old_src = subprocess.run(["git", "-C", str(HERE), "show", "9adc5fb:bench/qbench.py"], capture_output=True, text=True)
        if old_src.returncode:
            self.skipTest("no git history")
        old = type(sys)("qbench_old"); old.__file__ = str(HERE / "qbench.py"); exec(compile(old_src.stdout, "qbench_old", "exec"), old.__dict__)
        o = old.measured(old.Engine(self.url, "m", "k", False, 30), "p", TOKENS)
        self.assertEqual({k: v for k, v in m.items() if k not in ("timing", "wall_s")},
                         {k: v for k, v in o.items() if k != "wall_s"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
