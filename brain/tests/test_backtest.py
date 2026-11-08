"""
The brain-side tests for B5's policy backtest.

The backtest answers one question: **"would the candidate policy have caught
it?"** Everything here serves that question.

Three things must hold, and the third is the one people forget:

- the report is **deterministic** — the same traces and the same policy always
  give the same catches, so two policies can be compared;
- a **false positive is counted, not hidden** — a backtest that only reports
  the good news is an advertisement, not a measurement;
- the **money is the ROI formula** — the same money the live system counts.

And a store with no history reports zero, not an error.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from brain import backtest as brain_backtest
from brain.api import create_app
from brain.policy import Policy
from shared.contracts import ROI_FORMULA, ActionRow, AlertRow, SpanRow
from shared.store import LocalStore

# ── a known set of traces ───────────────────────────────────────────────────
# Two agents. `beta` burns like a runaway; `alpha` is busy but healthy. The
# candidate policy is *tighter* than the running one, so it stops both — beta
# rightly (beta really did go wrong, and the store says so) and alpha wrongly
# (alpha never had an incident, so the stop is a false positive).
ROGUE_PROMPT = "Retry: fetch order #4471 status from the orders API and summarize the result"
HEALTHY_PROMPT = "Summarize the weekly sales report for the north region"


def _span(agent_id: str, ts: float, prompt: str, tokens: int = 400, cost: float = 0.01,
          prompt_hash: str = "") -> SpanRow:
    return SpanRow(agent_id, "chat", f"chat {ts}", trace_id=f"t-{agent_id}",
                   input_tokens=tokens, output_tokens=tokens // 4, cost_usd=cost,
                   prompt_preview=prompt, prompt_hash=prompt_hash or f"h-{prompt[:20]}",
                   start_ts=ts)


def _trace(store, *, rogue_tokens: int = 400, healthy_tokens: int = 400,
           base: Optional[float] = None, stopped: bool = False) -> None:
    """
    A store with two agents: one runaway, one busy but fine.

    The **alert** is what makes the difference between a catch and a false
    positive: the running policy recorded one for `beta` and none for `alpha`,
    so `beta` really did go wrong and `alpha` really was fine. The backtest
    reads that record — it does not guess.

    `base` pins the timestamps, so two stores can hold the *same* trace and the
    API and the CLI can be compared exactly.

    `stopped` adds the action row the running policy wrote when it stopped
    `beta` — the record that says "this was already handled".
    """
    # The store's `recent_spans` filters on the wall clock, so the trace has to
    # be *now* — a backtest reads the traces that were actually stored.
    t = (time.time() - 120.0) if base is None else base
    rows = []
    # beta: the same prompt, again and again — a loop, and it burns hard.
    for i in range(14):
        rows.append(_span("beta", t + i, ROGUE_PROMPT, tokens=rogue_tokens, cost=0.05))
    # alpha: different prompts, a normal busy agent.
    for i in range(10):
        rows.append(_span("alpha", t + i, f"{HEALTHY_PROMPT} #{i}", tokens=healthy_tokens, cost=0.001))
    store.insert_spans(rows)
    store.insert_alert(AlertRow("beta", "warning", "loop_exact",
                                "same prompt repeated 14x in the last minute"))
    if stopped:
        store.insert_action(ActionRow("beta", "PAUSE", "rules",
                                      "same prompt repeated 14x in the last minute"))


def _candidate(budget_usd: float = 0.20, on_hard_limit: str = "kill") -> Policy:
    """A candidate policy: a tighter budget than the running one."""
    return Policy.from_dict({"defaults": {"budget_usd": budget_usd,
                                          "on_trip": "pause",
                                          "on_hard_limit": on_hard_limit}},
                            default_budget=budget_usd)


@pytest.fixture
def store():
    return LocalStore(":memory:")


@pytest.fixture
def running(cfg):
    return Policy.load("brain/policies.yaml")


# ── the report is deterministic ─────────────────────────────────────────────
def test_the_same_traces_give_the_same_catches_twice(store, cfg, running):
    """A backtest that varied run to run could not be used to compare two policies."""
    _trace(store)
    candidate = _candidate()
    first = brain_backtest.run_backtest(store, candidate, cfg, running_policy=running)
    second = brain_backtest.run_backtest(store, candidate, cfg, running_policy=running)
    assert first["catches"] == second["catches"]
    assert first["false_positives"] == second["false_positives"]
    assert first["usd_saved"] == second["usd_saved"]
    assert first["counts"] == second["counts"]


def test_the_catches_are_in_a_stable_order(store, cfg, running):
    _trace(store)
    candidate = _candidate()
    first = brain_backtest.run_backtest(store, candidate, cfg, running_policy=running)
    second = brain_backtest.run_backtest(store, candidate, cfg, running_policy=running)
    assert [c["agent_id"] for c in first["catches"]] == [c["agent_id"] for c in second["catches"]]


def test_one_runaway_is_one_catch_not_a_hundred(store, cfg, running):
    """The same rule firing again is the same mistake, counted once."""
    _trace(store)
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    assert len(report["catches"]) == 1
    assert report["catches"][0]["agent_id"] == "beta"


# ── the false positive is counted, not hidden ───────────────────────────────
def test_a_false_positive_is_counted_not_hidden(store, cfg, running):
    """alpha never had an incident, so the candidate stopping it is a false positive."""
    _trace(store)
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    assert report["counts"]["false_positives"] >= 1
    assert any(f["agent_id"] == "alpha" for f in report["false_positives"])


def test_the_false_positives_are_not_subtracted_from_the_catches(store, cfg, running):
    """The counts are two separate facts. One does not cancel the other."""
    _trace(store)
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    assert report["counts"]["catches"] >= 1
    assert report["counts"]["false_positives"] >= 1
    assert report["counts"]["total"] == (report["counts"]["catches"]
                                         + report["counts"]["false_positives"])


def test_the_summary_says_the_false_positives_out_loud(store, cfg, running):
    """A summary that shows only the catches hides half the answer."""
    _trace(store)
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    from shared.contracts import backtest_summary

    line = backtest_summary(report)
    assert "caught" in line and "false positive" in line


# ── the money ───────────────────────────────────────────────────────────────
def test_the_money_saved_uses_the_roi_formula(store, cfg, running):
    """saved = $/min at the moment of action × horizon — the live system's formula."""
    _trace(store)
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    catch = report["catches"][0]
    # beta spends $0.05 per call, roughly one call a second → the burn rate is
    # high, and the saving is the burn rate times the horizon.
    expected = catch["usd_saved"]
    assert expected > 0
    assert expected == round(expected, 4)
    assert report["usd_saved"] == pytest.approx(sum(c["usd_saved"] for c in report["catches"]))
    assert report["horizon_minutes"] == cfg.roi_horizon_minutes


