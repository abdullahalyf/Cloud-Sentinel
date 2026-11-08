"""
The nightly integration check: `python -m brain.nightly`.

One command that runs everything the project has, in order, and says plainly what
passed and what did not. The nightly workflow runs this so that a broken night is a
report, not a silence.

**Why it exists.** The unit tests are green and the E2E suite is green, and yet
something is broken at 2 a.m. — the eval harness needs a key it does not have, the
dashboard's npm test needs Node, the brain does not boot with the real executor. Each
of those is a real failure of the *product*, and none of them is a failure of any one
test. This is the check that runs the whole thing and reports.

**Two rules it follows.**

  * **It reports; it does not guess.** Every step's output is captured and the last
    30 lines of a failure are written to the report, because "it failed" is not
    actionable and "it failed with this traceback" is.
  * **A failure is mapped to an owner.** The repo is split into folders and each
    folder belongs to one person (AGENTS.md). A failure in `telemetry/` is Fojle's to
    fix, a failure in `dashboard/` is Tamjid's. The report says which, so the right
    person reads it — and the nightly agent never edits somebody else's folder.

**Skips are not failures.** No Docker, no Node, no `dashboard/web/` — those steps are
skipped and marked as such, because a machine without Docker is not a broken product.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "data" / "nightly-report.md"

# ── who owns which folder (AGENTS.md) ───────────────────────────────────────
OWNERS: list[tuple[str, str, tuple[str, ...]]] = [
    ("fojle", "Fojle", ("telemetry/",)),
    ("orin", "Orin", ("eval/",)),
    ("tamjid", "Tamjid", ("dashboard/",)),
    ("alif", "Alif", ("brain/", "docs/research/")),
    ("contract", "Contract", ("shared/",)),
    ("taseen", "Taseen", ()),   # Taseen owns everything else
]


def owner_of(path: str) -> str:
    """The name of the person who owns the file at `path`.

    The order matters: `shared/store.py` is Fojle's, `shared/contracts.py` is the
    contract's, and `shared/mocks/` is the contract's too. The first match wins, so
    the more specific folders are listed first.
    """
    norm = str(path).replace("\\", "/").strip()
    if norm.startswith("telemetry/"):
        return "Fojle"
    if norm == "shared/store.py":
        return "Fojle"
    if norm.startswith("eval/"):
        return "Orin"
    if norm.startswith("dashboard/"):
        return "Tamjid"
    if norm.startswith("brain/") or norm.startswith("docs/research/"):
        return "Alif"
    if norm.startswith("shared/"):
        return "Contract"
    if norm.startswith(".github/") or norm.startswith("infra/"):
        return "Taseen"
    return "Taseen"   # anything else: the lead decides


# ── the steps ───────────────────────────────────────────────────────────────
@dataclass
class Step:
    """One check, and how it went."""

    name: str
    command: list[str]
    status: str = "pending"      # passed | failed | skipped
    detail: str = ""
    output: str = ""
    duration: float = 0.0
    owner: str = ""
    files: list[str] = field(default_factory=list)
    cwd: Optional[Path] = None

    @property
    def ok(self) -> bool:
        return self.status in ("passed", "skipped")


@dataclass
class Result:
    """Everything a run did, so the report can be written from it."""

    steps: list[Step] = field(default_factory=list)

    @property
    def failed(self) -> list[Step]:
        return [s for s in self.steps if s.status == "failed"]

    @property
    def ok(self) -> bool:
        return not self.failed


# ── the runners ─────────────────────────────────────────────────────────────
def run_step(step: Step, cwd: Path = REPO, timeout: int = 900) -> Step:
    """Run one step and record what happened. A step never raises.

    A step that was already marked *skipped* is not run at all — the skip is a decision
    made when the step was built ("this tool is not installed here"), and running it
    anyway would turn a skip into a failure and cry wolf about a machine that is fine.
    """
    if step.status == "skipped":
        return step

    started = time.time()
    try:
        proc = subprocess.run(step.command, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, env=_env())
    except subprocess.TimeoutExpired as exc:
        step.status = "failed"
        step.detail = f"timed out after {timeout}s"
        step.output = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else ""
    except FileNotFoundError as exc:
        step.status = "failed"
        step.detail = f"command not found: {exc}"
    except OSError as exc:
        # On Windows a command may exist but not be executable by CreateProcess (npm is a
        # .cmd script). That is a missing tool, not a broken product.
        step.status = "failed"
        step.detail = f"could not run: {exc}"
    else:
        step.output = ((proc.stdout or "") + (proc.stderr or ""))
        step.status = "passed" if proc.returncode == 0 else "failed"
        step.detail = f"exit code {proc.returncode}"
    step.duration = time.time() - started
    if step.status == "failed":
        step.files = suspect_files(step.output)
        step.owner = owner_of(step.files[0]) if step.files else "Taseen"
    return step


def _env() -> dict:
    """The environment the steps run in: the repo importable, the key not required."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO}{os.pathsep}{existing}" if existing else str(REPO)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


