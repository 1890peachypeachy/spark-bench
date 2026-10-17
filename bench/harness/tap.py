"""tap — a byte-for-byte passthrough proxy between an agent harness and the engine, one per agent session.

It changes nothing on the way through (except in ``venice`` mode, used only to dry-run the plumbing against a hosted
endpoint). It records, per LLM request: path, status, seconds, whether the request asked for thinking, the reply's usage,
the tool calls the reply made, and how much reasoning text came back. A process-wide semaphore keeps at most
``MAX_IN_FLIGHT`` upstream requests open across every tap, whatever the harnesses do in parallel.

Works for the OpenAI chat route (``/v1/chat/completions``, JSON or SSE) and Anthropic's Messages route (``/v1/messages``,
JSON or typed SSE events).
"""
from __future__ import annotations

import http.client
import http.server
import json
import threading
import time
import urllib.parse

MAX_IN_FLIGHT = 4
_slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)
_DROP_REQ = {"host", "content-length", "accept-encoding", "connection", "keep-alive", "proxy-connection"}
_DROP_RESP = {"transfer-encoding", "content-length", "connection", "content-encoding", "keep-alive"}


def thinking_asked(body: dict) -> bool | None:
    """What the request asked for: True/False, or None when it says nothing (the engine's default then applies)."""
    if not isinstance(body, dict):
        return None
    th = body.get("thinking")
    if isinstance(th, dict) and isinstance(th.get("type"), str):  # Anthropic shape (also pi's "deepseek" format)
        return th["type"] != "disabled"
    kw = body.get("chat_template_kwargs")
    if isinstance(kw, dict):
        for k in ("enable_thinking", "thinking"):
            if isinstance(kw.get(k), bool):
                return kw[k]
    eff = body.get("reasoning_effort")
    if eff is not None:
        return str(eff) not in ("none", "minimal")
    vp = body.get("venice_parameters")
    if isinstance(vp, dict) and "disable_thinking" in vp:
        return not vp["disable_thinking"]
    return None


def parse_reply(raw: bytes, ctype: str) -> dict:
    """Usage, tool calls, finish, reasoning/content sizes of one reply (OpenAI or Anthropic, JSON or SSE)."""
    out = {"prompt_tokens": None, "completion_tokens": None, "tool_calls": 0, "tool_names": [],
           "reasoning_chars": 0, "content_chars": 0, "finish": None}
    text = raw.decode(errors="replace")
    events = []
    if "text/event-stream" in ctype or text.lstrip().startswith(("data:", "event:")):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                p = line[5:].strip()
                if p and p != "[DONE]":
                    try:
                        events.append(json.loads(p))
                    except json.JSONDecodeError:
                        pass
    else:
        try:
            events.append(json.loads(text))
        except json.JSONDecodeError:
            return out
    oa_calls: dict[int, str] = {}
    for d in events:
        if not isinstance(d, dict):
            continue
        u = d.get("usage") or (d.get("message") or {}).get("usage")
        if isinstance(u, dict):
            if "prompt_tokens" in u:
                out["prompt_tokens"] = u.get("prompt_tokens")
                out["completion_tokens"] = u.get("completion_tokens")
            else:  # Anthropic: input at message_start, output (cumulative) at message_delta
                if u.get("input_tokens") is not None:
                    out["prompt_tokens"] = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
                        + (u.get("cache_creation_input_tokens") or 0)
                if u.get("output_tokens") is not None:
                    out["completion_tokens"] = u["output_tokens"]
        # OpenAI
        for ch in d.get("choices") or []:
            m = ch.get("delta") or ch.get("message") or {}
            out["content_chars"] += len(m.get("content") or "")
            out["reasoning_chars"] += len(m.get("reasoning_content") or m.get("reasoning") or "")
            for i, tc in enumerate(m.get("tool_calls") or []):
                idx = tc.get("index", i)
                name = (tc.get("function") or {}).get("name")
                if name or idx not in oa_calls:
                    oa_calls[idx] = name or oa_calls.get(idx) or "?"
            if ch.get("finish_reason"):
                out["finish"] = ch["finish_reason"]
        # Anthropic
        blocks = d.get("content") if d.get("type") == "message" else None
        if d.get("type") == "content_block_start":
            blocks = [d.get("content_block") or {}]
        for b in blocks or []:
            if b.get("type") == "tool_use":
                out["tool_calls"] += 1
                out["tool_names"].append(b.get("name"))
            elif b.get("type") == "thinking":
                out["reasoning_chars"] += len(b.get("thinking") or "")
            elif b.get("type") == "text":
                out["content_chars"] += len(b.get("text") or "")
        if d.get("type") == "content_block_delta":
            dl = d.get("delta") or {}
            out["content_chars"] += len(dl.get("text") or "")
            out["reasoning_chars"] += len(dl.get("thinking") or "")
        if d.get("type") == "message_delta" and (d.get("delta") or {}).get("stop_reason"):
            out["finish"] = d["delta"]["stop_reason"]
        if d.get("type") == "message" and d.get("stop_reason"):
            out["finish"] = d["stop_reason"]
    out["tool_calls"] += len(oa_calls)
    out["tool_names"] += [n for _, n in sorted(oa_calls.items())]
    return out


