"""
Nightly integration check (task A10).   Owner: Alif.

Runs every check the team relies on, in order, and writes data/nightly-report.md:
  1. python -m pytest -q
  2. python -m pytest -q -m "e2e or chaos"      (exit code 5 = "no tests yet" counts as a pass)
  3. python -m eval.harness
  4. python -m brain.judge_bench --judge fallback
  5. a 20 s `python -m brain --fake` boot smoke (/v1/health and /v1/fleet must answer)
  6. docker compose config -q                    (skipped without docker)
  7. cd dashboard/web && npm ci && npm test      (skipped without node or without the folder)

Every failing test or step is mapped to the owner of its folder, so the report says who must look.
The exit code is 1 if anything failed.

    python -m brain.nightly
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import httpx

from shared.config import settings

ROOT = Path(__file__).resolve().parent.parent
TAIL_LINES = 30
BOOT_SECONDS = 20.0

# Folder prefix -> owner (same table as AGENTS.md "Folder ownership"). First match wins.
OWNERS: list[tuple[str, str]] = [
    ("brain/", "Alif"),
    ("shared/", "Alif + Taseen (contract)"),
    ("telemetry/", "Fojle"),
    ("dashboard/", "Tamjid"),
    ("eval/", "Orin"),
    ("infra/", "Taseen"),
    (".github/", "Taseen"),
]
DEFAULT_OWNER = "Taseen"  # integration lead owns everything else

# Who owns a whole step when it fails without naming a test file.
STEP_OWNERS = {
    "pytest": DEFAULT_OWNER,
    "e2e + chaos": "Alif",
    "eval harness": "Orin",
    "judge bench": "Alif",
    "boot smoke": "Alif",
    "compose config": "Taseen",
    "npm test": "Tamjid",
}

_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)


@dataclass
class StepResult:
    name: str
    status: str  # "pass" | "fail" | "skip"
    seconds: float
    output: str  # error tail (fail), skip reason (skip), or "" (pass)
    failed: list[str] = field(default_factory=list)  # failing test ids, if any


# ── small pure helpers (unit-tested) ──────────────────────────────────────────
def owner_for(path: str) -> str:
    """Owner of a file or test id, by its folder."""
    for prefix, owner in OWNERS:
        if path.startswith(prefix):
            return owner
    return DEFAULT_OWNER


def failed_tests(output: str) -> list[str]:
    """Test ids from pytest's short summary ('FAILED x::y - msg' / 'ERROR x::y')."""
    return _FAILED.findall(output)


def status_for(returncode: int, allow_no_tests: bool) -> str:
    if returncode == 0 or (allow_no_tests and returncode == 5):
        return "pass"
    return "fail"


