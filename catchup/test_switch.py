import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from catchup.service import CatchupService, WarmupAborted
from catchup.switch import CatchupSwitch, http_fetcher, resolve_config


def wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeHealth:
    """Mocked /api/kv-catchup/health: set .body, or .error to fail the fetch."""

    def __init__(self, body=None):
        self.body = body
        self.error = None
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return self.body


def make_switch(fake):
    logs = []
    return CatchupSwitch(fake, log=logs.append), logs


class SwitchStateTests(unittest.TestCase):
    def test_never_known_defaults_on(self):
        fake = FakeHealth()
        fake.error = "unreachable: connection refused"
        switch, logs = make_switch(fake)
        self.assertTrue(switch.is_on())
        self.assertTrue(switch.poll_once())
        self.assertTrue(switch.allows("eva-dm"))
        self.assertFalse(switch.snapshot()["known"])
        self.assertEqual(len(logs), 1)
        self.assertIn("never known, defaulting ON", logs[0])

    def test_off_on_transitions_are_logged(self):
        fake = FakeHealth({"switchedOn": False, "disabledAgents": [], "updatedAt": "t1"})
        switch, logs = make_switch(fake)
        self.assertFalse(switch.poll_once())
        self.assertFalse(switch.allows("eva-dm"))
        self.assertIn("[kv-catchup] switch off seen (state source: health endpoint", logs[-1])
        switch.poll_once()  # unchanged: no new transition line
        self.assertEqual(sum("switch off seen" in line for line in logs), 1)
        fake.body = {"switchedOn": True, "disabledAgents": [], "updatedAt": "t2"}
        self.assertTrue(switch.poll_once())
        self.assertIn("[kv-catchup] switch on seen", logs[-1])

    def test_failure_keeps_last_known_off(self):
        fake = FakeHealth({"switchedOn": False, "disabledAgents": []})
        switch, logs = make_switch(fake)
        switch.poll_once()
        fake.error = "timed out"
        for _ in range(3):
            self.assertFalse(switch.poll_once())
        self.assertEqual(switch.snapshot()["failures"], 3)
        self.assertEqual(sum("poll failed" in line for line in logs), 1)
        self.assertIn("keeping OFF", [line for line in logs if "poll failed" in line][0])
        fake.error = None
        fake.body = {"switchedOn": True, "disabledAgents": []}
        self.assertTrue(switch.poll_once())
        self.assertTrue(any("reachable again after 3" in line for line in logs))

    def test_malformed_body_is_a_failure(self):
        fake = FakeHealth({"switchedOn": False})
        switch, _ = make_switch(fake)
        switch.poll_once()
        fake.body = {"error": "oops"}
        self.assertFalse(switch.poll_once())
        self.assertEqual(switch.snapshot()["failures"], 1)

    def test_disabled_agents_use_session_prefix(self):
        fake = FakeHealth({"switchedOn": True, "disabledAgents": ["kai"]})
        switch, logs = make_switch(fake)
        switch.poll_once()
        self.assertTrue(switch.is_on())
        self.assertFalse(switch.allows("kai"))
        self.assertFalse(switch.allows("kai:background"))
        self.assertTrue(switch.allows("eva-dm"))
        self.assertTrue(any("disabled agents now ['kai']" in line for line in logs))

    def test_background_loop_polls(self):
        fake = FakeHealth({"switchedOn": False, "disabledAgents": []})
        switch, _ = make_switch(fake)
        switch.poll_s = 0.02
        switch.start()
        try:
            self.assertTrue(wait_until(lambda: fake.calls >= 3))
            self.assertFalse(switch.is_on())
        finally:
            switch.stop()


class AuthWiringTests(unittest.TestCase):
    def setUp(self):
        seen = self.seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):  # noqa: N802
                seen.append((self.path, dict(self.headers)))
                if self.headers.get("x-service-token") != "svc-secret":
                    body, code = b'{"error":"unauthorized"}', 401
                else:
                    body, code = json.dumps({"switchedOn": False, "disabledAgents": ["kai"], "updatedAt": 5}).encode(), 200
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/kv-catchup/health"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_service_token_header_is_sent(self):
        body = http_fetcher(self.url, "svc-secret")()
        self.assertFalse(body["switchedOn"])
        path, headers = self.seen[-1]
        self.assertEqual(path, "/api/kv-catchup/health")
        lowered = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(lowered["x-service-token"], "svc-secret")
        self.assertEqual(lowered["x-eva-actor"], "kv-catchup-sidecar")

    def test_wrong_token_is_a_failure_not_a_switch_flip(self):
        switch, logs = make_switch(http_fetcher(self.url, "wrong"))
        self.assertTrue(switch.poll_once())
        self.assertIn("HTTP 401", logs[0])

    def test_unreachable_is_a_failure(self):
        switch, logs = make_switch(http_fetcher("http://127.0.0.1:9/api/kv-catchup/health", "svc-secret", timeout_s=0.5))
        self.assertTrue(switch.poll_once())
        self.assertIn("unreachable", logs[0])