class Tap:
    """``upstream``: base URL the harness's ``/v1/...`` paths map onto (e.g. ``http://engine:8000/v1``).

    ``force_temperature``: control runs — set ``temperature`` in every request (else nothing is changed).
    ``venice``: dry-run mode for a hosted endpoint — replaces ``chat_template_kwargs`` by the same switch in
    ``venice_parameters`` (thinking as the request asked, no injected system prompt) and the auth by ``api_key``.
    """

    def __init__(self, upstream: str, *, venice: bool = False, api_key: str | None = None, timeout: float = 900.0,
                 force_temperature: float | None = None):
        u = urllib.parse.urlsplit(upstream.rstrip("/"))
        self.scheme, self.netloc, self.prefix = u.scheme, u.netloc, u.path  # prefix replaces the incoming "/v1"
        self.venice, self.api_key, self.timeout = venice, api_key, timeout
        self.force_temperature = force_temperature  # control runs only: the one field the tap then changes
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        tap = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                tap._forward(self, None)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                tap._forward(self, self.rfile.read(n) if n else b"")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def _upstream_path(self, path: str) -> str:
        p = path[3:] if path.startswith("/v1") else path
        return self.prefix + p

    def _forward(self, h, body: bytes | None):
        headers = {k: v for k, v in h.headers.items() if k.lower() not in _DROP_REQ}
        rec = {"path": h.path.split("?")[0], "t": time.time(), "user_agent": h.headers.get("User-Agent")}
        parsed = None
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, dict):
            rec["thinking_asked"] = thinking_asked(parsed)
            rec["stream"] = bool(parsed.get("stream"))
            tools = parsed.get("tools") or []
            rec["n_tools_offered"] = len(tools)
            rec["tools_offered"] = [t.get("name") or (t.get("function") or {}).get("name") or t.get("type")
                                    for t in tools if isinstance(t, dict)]
            rec["system_chars"] = len(json.dumps(parsed.get("system") or [m for m in parsed.get("messages") or []
                                                                         if isinstance(m, dict) and m.get("role") == "system"]))
            rec["model"] = parsed.get("model")
            rec["sampling"] = {k: parsed.get(k) for k in ("temperature", "top_p", "top_k", "max_tokens") if k in parsed}
            if self.force_temperature is not None and "messages" in parsed:
                parsed["temperature"] = self.force_temperature
                body = json.dumps(parsed).encode()
            if self.venice and "messages" in parsed:
                kw = parsed.pop("chat_template_kwargs", None) or {}
                think = bool(kw.get("enable_thinking")) if isinstance(kw, dict) else False
                parsed["venice_parameters"] = {"disable_thinking": not think, "include_venice_system_prompt": False}
                body = json.dumps(parsed).encode()
        if self.venice and self.api_key:
            for k in list(headers):
                if k.lower() in ("authorization", "x-api-key"):
                    del headers[k]
            headers["Authorization"] = f"Bearer {self.api_key}"
        conn_cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        captured = bytearray()
        status = None
        with _slots:
            t0 = time.time()
            c = conn_cls(self.netloc, timeout=self.timeout)
            try:
                c.request(h.command, self._upstream_path(h.path), body=body, headers=headers)
                r = c.getresponse()
                status = r.status
                ctype = r.getheader("Content-Type") or ""
                h.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in _DROP_RESP:
                        h.send_header(k, v)
                h.send_header("Connection", "close")
                h.end_headers()
                h.close_connection = True
                while True:
                    chunk = r.read1(65536)
                    if not chunk:
                        break
                    h.wfile.write(chunk)
                    h.wfile.flush()
                    if len(captured) < 8 << 20:
                        captured += chunk
            except Exception as e:  # upstream or client gone: a data point, the harness sees a closed socket
                rec["error"] = f"{type(e).__name__}: {e}"
                ctype = ""
                if status is None:
                    try:
                        h.send_error(502, "tap: upstream error")
                    except Exception:
                        pass
            finally:
                c.close()  # a session killed mid-reply also cancels its request at the engine
            rec["seconds"] = round(time.time() - t0, 3)
        rec["status"] = status
        if rec["path"].endswith(("/chat/completions", "/messages")) and captured:
            rec.update(parse_reply(bytes(captured), ctype))
        with self.lock:
            self.requests.append(rec)

    def summary(self) -> dict:
        gen = [r for r in self.requests if r["path"].endswith(("/chat/completions", "/messages"))]
        return {"llm_requests": len(gen),
                "other_requests": len(self.requests) - len(gen),
                "errors": sum(1 for r in gen if r.get("error") or (r.get("status") or 0) >= 400),
                "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in gen),
                "completion_tokens": sum(r.get("completion_tokens") or 0 for r in gen),
                "tool_calls": sum(r.get("tool_calls") or 0 for r in gen),
                "reasoning_chars": sum(r.get("reasoning_chars") or 0 for r in gen),
                "thinking_asked": sorted({str(r.get("thinking_asked")) for r in gen})}