# ── finding the suspect file ────────────────────────────────────────────────
PYTEST_FILE_RE = re.compile(r"^([A-Za-z0-9_./\\-]+\.py):\d+", re.MULTILINE)
FAILING_RE = re.compile(r"^(?:FAILED|ERROR)\s+([A-Za-z0-9_./\\-]+\.py)", re.MULTILINE)
# A traceback names the file in quotes:  File "brain/engine.py", line 42, in tick
TRACEBACK_RE = re.compile(r'File "([A-Za-z0-9_./\\-]+\.py)"')


def suspect_files(output: str) -> list[str]:
    """The files a failure points at, best first.

    A pytest failure names its file directly ("FAILED brain/tests/test_x.py"). A
    traceback names it in quotes ('File "brain/engine.py", line 42'). Anything else —
    an npm error, a shell message — is read out of the output. An empty list means
    "nobody knows", and the report then says so rather than blaming the wrong person.
    """
    found: list[str] = []

    for pattern in (FAILING_RE, TRACEBACK_RE, PYTEST_FILE_RE):
        for m in pattern.finditer(output):
            path = m.group(1)
            if path not in found:
                found.append(path)

    # Only keep files that exist — a path from a stale log would send the wrong person.
    return [p for p in found if (REPO / p).exists()]


# ── the steps themselves ────────────────────────────────────────────────────
def build_steps() -> list[Step]:
    """The steps, with the ones that need something missing marked as skipped.

    A step whose tool is not installed is *skipped*, not failed: a machine without
    Docker is not a broken product, and a report full of skips nobody can fix trains
    people to ignore the report.
    """
    steps: list[Step] = [
        Step("unit", [sys.executable, "-m", "pytest", "-q"]),
        Step("e2e + chaos", [sys.executable, "-m", "pytest", "-q", "-m", "e2e or chaos"]),
        Step("eval harness", [sys.executable, "-m", "eval.harness"]),
        Step("judge bench (fallback)", [sys.executable, "-m", "brain.judge_bench", "--judge", "fallback"]),
        Step("boot smoke", [sys.executable, "-m", "brain.nightly", "--smoke"]),
    ]

    if shutil.which("docker") is None:
        steps.append(Step("docker compose config", ["docker", "compose", "config", "-q"],
                          status="skipped", detail="docker is not installed"))
    else:
        steps.append(Step("docker compose config", ["docker", "compose", "config", "-q"]))

    web = REPO / "dashboard" / "web"
    if shutil.which("npm") is None:
        steps.append(Step("dashboard tests", ["npm", "test"], status="skipped",
                          detail="node/npm is not installed"))
    elif not web.exists():
        steps.append(Step("dashboard tests", ["npm", "test"], status="skipped",
                          detail="dashboard/web/ does not exist yet"))
    else:
        steps.append(Step("dashboard tests", ["npm", "test"], cwd=web))

    return steps