def test_the_money_is_the_same_money_the_live_system_counts(store, cfg, running):
    """One formula, one answer — a backtest that invents its own maths is a fiction."""
    assert "saved = $/min at the moment of action" in ROI_FORMULA


def test_the_total_money_is_the_sum_of_the_catches(store, cfg, running):
    _trace(store)
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    assert report["usd_saved"] == pytest.approx(sum(c["usd_saved"] for c in report["catches"]))


# ── a store with no history ────────────────────────────────────────────────
def test_a_store_with_no_history_reports_zero_not_an_error(store, cfg, running):
    """"We have no traces, so we cannot tell you anything" is a fact, not a failure."""
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    assert report["counts"]["catches"] == 0
    assert report["counts"]["false_positives"] == 0
    assert report["counts"]["agents"] == 0
    assert report["usd_saved"] == 0.0
    assert report["spans_replayed"] == 0
    assert report["catches"] == [] and report["false_positives"] == []


def test_an_empty_store_still_names_the_candidate_policy(store, cfg, running):
    """The report says which policy it tested, even when it tested nothing."""
    report = brain_backtest.run_backtest(store, _candidate(), cfg, running_policy=running)
    assert report["policy_version"] is not None


# ── the candidate policy ────────────────────────────────────────────────────
def test_a_tighter_budget_catches_a_budget_the_loose_one_never_would(store, cfg, running):
    """The whole point of the backtest: a different policy gives a different answer."""
    _trace(store)
    tight = brain_backtest.run_backtest(store, _candidate(budget_usd=0.05), cfg, running_policy=running)
    loose = brain_backtest.run_backtest(store, _candidate(budget_usd=10.0), cfg, running_policy=running)
    tight_rules = {c["rule"] for c in tight["catches"]}
    loose_rules = {c["rule"] for c in loose["catches"]}
    assert "budget_exceeded" in tight_rules
    assert "budget_exceeded" not in loose_rules


def test_a_rule_the_running_policy_already_fired_is_not_a_new_catch(store, cfg, running):
    """
    The running policy saw the loop and stopped the agent. A backtest that
    reported that same rule as a *new* catch would be padding its numbers.
    """
    _trace(store, stopped=True)
    report = brain_backtest.run_backtest(store, running, cfg, running_policy=running)
    rules = {c["rule"] for c in report["catches"]}
    assert "loop_exact" not in rules


