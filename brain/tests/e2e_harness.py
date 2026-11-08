"""
The harness for the E2E and chaos suites.

Every test starts **real processes** — a brain, a collector, sometimes an agent — on free
ports, with a temp data directory, and kills them all at the end even when the test fails.
Nothing is mocked: the point of these tests is that the whole thing actually runs.

The two rules that make this reliable:

  * **A free port, found by binding one.** Picking 8000 and hoping is how a test suite
    fails on a machine that already has something on 8000. `free_port()` binds :0, reads
    the port the OS handed out, and closes it — a tiny race, but a far smaller one than a
    fixed port.
  * **Every process is killed in a finally.** A leaked brain keeps writing to the temp
    database and the next test sees its rows. The `Process` fixture tracks what it started
    and stops all of it, in reverse order, however the test ended.

The brain is started with `--fake` (no Docker needed) and `JUDGE_PROVIDER=fallback`, so the
tests measure the *system*, not the judge: a judge that needs an API key would make the
whole suite depend on a secret.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]


def free_port() -> int:
    """A port the OS says is free right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for_port(port: int, timeout: float = 30.0, host: str = "127.0.0.1") -> bool:
    """Wait until something is listening on the port. False if the timeout ran out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.suppress(OSError):
            with socket.create_connection((host, port), timeout=0.5):
                return True
        time.sleep(0.2)
    return False


def wait_for_http(url: str, timeout: float = 30.0) -> Optional[dict]:
    """Wait until the URL answers with JSON. None if the timeout ran out."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            import httpx

            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return r.json()
        except Exception as exc:  # the server is not up yet — that is the normal case
            last = exc
        time.sleep(0.3)
    if last is not None:
        print(f"  (waiting for {url} failed: {last})", file=sys.stderr)
    return None


