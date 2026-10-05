import contextlib
import io
import json
import os
import select
import socket
import tempfile
import threading
import time
import unittest
import unittest.mock
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen

from catchup.__main__ import build_handler
from catchup.service import CONNECT_TIMEOUT_S, CatchupService, WarmupAborted
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


class HangupDetectingVllm:
    """Fake engine that, like uvicorn under vLLM, watches the client socket while
    'prefilling' and records the moment it sees the client hang up."""

    def __init__(self, prefill_s=5.0):
        self.received = threading.Event()
        self.disconnected = threading.Event()
        self.headers = {}
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("content-length") or 0))
                outer.requests += 1
                outer.headers = {k.lower(): v for k, v in self.headers.items()}
                outer.received.set()
                deadline = time.time() + prefill_s
                while time.time() < deadline:
                    ready, _, _ = select.select([self.connection], [], [], 0.02)
                    if ready and self.connection.recv(1, socket.MSG_PEEK) == b"":
                        outer.disconnected.set()  # EOF: what triggers vLLM's abort
                        return
                body = b'{"usage":{"prompt_tokens":7}}'
                self.send_response(200)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class CloseHeaderBodyVllm:
    """Fake engine for fix pass 2: sends headers with Connection: close plus part
    of the body, then keeps 'generating' the rest while watching for the client to
    hang up. http.client hands the socket to the response on Connection: close and
    sets conn.sock = None, which is where the first abort lost its grip."""

    def __init__(self, stream_s=5.0):
        self.headers_sent = threading.Event()
        self.disconnected = threading.Event()
        self.headers = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("content-length") or 0))
                outer.headers = {k.lower(): v for k, v in self.headers.items()}
                self.send_response(200)
                self.send_header("content-length", "1000")
                self.send_header("connection", "close")
                self.end_headers()
                self.wfile.write(b'{"usage":')
                self.wfile.flush()
                outer.headers_sent.set()
                deadline = time.time() + stream_s
                while time.time() < deadline:
                    ready, _, _ = select.select([self.connection], [], [], 0.02)
                    if ready and self.connection.recv(1, socket.MSG_PEEK) == b"":
                        outer.disconnected.set()
                        return
                self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def on_switch():
    fake = FakeHealth({"switchedOn": True, "disabledAgents": []})
    switch, logs = make_switch(fake)
    switch.poll_once()
    return fake, switch, logs