def tail(text: str, lines: int = TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def exit_code(results: list[StepResult]) -> int:
    return 1 if any(r.status == "fail" for r in results) else 0


def render_report(results: list[StepResult], when: str) -> str:
    """Markdown report: summary table, who must act, then the error tail of each failed step."""
    failed = [r for r in results if r.status == "fail"]
    verdict = "✅ all green" if not failed else f"❌ {len(failed)} failed"
    icon = {"pass": "✅", "fail": "❌", "skip": "⏭️"}
    out = [f"# Nightly report · {when}", "", f"**Result: {verdict}**", "",
           "| Step | Status | Seconds | Note |", "|---|---|---|---|"]
    for r in results:
        note = r.output.splitlines()[0][:80] if r.status == "skip" and r.output else ""
        out.append(f"| {r.name} | {icon[r.status]} {r.status} | {r.seconds:.1f} | {note} |")
    if failed:
        out += ["", "## Who must look", "", "| Failing | Owner |", "|---|---|"]
        for r in failed:
            if r.failed:
                out += [f"| `{t}` | {owner_for(t)} |" for t in r.failed]
            else:
                out.append(f"| {r.name} | {STEP_OWNERS.get(r.name, DEFAULT_OWNER)} |")
        out += ["", "## Error tails"]
        for r in failed:
            out += ["", f"### {r.name}", "```", tail(r.output), "```"]
    return "\n".join(out) + "\n"


# ── steps (these run real subprocesses) ───────────────────────────────────────
def _run(name: str, cmd: list[str], cwd: Path = ROOT, allow_no_tests: bool = False,
         timeout: float = 900, env: Optional[dict] = None) -> StepResult:
    start = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        code, output = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        code, output = 124, f"timed out after {timeout:.0f} s\n{e.stdout or ''}"
    status = status_for(code, allow_no_tests)
    secs = time.monotonic() - start
    if status == "pass":
        return StepResult(name, "pass", secs, "")
    return StepResult(name, "fail", secs, tail(output), failed_tests(output))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def boot_smoke(seconds: float = BOOT_SECONDS) -> StepResult:
    """Start `python -m brain --fake` on a free port with a throwaway DB; /v1/health and /v1/fleet must answer."""
    start = time.monotonic()
    port = _free_port()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "CS_API_PORT": str(port), "LOCAL_DB_PATH": str(Path(tmp) / "nightly.db")}
        log = Path(tmp) / "brain.log"
        with log.open("w") as fh:
            proc = subprocess.Popen([sys.executable, "-m", "brain", "--fake"], cwd=ROOT, env=env,
                                    stdout=fh, stderr=subprocess.STDOUT)
        headers = {"X-CS-Token": settings.api_token} if settings.api_token else {}
        base = f"http://127.0.0.1:{port}"
        error = "brain never answered"
        try:
            while time.monotonic() - start < seconds:
                if proc.poll() is not None:
                    error = f"brain exited early with code {proc.returncode}"
                    break
                try:
                    health = httpx.get(f"{base}/v1/health", headers=headers, timeout=2)
                    fleet = httpx.get(f"{base}/v1/fleet", headers=headers, timeout=2)
                    if health.status_code == 200 and fleet.status_code == 200 and fleet.json():
                        return StepResult("boot smoke", "pass", time.monotonic() - start, "")
                    error = f"health {health.status_code}, fleet {fleet.status_code} {fleet.text[:200]}"
                except (httpx.HTTPError, ValueError) as e:
                    error = f"{type(e).__name__}: {e}"
                time.sleep(1)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        output = f"{error}\n--- brain log ---\n{log.read_text(errors='replace')}"
    return StepResult("boot smoke", "fail", time.monotonic() - start, tail(output))


def compose_config() -> StepResult:
    if not shutil.which("docker"):
        return StepResult("compose config", "skip", 0.0, "docker not installed")
    return _run("compose config", ["docker", "compose", "config", "-q"], timeout=120)


def npm_test() -> StepResult:
    web = ROOT / "dashboard" / "web"
    if not (web / "package.json").exists():
        return StepResult("npm test", "skip", 0.0, "dashboard/web not there yet")
    if not shutil.which("npm"):
        return StepResult("npm test", "skip", 0.0, "node/npm not installed")
    ci = _run("npm test", ["npm", "ci"], cwd=web, timeout=600)
    return ci if ci.status == "fail" else _run("npm test", ["npm", "test"], cwd=web, timeout=600)


def steps() -> list[Callable[[], StepResult]]:
    py = sys.executable
    return [
        lambda: _run("pytest", [py, "-m", "pytest", "-q"]),
        lambda: _run("e2e + chaos", [py, "-m", "pytest", "-q", "-m", "e2e or chaos"], allow_no_tests=True),
        lambda: _run("eval harness", [py, "-m", "eval.harness"], timeout=300),
        lambda: _run("judge bench", [py, "-m", "brain.judge_bench", "--judge", "fallback"], timeout=300),
        boot_smoke,
        compose_config,
        npm_test,
    ]


def report_path() -> Path:
    """data/nightly-report.md, next to the local DB (data/ is git-ignored)."""
    return ROOT / Path(settings.local_db_path).parent / "nightly-report.md"


def main() -> int:
    results: list[StepResult] = []
    for step in steps():
        r = step()
        print(f"{r.status:>4}  {r.name}  ({r.seconds:.1f} s)", flush=True)
        results.append(r)
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(results, datetime.now().strftime("%Y-%m-%d %H:%M")), encoding="utf-8")
    print(f"report: {path}")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