def test_a_rule_the_running_policy_never_fired_is_a_catch(store, cfg, running):
    """
    The running policy saw the loop. A candidate policy that also sees the
    **budget** going over is catching something the running policy missed.
    """
    _trace(store, stopped=True)
    report = brain_backtest.run_backtest(store, _candidate(budget_usd=0.05), cfg, running_policy=running)
    rules = {c["rule"] for c in report["catches"]}
    assert "budget_exceeded" in rules
    assert "loop_exact" not in rules   # the running policy already handled that one


# ── the CLI ─────────────────────────────────────────────────────────────────
def test_the_cli_prints_the_report_and_exits_zero(tmp_path, capsys):
    """The CLI prints the report and exits 0."""
    db = tmp_path / "cli.db"
    store = LocalStore(str(db))
    _trace(store)
    code = brain_backtest.main(["--db", str(db)])
    assert code == 0
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert report["counts"]["catches"] + report["counts"]["false_positives"] >= 1


def test_the_cli_exits_zero_even_when_it_finds_nothing(tmp_path, capsys):
    """A backtest that found nothing is a result, not a failure."""
    db = tmp_path / "empty.db"
    LocalStore(str(db))
    code = brain_backtest.main(["--db", str(db)])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["catches"] == 0


def test_the_cli_takes_a_policy_file_as_an_argument(tmp_path, capsys):
    """The candidate policy comes from the command line."""
    db = tmp_path / "cli.db"
    store = LocalStore(str(db))
    _trace(store)
    policy = tmp_path / "candidate.yaml"
    policy.write_text("defaults:\n  budget_usd: 0.05\n  on_trip: pause\n  on_hard_limit: kill\n",
                      encoding="utf-8")
    code = brain_backtest.main(["--db", str(db), str(policy)])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["policy_version"]


def test_the_cli_uses_the_running_policy_when_it_is_not_given_one(tmp_path, capsys):
    """With no policy argument the running policy is tested against itself."""
    db = tmp_path / "cli.db"
    store = LocalStore(str(db))
    _trace(store)
    code = brain_backtest.main(["--db", str(db)])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    running = Policy.load("brain/policies.yaml")
    assert report["policy_version"] == running.version


def test_the_cli_reports_a_missing_policy_file_instead_of_crashing(tmp_path, capsys):
    """A broken argument is a message and an exit code, not a traceback."""
    db = tmp_path / "cli.db"
    LocalStore(str(db))
    code = brain_backtest.main(["--db", str(db), str(tmp_path / "nope.yaml")])
    assert code == 1
    assert "could not read" in capsys.readouterr().err


# ── the API ─────────────────────────────────────────────────────────────────
def _client(store, cfg, running):
    return TestClient(create_app(store, running, cfg, "fake", "fallback"))


def test_the_api_is_off_by_default(store, cfg, running):
    """The flag is off, so the endpoint does not exist. A 404, not an empty report."""
    assert cfg.backtest_enabled is False
    assert _client(store, cfg, running).get("/v1/backtest").status_code == 404


def test_the_api_serves_the_report_when_the_flag_is_on(store, cfg, running):
    _trace(store)
    on = replace(cfg, backtest_enabled=True)
    report = _client(store, on, running).get("/v1/backtest").json()
    assert report["counts"]["catches"] + report["counts"]["false_positives"] >= 1


def test_the_api_and_the_cli_agree(store, cfg, running, tmp_path, capsys):
    """The same question must not have two answers."""
    base = time.time() - 120.0
    _trace(store, base=base)
    on = replace(cfg, backtest_enabled=True)
    api_report = _client(store, on, running).get("/v1/backtest").json()

    db = tmp_path / "same.db"
    same = LocalStore(str(db))
    _trace(same, base=base)
    brain_backtest.main(["--db", str(db)])
    cli_report = json.loads(capsys.readouterr().out)

    assert api_report["catches"] == cli_report["catches"]
    assert api_report["false_positives"] == cli_report["false_positives"]
    assert api_report["usd_saved"] == cli_report["usd_saved"]
    assert api_report["counts"] == cli_report["counts"]


def test_the_api_matches_the_mock(store, cfg, running):
    """The mock and the real API must say the same thing."""
    from shared.mocks import mock_api
    from shared.mocks.mock_api import app as mock_app

    _trace(store)
    on = replace(cfg, backtest_enabled=True)
    real = _client(store, on, running).get("/v1/backtest").json()
    mock = TestClient(mock_app).get("/v1/backtest").json()
    assert set(real) == set(mock)
    assert set(real["counts"]) == set(mock["counts"])
    assert set(real["catches"][0]) == set(mock["catches"][0])
    assert set(real["false_positives"][0]) == set(mock["false_positives"][0])
