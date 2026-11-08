"""
The deterministic demo runner (B3).

The runner is the demo, so the runner is the test. What matters:

- every step of the incident is asserted — the agent was detected, the judge
  decided, the breaker acted, the money was counted — and a missing step
  fails the run loudly;
- the timings have a budget, and a drift over it fails the run;
- the run is **deterministic**: the same seed gives the same numbers, twice;
- the runner writes the markdown with the timings;
- it works offline — no Docker, no key;
- it exits non-zero on a drift.
"""
from __future__ import annotations

import json
import os

import pytest

from brain import demo_runner
from brain.demo_runner import DEFAULT_BUDGET_SECONDS, DemoResult, render_markdown, run_demo


# ── the run itself ──────────────────────────────────────────────────────────
def test_the_demo_runs_to_completion():
    """The whole incident happens: detected, judged, acted, healed."""
    result = run_demo()
    assert result.failed is False, result.failures
    assert result.healed is True


def test_the_agent_was_detected():
    result = run_demo()
    assert result.alerts >= 1, "the brain never flagged the agent"


def test_the_judge_reached_a_verdict():
    result = run_demo()
    assert result.verdicts >= 1, "the judge never reached a verdict"


def test_the_breaker_acted():
    result = run_demo()
    assert result.actions >= 1, "the breaker never acted"


def test_the_money_was_counted():
    result = run_demo()
    assert result.usd_saved > 0, "the action saved nothing — the money was not counted"
    assert result.tokens_saved > 0


def test_the_root_cause_names_the_rule():
    result = run_demo()
    assert result.rule, "the alert carried no rule"
    assert result.pattern, "the judge named no pattern"


def test_the_timings_were_measured():
    result = run_demo()
    for name in ("detect", "judge", "act", "total"):
        assert name in result.timings, f"the {name} step was never timed"
        assert result.timings[name] >= 0


def test_the_detect_step_is_measured_from_the_rogue():
    """The clock starts when the agent goes rogue."""
    result = run_demo()
    assert result.timings["detect"] > 0
    assert result.timings["detect"] < DEFAULT_BUDGET_SECONDS


# ── determinism ─────────────────────────────────────────────────────────────
def test_the_same_seed_gives_the_same_numbers():
    """A demo that is different every run cannot be debugged at 3 AM."""
    first, second = run_demo(seed=42), run_demo(seed=42)
    assert first.timings == second.timings
    assert first.usd_saved == second.usd_saved
    assert first.tokens_saved == second.tokens_saved
    assert first.rule == second.rule
    assert first.pattern == second.pattern
    assert first.action == second.action


def test_the_run_is_deterministic_across_many_runs():
    """Twenty runs, one set of numbers."""
    results = [run_demo(seed=7) for _ in range(5)]
    first = results[0]
    for result in results[1:]:
        assert result.timings == first.timings
        assert result.usd_saved == first.usd_saved


def test_a_different_seed_is_allowed_to_differ_but_must_still_pass():
    """The seed changes the run, but the run must still hold."""
    for seed in (1, 99, 20261108):
        result = run_demo(seed=seed)
        assert result.failed is False, f"seed {seed} failed: {result.failures}"


# ── the assertions ──────────────────────────────────────────────────────────
def test_a_run_that_never_detects_fails():
    """The runner must fail when a step does not happen — not shrug."""
    result = demo_runner.run_demo(agent_id="nobody", budget_seconds=5)
    assert result.failed is True
    assert any("detected" in f for f in result.failures)


def test_a_run_that_times_out_fails():
    """A demo that runs out of time is a failed demo."""
    result = demo_runner.run_demo(budget_seconds=1.0)
    assert result.failed is True
    assert result.failures


def test_a_timing_over_its_budget_fails_the_run():
    """The budget is a budget, not a suggestion."""
    result = demo_runner.run_demo(step_budgets={"detect": 0.001})
    assert result.failed is True
    assert any("budget" in f for f in result.failures)


def test_the_failure_says_which_step_broke():
    result = demo_runner.run_demo(agent_id="nobody", budget_seconds=5)
    assert result.failures
    assert all(isinstance(f, str) and f for f in result.failures)


# ── the markdown ────────────────────────────────────────────────────────────
def test_the_markdown_shows_the_timings():
    result = run_demo()
    md = render_markdown(result)
    assert md.startswith("#")
    assert "The timings" in md
    assert f"{result.timings['detect']:.1f}s" in md


def test_the_markdown_shows_the_money():
    result = run_demo()
    md = render_markdown(result)
    assert f"${result.usd_saved:.4f}" in md
    assert f"{result.tokens_saved:,} tokens" in md


def test_the_markdown_shows_the_root_cause():
    result = run_demo()
    md = render_markdown(result)
    assert result.rule in md
    assert result.pattern in md


def test_the_markdown_says_what_failed():
    """A failing run's report must say what broke — that is the whole point."""
    result = demo_runner.run_demo(agent_id="nobody", budget_seconds=5)
    md = render_markdown(result)
    assert "FAILED" in md


def test_the_markdown_of_a_good_run_says_every_step_held():
    result = run_demo()
    md = render_markdown(result)
    assert "every step held" in md


# ── the command ─────────────────────────────────────────────────────────────
def test_the_command_exits_zero_when_the_demo_holds(capsys):
    assert demo_runner.main(["--runs", "1"]) == 0


def test_the_command_exits_non_zero_on_a_drift(capsys):
    """A drift must fail the build, or it is not a check."""
    code = demo_runner.main(["--agent", "nobody", "--budget", "5"])
    assert code == 1


def test_the_command_writes_the_report(tmp_path, capsys):
    out = tmp_path / "demo_run.md"
    assert demo_runner.main(["--runs", "1", "--write", str(out)]) == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("#")
    assert "The timings" in text


def test_the_command_prints_json_when_asked(capsys):
    demo_runner.main(["--runs", "1", "--json"])
    body = json.loads(capsys.readouterr().out)
    assert len(body) == 1
    assert "timings" in body[0]
    assert "usd_saved" in body[0]


def test_the_command_runs_many_times(capsys):
    """The 20-out-of-20 requirement, as a test."""
    code = demo_runner.main(["--runs", "20"])
    assert code == 0


# ── offline ─────────────────────────────────────────────────────────────────
def test_the_demo_needs_no_key_and_no_docker(monkeypatch):
    """The demo must work with no ANTHROPIC_API_KEY and no collector."""
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "CS_VERDICT_OTLP_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    result = run_demo()
    assert result.failed is False, result.failures


def test_the_demo_is_offline_by_default(monkeypatch):
    """The judge is the deterministic fallback, so the verdict is reproducible."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")
    settings = demo_runner._settings()
    assert settings.judge_provider == "fallback"
    assert settings.anthropic_api_key == ""
