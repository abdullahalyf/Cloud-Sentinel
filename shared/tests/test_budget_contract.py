"""
The contract test for B4's budget hierarchy and degradation ladder.

Two ideas carry the whole task:

- **the budget is a tree** — org → team → agent — and every level is the sum
  of the level below it, so one runaway agent cannot eat the fleet's money;
- **the ladder steps down gently** — throttle → downgrade → pause → kill —
  and it never skips a rung.

And the forecast answers the operator's 3 AM question only when it can: a
burn rate of zero has no forecast, because "exhausted in 0 minutes" is a lie.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.contracts import (ACTION_TYPES, BUDGET_LEVELS, DEGRADATION_LADDER,
                              budget_forecast, budget_node, budget_report, degradation_plan)
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    mock_api.seed()
    yield
    mock_api.seed()


# ── the ladder ──────────────────────────────────────────────────────────────
def test_the_ladder_is_throttle_downgrade_pause_kill():
    """The order is the whole point: the gentlest step comes first."""
    assert DEGRADATION_LADDER == ("THROTTLE", "DOWNGRADE", "PAUSE", "KILL")


def test_the_new_action_types_are_in_the_contract():
    assert "THROTTLE" in ACTION_TYPES
    assert "DOWNGRADE" in ACTION_TYPES


def test_the_ladder_starts_at_throttle():
    plan = degradation_plan()
    assert plan["next_step"] == "THROTTLE"
    assert plan["exhausted"] is False


def test_the_ladder_does_not_skip_a_rung():
    """An agent that has not been throttled is not downgraded."""
    plan = degradation_plan(applied=["THROTTLE"])
    assert plan["next_step"] == "DOWNGRADE"


def test_the_ladder_advances_one_step_at_a_time():
    applied = []
    for step in DEGRADATION_LADDER:
        plan = degradation_plan(applied=applied)
        assert plan["next_step"] == step
        applied = plan["applied"] + [step]
    assert degradation_plan(applied=list(DEGRADATION_LADDER))["exhausted"] is True


def test_a_step_that_is_not_on_the_ladder_is_ignored():
    """A "WARN" is not a rung — it must not move the ladder along."""
    plan = degradation_plan(applied=["WARN"])
    assert plan["next_step"] == "THROTTLE"
    assert "WARN" not in plan["applied"]


def test_the_current_step_is_recorded():
    plan = degradation_plan(current_step="PAUSE")
    assert "PAUSE" in plan["applied"]
    assert plan["next_step"] == "KILL"


# ── the forecast ────────────────────────────────────────────────────────────
def test_the_forecast_says_exhausted_in_x_minutes():
    forecast = budget_forecast(1.0, 0.25, 0.05)
    assert forecast["minutes_to_exhausted"] == 15.0
    assert "15" in forecast["sentence"]


def test_the_forecast_says_nothing_when_the_burn_rate_is_zero():
    """Nothing is being spent, so nothing will be exhausted. "In 0 minutes"
    would be a lie and "in infinity" is not a number."""
    forecast = budget_forecast(1.0, 0.25, 0.0)
    assert forecast["minutes_to_exhausted"] is None
    assert forecast["sentence"] == ""


def test_a_budget_that_is_already_gone_is_already_exhausted():
    forecast = budget_forecast(1.0, 1.5, 0.05)
    assert forecast["remaining_usd"] == 0.0
    assert forecast["minutes_to_exhausted"] == 0.0
    assert "already exhausted" in forecast["sentence"]


def test_the_remaining_money_is_never_negative():
    forecast = budget_forecast(1.0, 3.0, 0.05)
    assert forecast["remaining_usd"] == 0.0


def test_the_forecast_says_whether_it_is_within_the_horizon():
    assert budget_forecast(1.0, 0.0, 0.5, horizon_minutes=60)["exhausted_within_horizon"] is True
    assert budget_forecast(1.0, 0.0, 0.001, horizon_minutes=60)["exhausted_within_horizon"] is False


# ── the tree ────────────────────────────────────────────────────────────────
def test_a_node_carries_its_level_and_its_money():
    node = budget_node("agent", "beta", 0.5, 0.1)
    assert node["level"] == "agent"
    assert node["id"] == "beta"
    assert node["budget_usd"] == 0.5
    assert node["remaining_usd"] == 0.4


def test_the_levels_are_org_team_agent():
    assert BUDGET_LEVELS == ("org", "team", "agent")


def test_the_report_has_the_tree():
    report = budget_report(budget_node("org", "org", 4.0, 1.0),
                            [budget_node("team", "core", 1.0, 0.2)],
                            [budget_node("agent", "beta", 0.5, 0.1)])
    assert sorted(report) == ["agents", "as_of", "org", "teams"]
    assert report["org"]["level"] == "org"
    assert report["teams"][0]["level"] == "team"
    assert report["agents"][0]["level"] == "agent"


# ── the mock endpoint ───────────────────────────────────────────────────────
def test_the_mock_serves_the_budget_tree():
    c = TestClient(mock_app)
    r = c.get("/v1/budgets")
    assert r.status_code == 200
    body = r.json()
    assert body["org"]["level"] == "org"
    assert body["teams"]
    assert body["agents"]


def test_the_org_budget_is_the_sum_of_the_team_budgets():
    """The tree is the point: the org is the sum of the teams."""
    body = TestClient(mock_app).get("/v1/budgets").json()
    assert body["org"]["budget_usd"] == round(sum(t["budget_usd"] for t in body["teams"]), 4)


def test_the_team_budget_is_the_sum_of_its_agent_budgets():
    """And a team's is the sum of its agents'."""
    body = TestClient(mock_app).get("/v1/budgets").json()
    budgets = {a["id"]: a["budget_usd"] for a in body["agents"]}
    for team in body["teams"]:
        members = [budgets[a] for a in team["children"]]
        assert team["budget_usd"] == round(sum(members), 4)


def test_the_mock_budget_tree_matches_the_real_policy_file():
    """The mock's budget tree must not disagree with `brain/policies.yaml`.

    The mock used to keep its own hardcoded budget dict while its `/v1/policy`
    endpoint served the real file — so when delta's budget changed, the fleet
    view said $0.20 and the policy view said $0.50. Both now read the file.
    """
    from pathlib import Path

    import yaml

    data = yaml.safe_load(Path("brain/policies.yaml").read_text(encoding="utf-8")) or {}
    agents = data.get("agents") or {}
    default_budget = (data.get("defaults") or {}).get("budget_usd")
    body = TestClient(mock_app).get("/v1/budgets").json()
    for agent in body["agents"]:
        expected = (agents.get(agent["id"]) or {}).get("budget_usd", default_budget)
        assert agent["budget_usd"] == pytest.approx(expected), (
            f"the mock's budget tree disagrees with brain/policies.yaml about {agent['id']}'s budget")


def test_every_level_has_a_forecast():
    body = TestClient(mock_app).get("/v1/budgets").json()
    for node in [body["org"], *body["teams"], *body["agents"]]:
        assert node["forecast"]
        assert "minutes_to_exhausted" in node["forecast"]