class AbortSemanticsTests(unittest.TestCase):
    """Fix pass defect 1: prove the cancellation actually reaches the engine side."""

    def test_engine_sees_hangup_mid_prefill_with_request_id(self):
        vllm = HangupDetectingVllm()
        self.addCleanup(vllm.close)
        fake, switch, _ = on_switch()
        service = CatchupService(vllm_url=vllm.url, model="m", max_context=10000, timeout_s=30, switch=switch)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "prefill me"}]})
            self.assertTrue(vllm.received.wait(3))
            t0 = time.time()
            fake.body = {"switchedOn": False, "disabledAgents": []}
            switch.poll_once()
            self.assertTrue(vllm.disconnected.wait(2), "engine never saw the client hang up")
            self.assertLess(time.time() - t0, 1.0)
            self.assertTrue(wait_until(lambda: service.stats()["inflight"] == 0))
        rid = vllm.headers.get("x-request-id", "")
        self.assertTrue(rid.startswith("kvwarm-"), vllm.headers)
        self.assertIn(f"warm {rid} for eva-dm aborted: engine connection closed", out.getvalue())
        self.assertNotIn("WARNING abort", out.getvalue())

    def test_abort_cuts_body_read_after_connection_close_headers(self):
        # Fix pass 2 reviewer scenario: headers (Connection: close) arrived, body
        # still being read. conn.sock is None by then; the abort must still land.
        vllm = CloseHeaderBodyVllm()
        self.addCleanup(vllm.close)
        fake, switch, _ = on_switch()
        service = CatchupService(vllm_url=vllm.url, model="m", max_context=10000, timeout_s=30, switch=switch)
        service.abort_confirm_s = 1.0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "prefill me"}]})
            self.assertTrue(vllm.headers_sent.wait(3))
            time.sleep(0.1)  # let the client get past getresponse() into the body read
            t0 = time.time()
            fake.body = {"switchedOn": False, "disabledAgents": []}
            switch.poll_once()
            self.assertTrue(vllm.disconnected.wait(2), "engine never saw the client hang up mid-body")
            self.assertLess(time.time() - t0, 1.0)
            self.assertTrue(wait_until(lambda: service.stats()["inflight"] == 0, timeout=2))
            time.sleep(1.2)  # past abort_confirm_s: the watchdog must stay quiet
        rid = vllm.headers.get("x-request-id", "")
        self.assertTrue(rid.startswith("kvwarm-"), vllm.headers)
        self.assertIn(f"warm {rid} for eva-dm aborted: engine connection closed", out.getvalue())
        self.assertNotIn("WARNING abort", out.getvalue())
        self.assertEqual(service.get("eva-dm")["state"], "off")

    def test_abort_landing_during_connect_never_sends_the_prefill(self):
        vllm = HangupDetectingVllm()
        self.addCleanup(vllm.close)
        service = CatchupService(vllm_url=vllm.url, model="m", max_context=10000, timeout_s=30)
        cancel = threading.Event()
        cancel.set()  # abort() ran while conn.sock was still None
        work = {"model": "m", "messages": [{"role": "user", "content": "x"}], "cancel": cancel}
        with self.assertRaises(WarmupAborted):
            service._http_warmup(work)
        time.sleep(0.1)
        self.assertEqual(vllm.requests, 0)

    def test_read_timeout_restored_after_short_connect_timeout(self):
        vllm = HangupDetectingVllm(prefill_s=0.0)
        self.addCleanup(vllm.close)
        seen = []
        real_request = HTTPConnection.request

        def spy(conn, *args, **kwargs):
            seen.append((conn.timeout, conn.sock.gettimeout()))
            return real_request(conn, *args, **kwargs)

        service = CatchupService(vllm_url=vllm.url, model="m", max_context=10000, timeout_s=1800)
        with unittest.mock.patch.object(HTTPConnection, "request", spy):
            service._http_warmup({"model": "m", "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(seen, [(CONNECT_TIMEOUT_S, 1800)])

    def test_watchdog_flags_a_warm_that_ignores_the_abort(self):
        release = threading.Event()

        def stubborn(work):
            release.wait(2)  # ignores work["cancel"]
            return {}

        fake, switch, _ = on_switch()
        service = CatchupService(warmup_fn=stubborn, max_context=10000, switch=switch)
        service.abort_confirm_s = 0.1
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "x"}]})
            fake.body = {"switchedOn": False, "disabledAgents": []}
            switch.poll_once()
            self.assertTrue(wait_until(lambda: "WARNING abort of warm" in out.getvalue(), timeout=2))
            release.set()
            self.assertTrue(wait_until(lambda: service.stats()["inflight"] == 0))
        self.assertEqual(service.get("eva-dm")["state"], "off")


