"""
Acceptance tests for C1: the judge-eval CI runner.

**What is actually being tested.** The dangerous failure mode of this module
is not a crash — it is a *plausible lie*. If the API key is missing, or the
provider is unreachable, and the runner falls back to the offline judge, the
pack would then carry "Claude: 0 ms, $0.00" — which is both wrong and
exactly the thing `test_the_pack_does_not_quote_a_claude_judge_number` exists
to catch.

So most of these tests are about **refusal**: the runner must refuse to write
a number it did not measure, and the pack must come out untouched.

No network, no API key: the live half is marked `live` and skips.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from brain.judge_eval_ci import (CLAUDE_MODELS, JSON_OUT, PACK, PACK_BEGIN, PACK_END,
                                 ModelResult, RunReport, block_markdown, run_all, run_model,
                                 update_disclaimer, update_pack)
from shared.config import load_settings

PACK_PATH = Path("docs/research/pitch-numbers.md")


# ── the pack has the markers the machine writes into ───────────────────────
def test_the_pack_has_the_claude_markers():
    """
    The pack is where the numbers go, and the machine writes them between two
    markers. If the markers are missing, `update_pack` raises — so this test
    is about the file, not the function.
    """
    text = PACK_PATH.read_text(encoding="utf-8")
    assert PACK_BEGIN in text, f"the pack has no {PACK_BEGIN} marker"
    assert PACK_END in text, f"the pack has no {PACK_END} marker"


def test_the_markers_are_in_the_right_order():
    text = PACK_PATH.read_text(encoding="utf-8")
    assert text.index(PACK_BEGIN) < text.index(PACK_END), "the markers are the wrong way round"


def test_the_pack_still_disclaims_the_numbers_it_does_not_have():
    """
    The pack's limits section has to name "Claude", "revenue" and
    "competitor" — `test_the_pack_says_what_it_does_not_claim` requires all
    three. The CI updater replaces one line, never the whole list.
    """
    text = PACK_PATH.read_text(encoding="utf-8")
    assert "does not claim" in text.lower()
    for limit in ("Claude", "revenue", "competitor"):
        assert limit.lower() in text.lower(), f"the pack does not disclaim {limit}"


# ── the models the runner covers ────────────────────────────────────────────
def test_every_claude_model_has_a_price():
    """
    A model with no price in `shared/pricing.py` would be costed at the
    default rate — which would put a *wrong* dollar figure in the pack. The
    runner's whole value is that the numbers are real, so every model it runs
    has to be priceable.
    """
    from shared.pricing import PRICES_PER_MTOK
    for model in CLAUDE_MODELS:
        assert model in PRICES_PER_MTOK, f"{model} has no price in shared/pricing.py"


def test_the_model_list_is_not_empty_and_has_no_duplicates():
    assert CLAUDE_MODELS
    assert len(CLAUDE_MODELS) == len(set(CLAUDE_MODELS))


# ── the block that gets written ─────────────────────────────────────────────
def _report(**kwargs) -> RunReport:
    report = RunReport(started_at="2026-11-08 12:00 UTC", runs_per_incident=3, key_present=True)
    report.models.append(ModelResult(
        model="claude-haiku-5-5", ok=True, precision=0.9, recall=0.8, f1=0.85,
        accuracy=0.87, latency_p50_ms=120.0, latency_p95_ms=300.0,
        cost_per_verdict_usd=0.0001, cost_total_usd=0.021, n_incidents=70,
    ))
    for k, v in kwargs.items():
        setattr(report, k, v)
    return report


def test_the_block_states_the_measured_numbers():
    """The table has to carry the numbers, not a promise to produce them."""
    block = block_markdown(_report())
    assert "claude-haiku-5-5" in block
    assert "0.850" in block          # F1
    assert "0.870" in block          # accuracy
    assert "120 ms" in block         # p50
    assert "300 ms" in block         # p95
    assert "0.000100" in block       # $ per verdict


def test_the_block_says_how_many_runs_it_took():
    """A number without its conditions is not evidence."""
    block = block_markdown(_report())
    assert "3 runs per incident" in block


def test_the_block_does_not_quote_a_degraded_run():
    """
    A run that fell back to the offline judge is NOT a Claude measurement.
    It must not appear in the table at all.
    """
    report = RunReport(started_at="2026-11-08 12:00 UTC", runs_per_incident=3, key_present=True)
    report.models.append(ModelResult(model="claude-opus-5-5", ok=True, fallback_used=True,
                                     latency_p50_ms=0.0, cost_per_verdict_usd=0.0))
    block = block_markdown(report)
    assert "claude-opus-5-5" not in block, "a fallback run was filed as a Claude measurement"
    assert "no model was measured" in block


def test_the_block_keeps_its_markers():
    """The updater replaces the span *between* the markers, so the markers
    themselves have to survive the write."""
    block = block_markdown(_report())
    assert block.startswith(PACK_BEGIN)
    assert block.rstrip().endswith(PACK_END)


# ── the pack updater ────────────────────────────────────────────────────────
def test_updating_the_pack_writes_the_numbers(tmp_path):
    pack = tmp_path / "pack.md"
    pack.write_text(f"before\n{PACK_BEGIN}\nold text\n{PACK_END}\nafter\n", encoding="utf-8")
    changed = update_pack(pack, _report())
    assert changed is True
    text = pack.read_text(encoding="utf-8")
    assert "old text" not in text, "the old block was not replaced"
    assert "claude-haiku-5-5" in text
    assert text.startswith("before\n"), "the text before the markers was touched"
    assert text.rstrip().endswith("after"), "the text after the markers was touched"


def test_updating_the_pack_twice_is_idempotent(tmp_path):
    """CI may run twice. The second run must not churn the file."""
    pack = tmp_path / "pack.md"
    pack.write_text(f"a\n{PACK_BEGIN}\nold\n{PACK_END}\nb\n", encoding="utf-8")
    update_pack(pack, _report())
    first = pack.read_text(encoding="utf-8")
    changed = update_pack(pack, _report())
    assert changed is False, "the second write changed the file"
    assert pack.read_text(encoding="utf-8") == first


def test_updating_a_pack_without_markers_raises(tmp_path):
    """
    A silent no-op here would let CI go green without writing anything.
    """
    pack = tmp_path / "pack.md"
    pack.write_text("no markers here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        update_pack(pack, _report())


def test_the_disclaimer_is_replaced_once_there_is_a_number(tmp_path):
    pack = tmp_path / "pack.md"
    pack.write_text(
        "- **No Claude judge latency or cost.** Never measured. Needs an API key.\n"
        "- **No revenue figure.**\n", encoding="utf-8")
    changed = update_disclaimer(pack, _report())
    assert changed is True
    text = pack.read_text(encoding="utf-8")
    assert "Never measured" not in text
    assert "claude-haiku-5-5" in text
    assert "No revenue figure" in text, "the other limits must survive"


def test_the_disclaimer_is_left_alone_when_nothing_was_measured(tmp_path):
    """
    Without a measurement, the disclaimer is the truth and must stay.
    """
    pack = tmp_path / "pack.md"
    original = "- **No Claude judge latency or cost.** Never measured. Needs an API key.\n"
    pack.write_text(original, encoding="utf-8")
    report = RunReport(started_at="2026-11-08 12:00 UTC", runs_per_incident=3, key_present=False)
    assert update_disclaimer(pack, report) is False
    assert pack.read_text(encoding="utf-8") == original


# ── the refusal to invent a number ──────────────────────────────────────────
def test_a_fallback_run_is_flagged_as_degraded(monkeypatch):
    """
    When the provider cannot be reached the judge silently uses the offline
    scorer. The runner has to notice — otherwise a "Claude" row of 0 ms and
    $0.00 lands in the pack.
    """
    import brain.judge_eval_ci as mod

    def fake_run_eval(cfg, path, judge=None, runs=None, **kw):
        return {
            "judge": "fallback",          # <- the judge fell back
            "precision": 1.0, "recall": 0.824, "f1": 0.903, "accuracy": 0.914,
            "false_positive_rate": 0.0, "invalid_output_rate": 0.0,
            "latency_p50_ms": 0.0, "latency_p95_ms": 0.0,
            "cost_per_verdict_usd": 0.0, "cost_total_usd": 0.0, "n_incidents": 70,
        }

    monkeypatch.setattr(mod, "run_eval", fake_run_eval)
    result = run_model("claude-haiku-5-5", runs=1)
    assert result.ok is True
    assert result.fallback_used is True, "a fallback run was not flagged"
    assert result.latency_p50_ms == 0.0


def test_a_real_claude_run_is_not_flagged_as_degraded(monkeypatch):
    import brain.judge_eval_ci as mod

    def fake_run_eval(cfg, path, judge=None, runs=None, **kw):
        return {
            "judge": "claude",
            "precision": 0.9, "recall": 0.8, "f1": 0.85, "accuracy": 0.87,
            "false_positive_rate": 0.1, "invalid_output_rate": 0.0,
            "latency_p50_ms": 120.0, "latency_p95_ms": 300.0,
            "cost_per_verdict_usd": 0.0001, "cost_total_usd": 0.021, "n_incidents": 70,
        }

    monkeypatch.setattr(mod, "run_eval", fake_run_eval)
    result = run_model("claude-haiku-5-5", runs=3)
    assert result.fallback_used is False
    assert result.latency_p50_ms == 120.0
    assert result.cost_per_verdict_usd == 0.0001


def test_an_exception_is_an_error_not_a_measurement(monkeypatch):
    """
    A provider error must never become a row of zeros.
    """
    import brain.judge_eval_ci as mod

    def boom(cfg, path, judge=None, runs=None, **kw):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(mod, "run_eval", boom)
    result = run_model("claude-haiku-5-5", runs=1)
    assert result.ok is False
    assert "connection reset" in result.error
    assert result.latency_p50_ms == 0.0


def test_the_report_separates_measured_from_degraded():
    report = RunReport(started_at="", runs_per_incident=3, key_present=True)
    report.models.append(ModelResult(model="a", ok=True, fallback_used=False))
    report.models.append(ModelResult(model="b", ok=True, fallback_used=True))
    report.models.append(ModelResult(model="c", ok=False, error="boom"))
    assert [m.model for m in report.measured] == ["a"]
    assert [m.model for m in report.degraded] == ["b"]


# ── the command line ────────────────────────────────────────────────────────
def test_no_key_is_an_error_not_a_silent_pass(monkeypatch, tmp_path):
    """
    Without a key the module must exit non-zero and touch nothing. This is
    the difference between "the CI job failed and a human read it" and "the
    pack now says Claude costs $0.00".
    """
    import brain.judge_eval_ci as mod

    monkeypatch.setattr(mod, "load_settings",
                        lambda: replace(load_settings(), anthropic_api_key=""))
    monkeypatch.setattr(sys, "argv", ["judge_eval_ci", "--runs", "3"])
    code = mod.main()
    assert code == 3, "a missing key must be a non-zero exit"


def test_no_key_leaves_the_pack_alone(monkeypatch, tmp_path):
    """The pack is not touched on the way to the error."""
    import brain.judge_eval_ci as mod

    pack = tmp_path / "pack.md"
    original = f"a\n{PACK_BEGIN}\nold\n{PACK_END}\nb\n"
    pack.write_text(original, encoding="utf-8")
    monkeypatch.setattr(mod, "load_settings",
                        lambda: replace(load_settings(), anthropic_api_key=""))
    monkeypatch.setattr(sys, "argv",
                        ["judge_eval_ci", "--runs", "3", "--pack", str(pack)])
    assert mod.main() == 3
    assert pack.read_text(encoding="utf-8") == original


def test_the_cli_writes_a_json_report(monkeypatch, tmp_path):
    """
    The JSON next to the markdown is what makes the markdown checkable: a
    reader can compare the table with the raw run.
    """
    import brain.judge_eval_ci as mod

    monkeypatch.setattr(mod, "load_settings",
                        lambda: replace(load_settings(), anthropic_api_key="sk-test"))
    monkeypatch.setattr(mod, "run_all", lambda *a, **k: _report())
    out = tmp_path / "judge-eval-ci.json"
    pack = tmp_path / "pack.md"
    pack.write_text(f"a\n{PACK_BEGIN}\nold\n{PACK_END}\nb\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["judge_eval_ci", "--json-out", str(out), "--pack", str(pack)])
    code = mod.main()
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["runs_per_incident"] == 3
    assert data["models"][0]["model"] == "claude-haiku-5-5"
    # The real pack must not be touched by a test.
    assert "claude-haiku-5-5" in pack.read_text(encoding="utf-8")


def test_the_json_records_the_error_of_a_failed_model():
    """A failed model is recorded, not dropped — a dropped row hides a problem."""
    report = RunReport(started_at="", runs_per_incident=3, key_present=True)
    report.models.append(ModelResult(model="x", ok=False, error="boom"))
    data = report.to_dict()
    assert data["models"][0]["ok"] is False
    assert data["models"][0]["error"] == "boom"