class ConfigTests(unittest.TestCase):
    def test_token_and_url_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, ".env")
            with open(env_file, "w") as fh:
                fh.write("# eva-core\nPORT=3456\nSERVICE_TOKEN='from-core'\nEVA_CORE_TOKEN=other\n")
            base = {"EVA_CORE_ENV_FILE": env_file}
            cfg = resolve_config(base)
            self.assertEqual(cfg["token"], "from-core")
            self.assertEqual(cfg["url"], "http://127.0.0.1:3456/api/kv-catchup/health")
            cfg = resolve_config({**base, "EVA_CORE_SERVICE_TOKEN": "explicit", "EVA_CORE_URL": "http://eva-core:9000/"})
            self.assertEqual(cfg["token"], "explicit")
            self.assertEqual(cfg["url"], "http://eva-core:9000/api/kv-catchup/health")
            cfg = resolve_config({**base, "CATCHUP_SWITCH_URL": "http://x/h"})
            self.assertEqual(cfg["url"], "http://x/h")
        cfg = resolve_config({"EVA_CORE_ENV_FILE": "/nonexistent/.env", "SERVICE_TOKEN": "proc"})
        self.assertEqual(cfg["token"], "proc")
        self.assertEqual(cfg["url"], "http://127.0.0.1:3456/api/kv-catchup/health")


class ServiceSwitchTests(unittest.TestCase):
    def test_off_skips_new_warms(self):
        calls = []
        fake = FakeHealth({"switchedOn": False, "disabledAgents": []})
        switch, _ = make_switch(fake)
        switch.poll_once()
        service = CatchupService(warmup_fn=lambda w: calls.append(w) or {}, max_context=10000, switch=switch)
        status = service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status["state"], "off")
        self.assertEqual(status["color"], "off")
        time.sleep(0.05)
        self.assertEqual(calls, [])
        self.assertEqual(service.stats()["pending"], 0)
        self.assertFalse(service.stats()["switch"]["switched_on"])

        fake.body = {"switchedOn": True, "disabledAgents": []}
        switch.poll_once()
        service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(wait_until(lambda: service.get("eva-dm")["state"] == "warm"))
        self.assertEqual(len(calls), 1)

    def test_switch_off_aborts_inflight_and_drops_queue(self):
        started = []

        def warmup(work):
            started.append(work["session_id"])
            if not work["cancel"].wait(5):
                return {"usage": {"prompt_tokens": 1}}
            raise WarmupAborted()

        fake = FakeHealth({"switchedOn": True, "disabledAgents": []})
        switch, logs = make_switch(fake)
        switch.poll_once()
        service = CatchupService(warmup_fn=warmup, max_context=10000, max_inflight=1, switch=switch)
        service.submit({"session_id": "a", "messages": [{"role": "user", "content": "aaa"}]})
        service.submit({"session_id": "b", "messages": [{"role": "user", "content": "bbb"}]})
        self.assertTrue(wait_until(lambda: started == ["a"]))
        self.assertEqual(service.stats()["pending"], 1)

        fake.body = {"switchedOn": False, "disabledAgents": []}
        switch.poll_once()
        self.assertTrue(wait_until(lambda: service.get("a")["state"] == "off"))
        self.assertEqual(service.get("b")["state"], "off")
        self.assertTrue(wait_until(lambda: service.stats()["inflight"] == 0))
        self.assertEqual(service.stats()["pending"], 0)
        time.sleep(0.05)
        self.assertEqual(started, ["a"])  # b never started
        self.assertIsNone(service.get("a")["error"])

    def test_disabled_agent_only_aborts_that_agent(self):
        started = []

        def warmup(work):
            started.append(work["session_id"])
            if work["cancel"].wait(0.3):
                raise WarmupAborted()
            return {"usage": {"prompt_tokens": 1}}

        fake = FakeHealth({"switchedOn": True, "disabledAgents": []})
        switch, _ = make_switch(fake)
        switch.poll_once()
        service = CatchupService(warmup_fn=warmup, max_context=10000, max_inflight=2, switch=switch)
        service.submit({"session_id": "kai:background", "messages": [{"role": "user", "content": "k"}]})
        service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "e"}]})
        self.assertTrue(wait_until(lambda: len(started) == 2))
        fake.body = {"switchedOn": True, "disabledAgents": ["kai"]}
        switch.poll_once()
        self.assertTrue(wait_until(lambda: service.get("eva-dm")["state"] == "warm"))
        self.assertEqual(service.get("kai:background")["state"], "off")


class SlowVllm:
    """Fake vLLM whose /chat/completions blocks until released or the client hangs up."""

    def __init__(self):
        self.release = threading.Event()
        self.received = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("content-length") or 0))
                outer.received.set()
                outer.release.wait(5)
                body = b'{"usage":{"prompt_tokens":7}}'
                try:
                    self.send_response(200)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class HttpWarmupAbortTests(unittest.TestCase):
    def test_real_http_warmup_is_cut_when_switch_goes_off(self):
        vllm = SlowVllm()
        self.addCleanup(vllm.close)
        fake = FakeHealth({"switchedOn": True, "disabledAgents": []})
        switch, _ = make_switch(fake)
        switch.poll_once()
        service = CatchupService(vllm_url=vllm.url, model="m", max_context=10000, timeout_s=10, switch=switch)
        service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "prefill me"}]})
        self.assertTrue(vllm.received.wait(3))
        t0 = time.time()
        fake.body = {"switchedOn": False, "disabledAgents": []}
        switch.poll_once()
        self.assertTrue(wait_until(lambda: service.get("eva-dm")["state"] == "off", timeout=2))
        self.assertLess(time.time() - t0, 2)
        self.assertFalse(vllm.release.is_set())  # cut before the engine answered
        self.assertTrue(wait_until(lambda: service.stats()["inflight"] == 0))

    def test_real_http_warmup_still_works_when_on(self):
        vllm = SlowVllm()
        vllm.release.set()
        self.addCleanup(vllm.close)
        service = CatchupService(vllm_url=vllm.url, model="m", max_context=10000, timeout_s=10)
        service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(wait_until(lambda: service.get("eva-dm")["state"] == "warm"))
        self.assertEqual(service.get("eva-dm")["prompt_tokens"], 7)


if __name__ == "__main__":
    unittest.main()
