"""eva-core KV catch-up on/off switch, as seen by the sidecar.

eva-core owns the admin switch (settings `kvCatchup.enabled` + `disabledAgents`)
and serves it cheaply at GET /api/kv-catchup/health. The sidecar polls it on a
background thread and caches the last-known state:

- never fetched yet  -> ON (pre-switch behaviour; a cold eva-core must not
  silently stop warming)
- fetch fails/times out -> keep the last-known state, log the failure streak
- switchedOn false   -> CatchupService stops dispatching and aborts in-flight warms
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_EVA_CORE_URL = "http://127.0.0.1:3456"
HEALTH_PATH = "/api/kv-catchup/health"
DEFAULT_POLL_S = 10.0
DEFAULT_TIMEOUT_S = 3.0
ACTOR = "kv-catchup-sidecar"
# Log the first failure of a streak, then every Nth, so a down eva-core does not
# flood the journal at one line per poll.
FAILURE_LOG_EVERY = 30

FetchFn = Callable[[], Mapping[str, Any]]
LogFn = Callable[[str], None]


def _log(line: str) -> None:
    print(line, flush=True)


def agent_of(session_id: str) -> str:
    # Same mapping as eva-core's settings view: "kai:background" -> "kai".
    return str(session_id or "").split(":")[0]


def read_env_file(path: str | os.PathLike) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def resolve_config(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Health URL + service token.

    Token order: EVA_CORE_SERVICE_TOKEN env; then eva-core's own .env
    (SERVICE_TOKEN, then EVA_CORE_TOKEN — the same precedence eva-core's
    server/auth.js uses to check x-service-token); then SERVICE_TOKEN /
    EVA_CORE_TOKEN from this process env.
    """
    env = os.environ if env is None else env
    core_env_path = env.get("EVA_CORE_ENV_FILE") or str(Path.home() / "git" / "eva-core" / ".env")
    core_env = read_env_file(core_env_path)
    token = (
        env.get("EVA_CORE_SERVICE_TOKEN")
        or core_env.get("SERVICE_TOKEN")
        or core_env.get("EVA_CORE_TOKEN")
        or env.get("SERVICE_TOKEN")
        or env.get("EVA_CORE_TOKEN")
        or ""
    ).strip()
    url = (env.get("CATCHUP_SWITCH_URL") or "").strip()
    if not url:
        base = (env.get("EVA_CORE_URL") or core_env.get("EVA_CORE_URL") or "").strip()
        if not base and core_env.get("PORT"):
            base = f"http://127.0.0.1:{core_env['PORT'].strip()}"
        url = (base or DEFAULT_EVA_CORE_URL).rstrip("/") + HEALTH_PATH
    return {"url": url, "token": token}


def http_fetcher(url: str, token: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> FetchFn:
    def fetch() -> Mapping[str, Any]:
        headers = {"accept": "application/json", "x-eva-actor": ACTOR}
        if token:
            headers["x-service-token"] = token
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            exc.close()
            raise RuntimeError(f"HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"unreachable: {exc.reason}") from exc

    return fetch


class CatchupSwitch:
    def __init__(
        self,
        fetch_fn: FetchFn | None = None,
        *,
        poll_s: float = DEFAULT_POLL_S,
        log: LogFn = _log,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._fetch = fetch_fn
        self.poll_s = max(1.0, float(poll_s or DEFAULT_POLL_S))
        self._log = log
        self._now = now or time.time
        self._lock = threading.Lock()
        self._switched_on: bool | None = None  # None = never known
        self._disabled_agents: frozenset[str] = frozenset()
        self._updated_at: Any = None
        self._last_ok_at: float | None = None
        self._failures = 0
        self._last_error: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add_listener(self, fn: Callable[[], None]) -> None:
        """fn() is called whenever the effective policy changes (master on/off or disabledAgents)."""
        self._listeners.append(fn)

    def is_on(self) -> bool:
        with self._lock:
            return self._switched_on is not False

    def allows(self, session_id: str) -> bool:
        with self._lock:
            if self._switched_on is False:
                return False
            return agent_of(session_id) not in self._disabled_agents

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "switched_on": self._switched_on is not False,
                "known": self._switched_on is not None,
                "disabled_agents": sorted(self._disabled_agents),
                "updated_at": self._updated_at,
                "last_ok_at": self._last_ok_at,
                "failures": self._failures,
                "last_error": self._last_error,
                "poll_s": self.poll_s,
            }

    def poll_once(self) -> bool:
        """One fetch. Returns the effective switch state afterwards."""
        if self._fetch is None:
            return self.is_on()
        try:
            body = self._fetch()
            if not isinstance(body, Mapping) or not isinstance(body.get("switchedOn"), bool):
                raise RuntimeError(f"unexpected health body: {json.dumps(body)[:200]}")
        except Exception as exc:  # noqa: BLE001 — any failure keeps last-known state
            self._on_failure(str(exc) or exc.__class__.__name__)
            return self.is_on()
        agents = body.get("disabledAgents") or []
        disabled = frozenset(str(a) for a in agents if isinstance(a, str) and a) if isinstance(agents, list) else frozenset()
        with self._lock:
            previous = self._switched_on is not False
            previous_agents = self._disabled_agents
            recovered = self._failures
            self._switched_on = body["switchedOn"]
            self._disabled_agents = disabled
            self._updated_at = body.get("updatedAt")
            self._last_ok_at = self._now()
            self._failures = 0
            self._last_error = None
            current = self._switched_on
        if recovered:
            self._log(f"[kv-catchup] switch health endpoint reachable again after {recovered} failed poll(s)")
        if current != previous:
            word = "on" if current else "off"
            self._log(
                f"[kv-catchup] switch {word} seen (state source: health endpoint, updatedAt={body.get('updatedAt')})"
            )
        if disabled != previous_agents:
            self._log(
                f"[kv-catchup] disabled agents now {sorted(disabled) or 'none'} (state source: health endpoint)"
            )
        if current != previous or disabled != previous_agents:
            for fn in list(self._listeners):
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    self._log(f"[kv-catchup] switch listener failed: {exc}")
        return current

    def _on_failure(self, error: str) -> None:
        with self._lock:
            self._failures += 1
            self._last_error = error
            failures = self._failures
            known = self._switched_on
        if failures == 1 or failures % FAILURE_LOG_EVERY == 0:
            state = "never known, defaulting ON" if known is None else ("keeping ON" if known else "keeping OFF")
            self._log(f"[kv-catchup] switch health poll failed ({failures}x): {error}; {state}")

    def start(self) -> None:
        if self._fetch is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="kv-catchup-switch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.poll_s)
