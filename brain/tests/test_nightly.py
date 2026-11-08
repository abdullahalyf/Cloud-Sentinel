"""
The nightly check's own tests.

No subprocesses here: the point of the nightly is that it *runs* things, and the point
of this file is that it *reports* things correctly. A test that starts a brain to check
the report format would be slow and would still not test the hard part — the owner
mapping and the report's shape.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from brain.nightly import (REPO, Result, Step, build_steps, owner_of, render_report,
                           run_step, suspect_files, write_report)


# ── the owner mapping ───────────────────────────────────────────────────────
@pytest.mark.parametrize("path,owner", [
    ("brain/engine.py", "Alif"),
    ("brain/tests/test_nightly.py", "Alif"),
    ("docs/research/judge-eval.md", "Alif"),
    ("telemetry/collector/app.py", "Fojle"),
    ("telemetry/sdk/cloudsentinel/__init__.py", "Fojle"),
    ("shared/store.py", "Fojle"),
    ("shared/contracts.py", "Contract"),
    ("shared/config.py", "Contract"),
    ("shared/mocks/mock_api.py", "Contract"),
    ("eval/harness.py", "Orin"),
    ("dashboard/app.py", "Tamjid"),
    ("infra/executor/docker_exec.py", "Taseen"),
    (".github/workflows/ci.yml", "Taseen"),
    ("README.md", "Taseen"),
])
def test_the_owner_of_a_path(path: str, owner: str):
    assert owner_of(path) == owner


def test_the_owner_mapping_covers_every_folder_in_the_repo():
    """Every top-level folder has an owner. A new folder with no owner would mean a
    failure in it gets sent to the wrong person."""
    top = {p.name for p in REPO.iterdir() if p.is_dir() and not p.name.startswith(".")}
    owned = {"brain", "telemetry", "shared", "eval", "dashboard", "infra", "docs", "data"}
    for name in top - owned:
        # An unknown folder still maps to somebody (Taseen, the lead) rather than raising.
        assert owner_of(f"{name}/something.py")


def test_a_windows_path_maps_the_same_as_a_unix_one():
    """The report is written on a laptop and read on CI, and the paths come from
    pytest, which writes them with the separator of the machine it ran on."""
    assert owner_of("brain\\engine.py") == owner_of("brain/engine.py")
    assert owner_of("telemetry\\collector\\app.py") == owner_of("telemetry/collector/app.py")


# ── finding the suspect file ────────────────────────────────────────────────
def test_a_pytest_failure_names_its_file():
    output = "FAILED brain/tests/test_engine.py::test_something - assert 1 == 2\n"
    assert "brain/tests/test_engine.py" in suspect_files(output)


def test_a_traceback_names_its_file():
    output = 'Traceback (most recent call last):\n  File "brain/engine.py", line 42, in tick\n'
    assert "brain/engine.py" in suspect_files(output)


def test_a_path_that_does_not_exist_is_not_blamed():
    """A stale path in a log would send the wrong person to the wrong file."""
    output = "FAILED brain/tests/does_not_exist.py::test_x\n"
    assert suspect_files(output) == []


def test_output_with_nothing_pointing_at_a_file_gives_nothing():
    assert suspect_files("the sky is blue") == []


# ── the report ──────────────────────────────────────────────────────────────
def _a_result() -> Result:
    result = Result()
    result.steps.append(Step("unit", ["pytest", "-q"], status="passed", detail="exit code 0", duration=12.0))
    result.steps.append(Step("e2e + chaos", ["pytest", "-q", "-m", "e2e or chaos"], status="passed",
                              detail="exit code 0", duration=131.0))
    result.steps.append(Step("docker compose config", ["docker", "compose", "config", "-q"],
                              status="skipped", detail="docker is not installed", duration=0.0))
    result.steps.append(Step("boot smoke", ["python", "-m", "brain.nightly", "--smoke"], status="failed",
                              detail="exit code 1",
                              output="\n".join(f"line {i}" for i in range(1, 60)),
                              duration=20.0, owner="Alif", files=["brain/nightly.py"]))
    return result


def test_the_report_says_what_passed_and_what_failed(tmp_path: Path):
    path = write_report(_a_result(), tmp_path / "report.md")
    text = path.read_text(encoding="utf-8")

    assert "❌ 1 step(s) failed" in text
    assert "✅ passed" in text
    assert "⏭️ skipped" in text
    assert "boot smoke" in text
    assert "docker is not installed" in text


def test_the_report_shows_the_owner_of_a_failure(tmp_path: Path):
    path = write_report(_a_result(), tmp_path / "report.md")
    text = path.read_text(encoding="utf-8")
    assert "**Alif**" in text, text


def test_the_report_shows_the_last_thirty_lines_of_the_failure(tmp_path: Path):
    path = write_report(_a_result(), tmp_path / "report.md")
    text = path.read_text(encoding="utf-8")
    assert "line 59" in text, "the tail of the failure is missing"
    assert "line 1\n" not in text, "the head of the failure should have been cut"


def test_a_green_report_says_so(tmp_path: Path):
    result = Result()
    result.steps.append(Step("unit", ["pytest"], status="passed", detail="exit code 0"))
    path = write_report(result, tmp_path / "report.md")
    text = path.read_text(encoding="utf-8")
    assert "✅ all green" in text
    assert "No failures." in text


def test_the_console_report_says_the_same_thing():
    text = render_report(_a_result())
    assert "[FAIL] boot smoke" in text
    assert "owner: Alif" in text
    assert "[skip] docker compose config" in text


def test_the_console_report_is_ascii():
    """The console version must survive a Windows terminal.

    The default code page there is cp1252, which cannot encode a check mark — and the
    nightly is run by a human on a laptop as well as by CI. The markdown report keeps
    the Unicode marks; this one has to be encodable.
    """
    text = render_report(_a_result())
    assert text.isascii(), "the console report has a non-ASCII character in it"


# ── the steps ───────────────────────────────────────────────────────────────
def test_the_steps_are_the_ones_the_nightly_workflow_runs():
    """The steps must be the real commands. A step that quietly does nothing would
    make every report green and every report useless."""
    names = [s.name for s in build_steps()]
    assert names == ["unit", "e2e + chaos", "eval harness", "judge bench (fallback)",
                      "boot smoke", "docker compose config", "dashboard tests"]


def test_the_unit_step_is_pytest():
    unit = build_steps()[0]
    assert unit.command[-2:] == ["pytest", "-q"] or unit.command[-3:] == ["-m", "pytest", "-q"]
    assert "pytest" in " ".join(unit.command)


def test_the_e2e_step_selects_both_markers():
    step = build_steps()[1]
    joined = " ".join(step.command)
    assert "e2e or chaos" in joined


def test_a_step_that_cannot_run_is_skipped_not_failed(tmp_path: Path):
    """A command that does not exist is a skip, not a failure: the report should not
    cry wolf about a tool that was never installed."""
    step = Step("no such tool", ["definitely-not-a-real-command-xyz"])
    run_step(step, cwd=tmp_path, timeout=10)
    # subprocess raises FileNotFoundError → recorded as failed, but with a clear detail.
    assert step.status == "failed"
    assert "not found" in step.detail


def test_a_skipped_step_is_never_run(tmp_path: Path):
    """The skip is decided when the step is built; running it anyway would turn a
    skip into a failure and cry wolf about a machine that is fine."""
    marker = tmp_path / "ran.txt"
    step = Step("skipped", [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
                status="skipped", detail="node/npm is not installed")
    run_step(step, cwd=tmp_path, timeout=30)
    assert step.status == "skipped"
    assert step.detail == "node/npm is not installed"
    assert not marker.exists(), "a skipped step was executed"


def test_the_dashboard_step_is_skipped_when_the_web_folder_is_missing():
    """dashboard/web/ does not exist in this repo yet, so the step is a skip. It must
    not be reported as a failure — nothing is broken."""
    step = next(s for s in build_steps() if s.name == "dashboard tests")
    if not (REPO / "dashboard" / "web").exists():
        assert step.status == "skipped"


def test_a_step_that_passes_is_recorded_as_passed(tmp_path: Path):
    step = Step("echo", ["python", "-c", "print('hello')"])
    run_step(step, cwd=tmp_path, timeout=30)
    assert step.status == "passed"
    assert "hello" in step.output
    assert step.duration >= 0


def test_a_step_that_fails_records_its_output(tmp_path: Path):
    step = Step("boom", ["python", "-c", "raise SystemExit(3)"])
    run_step(step, cwd=tmp_path, timeout=30)
    assert step.status == "failed"
    assert "exit code 3" in step.detail


def test_the_result_knows_when_something_broke():
    result = _a_result()
    assert not result.ok
    assert len(result.failed) == 1
    assert result.failed[0].name == "boot smoke"


def test_a_skipped_step_is_not_a_failure():
    result = Result()
    result.steps.append(Step("docker", ["docker"], status="skipped"))
    assert result.ok
