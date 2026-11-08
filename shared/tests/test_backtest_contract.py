"""
The contract test for B5's policy backtest.

The report has to say three things, and the third one is the one people forget:

- **the catches** — what the candidate policy would have stopped;
- **the false positives** — what it would have stopped *wrongly*, counted out
  loud, because a backtest that only reports the good news is an advertisement
  and not a measurement;
- **the money** — by the same ROI formula the live system uses.

And a store with no traces reports **zeroes, not an error**.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.contracts import (BACKTEST_CATCH_ACTIONS, ROI_FORMULA, backtest_catch,
                              backtest_false_positive, backtest_report, backtest_summary)
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    mock_api.seed()
    yield
    mock_api.seed()


# ── the shape ───────────────────────────────────────────────────────────────
def test_an_empty_backtest_reports_zeroes_not_an_error():
    """No traces means "we cannot tell you anything" — a fact, not a failure."""
    report = backtest_report()
    assert report["counts"] == {"catches": 0, "false_positives": 0, "agents": 0, "total": 0}
    assert report["usd_saved"] == 0.0
    assert report["spans_replayed"] == 0
    assert report["catches"] == [] and report["false_positives"] == []


def test_the_report_has_every_field_the_api_serves():
    report = backtest_report()
    assert set(report) == {"catches", "false_positives", "usd_saved", "policy_version",
                           "agents_tested", "spans_replayed", "horizon_minutes", "counts", "as_of"}


def test_a_catch_names_the_rule_the_agent_the_time_and_the_action():
    catch = backtest_catch("loop_semantic", "beta", 1000.5, "PAUSE", "it looped", 2.5)
    assert catch == {"rule": "loop_semantic", "agent_id": "beta", "at": 1000.5, "action": "PAUSE",
                     "reason": "it looped", "usd_saved": 2.5}


def test_a_false_positive_names_what_would_have_been_stopped_wrongly():
    fp = backtest_false_positive("budget_80pct", "alpha", 900.0, "it was fine")
    assert fp == {"rule": "budget_80pct", "agent_id": "alpha", "at": 900.0, "reason": "it was fine"}


def test_the_money_is_rounded_to_four_places():
    """Money in a report is money you can sum."""
    catch = backtest_catch("budget_exceeded", "beta", 1.0, "KILL", "", 1.23456789)
    assert catch["usd_saved"] == 1.2346


def test_the_counts_match_the_lists():
    report = backtest_report(catches=[backtest_catch("r", "a", 1.0, "KILL")],
                             false_positives=[backtest_false_positive("r", "b", 2.0)],
                             agents_tested=["a", "b"])
    assert report["counts"]["catches"] == 1
    assert report["counts"]["false_positives"] == 1
    assert report["counts"]["agents"] == 2
    assert report["counts"]["total"] == 2


# ── what counts as a catch ──────────────────────────────────────────────────
def test_a_warning_is_not_a_catch():
    """Warning about a runaway is not stopping it."""
    assert "WARN" not in BACKTEST_CATCH_ACTIONS


def test_the_catch_actions_are_the_ones_that_stop_an_agent():
    assert set(BACKTEST_CATCH_ACTIONS) == {"PAUSE", "KILL", "TOOL_DENY", "TOOL_REWRITE"}


# ── the summary ─────────────────────────────────────────────────────────────
def test_the_summary_says_the_false_positives_out_loud():
    """A summary that shows only the catches hides half the answer."""
    report = backtest_report(catches=[backtest_catch("r", "a", 1.0, "KILL")],
                             false_positives=[backtest_false_positive("r", "b", 2.0)],
                             usd_saved=12.5)
    line = backtest_summary(report)
    assert "1 caught" in line
    assert "1 false positive" in line
    assert "$12.50 saved" in line


def test_the_summary_of_an_empty_backtest_is_readable():
    line = backtest_summary(backtest_report())
    assert "0 caught" in line and "0 false positive" in line and "$0.00 saved" in line


# ── the ROI formula ─────────────────────────────────────────────────────────
def test_the_money_is_the_roi_formula_the_live_system_uses():
    """One formula, one answer — a backtest that invents its own maths is a fiction."""
    assert "saved = $/min at the moment of action" in ROI_FORMULA
    assert "TOOL_DENY: saved = value at stake" in ROI_FORMULA


# ── the mock endpoint ───────────────────────────────────────────────────────
def test_the_mock_serves_the_backtest():
    report = TestClient(mock_app).get("/v1/backtest").json()
    assert report["counts"]["catches"] > 0
    assert report["counts"]["false_positives"] > 0
    assert report["usd_saved"] > 0
    assert report["spans_replayed"] > 0
    assert report["agents_tested"]


def test_the_mock_backtest_has_the_same_fields_as_the_contract():
    report = TestClient(mock_app).get("/v1/backtest").json()
    assert set(report) == set(backtest_report())


def test_the_mock_backtest_catches_have_the_same_fields_as_the_contract():
    report = TestClient(mock_app).get("/v1/backtest").json()
    assert set(report["catches"][0]) == set(backtest_catch("r", "a", 1.0, "KILL"))
    assert set(report["false_positives"][0]) == set(backtest_false_positive("r", "a", 1.0))


def test_the_mock_backtest_says_the_false_positives_out_loud():
    """The mock is the dashboard's picture of the truth — it must show both sides."""
    report = TestClient(mock_app).get("/v1/backtest").json()
    assert "false positive" in backtest_summary(report)