class OffNeverGreenTests(unittest.TestCase):
    """Fix pass defect 2: status/health must not read green/warm while off."""

    def warm_service(self, *sessions):
        fake, switch, _ = on_switch()
        service = CatchupService(warmup_fn=lambda w: {}, max_context=10000, switch=switch)
        for sid in sessions:
            service.submit({"session_id": sid, "messages": [{"role": "user", "content": sid}]})
        self.assertTrue(wait_until(lambda: all(service.get(s)["color"] == "green" for s in sessions)))
        return fake, switch, service

    def test_warm_session_reads_off_while_switched_off_and_warm_again_after(self):
        fake, switch, service = self.warm_service("eva-dm")
        self.assertEqual((service.stats()["state"], service.stats()["color"]), ("on", "green"))
        fake.body = {"switchedOn": False, "disabledAgents": []}
        switch.poll_once()
        self.assertEqual((service.get("eva-dm")["state"], service.get("eva-dm")["color"]), ("off", "off"))
        self.assertEqual([s["color"] for s in service.get()], ["off"])
        self.assertEqual((service.get("never-seen")["state"], service.get("never-seen")["color"]), ("off", "off"))
        self.assertEqual((service.stats()["state"], service.stats()["color"]), ("off", "off"))
        # Re-posting the already-warm snapshot must not short-circuit to green.
        again = service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "eva-dm"}]})
        self.assertEqual((again["state"], again["color"]), ("off", "off"))
        fake.body = {"switchedOn": True, "disabledAgents": []}
        switch.poll_once()
        self.assertEqual(service.get("eva-dm")["color"], "grey")  # parked off -> idle until next snapshot
        service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "eva-dm"}]})
        self.assertTrue(wait_until(lambda: service.get("eva-dm")["color"] == "green"))

    def test_disabled_agent_reads_off_others_stay_green(self):
        fake, switch, service = self.warm_service("kai:background", "eva-dm")
        fake.body = {"switchedOn": True, "disabledAgents": ["kai"]}
        switch.poll_once()
        self.assertEqual(service.get("kai:background")["color"], "off")
        self.assertEqual(service.get("eva-dm")["color"], "green")

    def test_sidecar_http_status_and_health_report_off(self):
        fake, switch, service = self.warm_service("eva-dm")
        fake.body = {"switchedOn": False, "disabledAgents": []}
        switch.poll_once()
        server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(service))
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(f"{base}/v1/status?session_id=eva-dm", timeout=3) as resp:
            status = json.loads(resp.read())
        with urlopen(f"{base}/v1/health", timeout=3) as resp:
            health = json.loads(resp.read())
        self.assertEqual((status["state"], status["color"]), ("off", "off"))
        self.assertEqual((health["state"], health["color"]), ("off", "off"))


class MalformedAgentPolicyTests(unittest.TestCase):
    """Fix pass defect 3: a malformed disabledAgents fails CLOSED, never open."""

    def test_malformed_shapes_fail_closed_even_when_never_known(self):
        for bad in ("kai", {"kai": True}, ["kai", None], ["", "kai"], [42], None):
            body = {"switchedOn": True, "updatedAt": 1}
            if bad is not None:
                body["disabledAgents"] = bad
            switch, logs = make_switch(FakeHealth(body))
            self.assertFalse(switch.poll_once(), bad)
            self.assertFalse(switch.allows("eva-dm"), bad)
            self.assertFalse(switch.allows("kai"), bad)
            self.assertTrue(switch.snapshot()["policy_error"], bad)
            self.assertTrue(any("failing CLOSED" in line for line in logs), (bad, logs))

    def test_malformed_after_kai_disabled_does_not_reenable_kai_and_recovers(self):
        fake = FakeHealth({"switchedOn": True, "disabledAgents": ["kai"]})
        switch, logs = make_switch(fake)
        switch.poll_once()
        fake.body = {"switchedOn": True, "disabledAgents": "kai"}
        switch.poll_once()
        self.assertFalse(switch.allows("kai"))
        self.assertFalse(switch.allows("eva-dm"))
        self.assertEqual(sum("failing CLOSED" in line for line in logs), 1)
        switch.poll_once()  # same error again: no repeat line
        self.assertEqual(sum("failing CLOSED" in line for line in logs), 1)
        fake.body = {"switchedOn": True, "disabledAgents": ["kai"]}
        switch.poll_once()
        self.assertFalse(switch.allows("kai"))
        self.assertTrue(switch.allows("eva-dm"))
        self.assertIn("agent policy well-formed again", " ".join(logs))

    def test_malformed_policy_aborts_inflight_warm(self):
        def warmup(work):
            if work["cancel"].wait(5):
                raise WarmupAborted()
            return {}

        fake, switch, _ = on_switch()
        service = CatchupService(warmup_fn=warmup, max_context=10000, switch=switch)
        service.submit({"session_id": "eva-dm", "messages": [{"role": "user", "content": "x"}]})
        self.assertTrue(wait_until(lambda: service.stats()["inflight"] == 1))
        fake.body = {"switchedOn": True, "disabledAgents": {"oops": 1}}
        switch.poll_once()
        self.assertTrue(wait_until(lambda: service.stats()["inflight"] == 0))
        self.assertEqual(service.get("eva-dm")["color"], "off")
        self.assertEqual(service.stats()["state"], "off")


if __name__ == "__main__":
    unittest.main()