# ── the boot smoke ──────────────────────────────────────────────────────────
def boot_smoke(seconds: float = 20.0) -> tuple[bool, str]:
    """Start the brain for a moment and check it answers.

    Two things are asked of it: `/v1/health` says it is up, and `/v1/fleet` lists the
    agents. A brain that boots but serves nothing is not a brain that works.
    """
    import json
    import socket
    import urllib.error
    import urllib.request

    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    port = free_port()
    env = _env()
    env.update({"CS_API_PORT": str(port), "JUDGE_PROVIDER": "fallback",
                "LOCAL_DB_PATH": str(REPO / "data" / "nightly-smoke.db")})
    (REPO / "data").mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen([sys.executable, "-m", "brain", "--fake", "--no-auto-rogue"],
                            cwd=str(REPO), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + seconds
        health = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=2) as r:
                    health = json.loads(r.read())
                break
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(0.5)

        if not health:
            return False, "the brain did not answer /v1/health in time"
        if not health.get("ok"):
            return False, f"/v1/health said {health}"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/fleet", timeout=5) as r:
            fleet = json.loads(r.read())
        agents = fleet.get("agents") or []
        if not agents:
            return False, "/v1/fleet listed no agents"
        return True, f"{len(agents)} agents, judge={health.get('judge')}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── the report ──────────────────────────────────────────────────────────────
def write_report(result: Result, path: Path = REPORT) -> Path:
    """Write the report. The format is a checklist, so a glance says what broke."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Nightly report",
        "",
        f"**Result:** {'✅ all green' if result.ok else f'❌ {len(result.failed)} step(s) failed'}",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}  ·  "
        f"total {sum(s.duration for s in result.steps):.0f}s",
        "",
        "| Step | Status | Time | Owner | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in result.steps:
        mark = {"passed": "✅", "failed": "❌", "skipped": "⏭️"}.get(s.status, "•")
        owner = s.owner if s.status == "failed" and s.owner else "—"
        lines.append(f"| {s.name} | {mark} {s.status} | {s.duration:.0f}s | {owner} | {s.detail} |")

    failures = result.failed
    if failures:
        lines += ["", "## Failures", ""]
        for s in failures:
            lines += [
                f"### {s.name}",
                "",
                f"- command: `{' '.join(s.command)}`",
                f"- {s.detail}",
                f"- owner: **{s.owner}**" + (f" (suspect: `{s.files[0]}`)" if s.files else ""),
                "",
                "```",
                *s.output.splitlines()[-30:],
                "```",
                "",
            ]
    else:
        lines += ["", "No failures.", ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_report(result: Result) -> str:
    """The same report, for the console.

    The console version is plain ASCII on purpose: the Windows terminal's default code
    page (cp1252) cannot encode a check mark, and the nightly is run by a human on a
    Windows laptop as well as by CI. The markdown report keeps the nicer marks.
    """
    out = []
    for s in result.steps:
        mark = {"passed": "[ok]", "failed": "[FAIL]", "skipped": "[skip]"}.get(s.status, "[?]")
        out.append(f"{mark} {s.name} ({s.detail}, {s.duration:.0f}s)")
        if s.status == "failed":
            out.append(f"     owner: {s.owner}"
                       + (f" - suspect {s.files[0]}" if s.files else ""))
            for line in s.output.splitlines()[-10:]:
                out.append(f"     | {line}")
    return "\n".join(out)


# ── main ────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m brain.nightly",
                                description="The nightly integration check: run everything, report what broke.")
    p.add_argument("--smoke", action="store_true",
                   help="only the boot smoke (used by the nightly workflow's own step)")
    p.add_argument("--report", default=str(REPORT), help=f"where to write the report (default: {REPORT})")
    p.add_argument("--only", default="", help="run only the steps whose name contains this")
    args = p.parse_args(argv)

    if args.smoke:
        ok, detail = boot_smoke()
        print(f"{'[ok]' if ok else '[FAIL]'} boot smoke: {detail}")
        return 0 if ok else 1

    steps = build_steps()
    if args.only:
        steps = [s for s in steps if args.only.lower() in s.name.lower()]
        if not steps:
            print(f"no step matches {args.only!r}", file=sys.stderr)
            return 2

    result = Result()
    for step in steps:
        # ASCII on the console: the Windows terminal's default code page (cp1252) cannot
        # encode "→", and the nightly is run by a human on a Windows laptop too.
        print(f"-> {step.name} ...", flush=True)
        result.steps.append(run_step(step, cwd=step.cwd or REPO))

    print()
    print(render_report(result))
    path = write_report(result, Path(args.report))
    print(f"\nreport: {path}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