@dataclass
class Proc:
    """One process the test started."""

    name: str
    popen: subprocess.Popen
    log: Path

    def output(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


TICK_RE = re.compile(r"tick took (\d+) ms")


def tick_durations(text: str) -> list[int]:
    """The tick durations, in milliseconds, out of a brain's log.

    The engine logs one line per tick ("tick took N ms"), so the log is the honest
    record of how long the loop actually took — the process knows better than a
    test that only watches the clock from outside.
    """
    return [int(m) for m in TICK_RE.findall(text)]


def percentile(values: list[int], pct: float) -> float:
    """The p-th percentile of a list of numbers (nearest-rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int(round(pct / 100.0 * len(ordered))))
    return float(ordered[min(rank, len(ordered)) - 1])


@dataclass
class Harness:
    """The processes of one test, and the temp dir they share."""

    tmp: Path
    procs: list[Proc] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    api_port: int = 0
    collector_port: int = 0

    # ── the processes ───────────────────────────────────────────────────────
    def spawn(self, name: str, args: list[str], env: Optional[dict] = None) -> Proc:
        """Start a process and remember it, so it gets killed however the test ends."""
        log = self.tmp / f"{name}.log"
        full_env = dict(os.environ)
        full_env.update(self.env)
        full_env.update(env or {})
        handle = log.open("wb")
        popen = subprocess.Popen(args, cwd=str(REPO), env=full_env,
                                 stdout=handle, stderr=subprocess.STDOUT)
        proc = Proc(name, popen, log)
        self.procs.append(proc)
        return proc

    def stop(self, proc: Proc, timeout: float = 10.0) -> None:
        """Stop one process, hard if it does not go on its own."""
        if proc.popen.poll() is not None:
            return
        proc.popen.terminate()
        try:
            proc.popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.popen.kill()
            with contextlib.suppress(Exception):
                proc.popen.wait(timeout=5)

    def stop_all(self) -> None:
        """Stop everything, newest first — a brain that depends on the collector should
        go before the collector does."""
        for proc in reversed(self.procs):
            self.stop(proc)
        self.procs.clear()

    def killed(self, name: str) -> bool:
        """Kill a process the way a crash would: no cleanup, no goodbye."""
        for proc in self.procs:
            if proc.name == name:
                proc.popen.kill()
                with contextlib.suppress(Exception):
                    proc.popen.wait(timeout=5)
                return True
        return False

    def alive(self, name: str) -> bool:
        return any(p.name == name and p.popen.poll() is None for p in self.procs)

    # ── the brain ───────────────────────────────────────────────────────────
    def start_brain(self, extra_env: Optional[dict] = None, wait: bool = True) -> Proc:
        """The brain with the fake fleet, on its own port, on the temp database."""
        self.api_port = free_port()
        env = {"CS_API_PORT": str(self.api_port), "LOCAL_DB_PATH": str(self.tmp / "fleet.db"),
               "JUDGE_PROVIDER": "fallback", "CS_EXECUTOR": "fake",
               "PYTHONUNBUFFERED": "1"}
        env.update(extra_env or {})
        proc = self.spawn("brain", [sys.executable, "-m", "brain", "--fake", "--no-auto-rogue"], env)
        if wait:
            assert wait_for_http(f"http://127.0.0.1:{self.api_port}/v1/health", 40), (
                f"the brain did not come up\n{proc.output()[-3000:]}")
        return proc

    def start_collector(self, wait: bool = True) -> Proc:
        """The OTLP collector, on its own port."""
        self.collector_port = free_port()
        env = {"CS_COLLECTOR_PORT": str(self.collector_port),
               "LOCAL_DB_PATH": str(self.tmp / "fleet.db"), "PYTHONUNBUFFERED": "1"}
        proc = self.spawn("collector", [sys.executable, "-m", "telemetry.collector"], env)
        if wait:
            assert wait_for_port(self.collector_port, 30), (
                f"the collector did not come up\n{proc.output()[-3000:]}")
        return proc

    # ── talking to it ───────────────────────────────────────────────────────
    def api(self, path: str, method: str = "GET", body: Optional[dict] = None):
        import httpx

        url = f"http://127.0.0.1:{self.api_port}{path}"
        if method == "GET":
            return httpx.get(url, timeout=10.0)
        return httpx.request(method, url, json=body, timeout=10.0)

    def json_api(self, path: str, method: str = "GET", body: Optional[dict] = None) -> dict:
        r = self.api(path, method, body)
        r.raise_for_status()
        return r.json()

    def fleet(self) -> list[dict]:
        return self.json_api("/v1/fleet").get("agents", [])

    def state(self, agent_id: str) -> Optional[str]:
        for a in self.fleet():
            if a.get("agent_id") == agent_id:
                return a.get("state")
        return None

    def wait_for_state(self, agent_id: str, wanted: set[str], timeout: float = 20.0) -> Optional[str]:
        """Wait until the agent is in one of the wanted states. None if the timeout ran out."""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = self.state(agent_id)
                if last in wanted:
                    return last
            except Exception:
                pass
            time.sleep(0.5)
        return last

    def command(self, agent_id: str, command: str, params: Optional[dict] = None) -> None:
        # "terminal" is the requester for a human driving the fleet from a shell, which is
        # what the test is. The API only accepts a known set of requesters.
        self.json_api(f"/v1/agents/{agent_id}/commands", "POST",
                      {"command": command, "params": params or {}, "requested_by": "terminal"})

    # ── what the brain is doing ─────────────────────────────────────────────
    def tick_ms(self) -> list[int]:
        """The tick durations the brain logged, in milliseconds."""
        return tick_durations(self.procs[0].output() if self.procs else "")

    def tick_p95(self) -> float:
        """The p95 tick duration, in milliseconds.

        Read out of the brain's own log: the process knows how long its tick took, and
        a test that only watches the clock from outside would miss a tick that took
        400 ms because the machine was busy.
        """
        return percentile(self.tick_ms(), 95)

    def alerts(self) -> list[dict]:
        return self.json_api("/v1/alerts").get("items", [])

    def db_path(self) -> Path:
        """The SQLite file the brain and the collector share."""
        return self.tmp / "fleet.db"

    # ── the MCP server, over stdio ──────────────────────────────────────────
    def mcp_call(self, tool: str, arguments: Optional[dict] = None,
                 api_url: Optional[str] = None, timeout: float = 60.0) -> dict:
        """Call one MCP tool over stdio and return the JSON-RPC reply.

        The stdin pipe is kept open for the whole exchange. That is not a detail: the
        stdio transport reads until EOF, so a server fed a closed stdin answers
        `initialize` and then exits before the tool call comes back. A client that keeps
        the pipe open gets the reply.
        """
        env = dict(os.environ)
        env["CS_API_URL"] = api_url or f"http://127.0.0.1:{self.api_port}"
        env["PYTHONPATH"] = str(REPO)
        env["CS_MCP_READONLY"] = "true"

        proc = subprocess.Popen([sys.executable, "-m", "brain.mcp_server"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, cwd=str(REPO), env=env, text=True)
        try:
            def send(obj: dict) -> None:
                proc.stdin.write(json.dumps(obj) + "\n")
                proc.stdin.flush()

            def read_reply(deadline: float) -> Optional[dict]:
                while time.time() < deadline:
                    line = proc.stdout.readline()
                    if not line:
                        return None
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            return json.loads(line)
                        except json.JSONDecodeError:
                            continue
                return None

            send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "e2e", "version": "1"}}})
            init = read_reply(time.time() + timeout)
            assert init is not None, "the MCP server did not answer initialize"

            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": tool, "arguments": arguments or {}}})
            return read_reply(time.time() + timeout)
        finally:
            with contextlib.suppress(Exception):
                proc.stdin.close()
            proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
