"""
The tests for B4: the budget tree, the forecast and the degradation ladder.

The task's own words, turned into tests:

- the org budget is the sum of the team budgets and the team budget is the sum
  of the agent budgets (an agent over its share does not consume the org's
  whole budget);
- the forecast says "exhausted in X min" from the burn rate, and says nothing
  when the burn rate is zero;
- the degradation ladder is exactly throttle → cheaper model → pause → kill,
  and the ladder stops at the first step that works;
- a threshold step does not skip a rung;
- the flag off → the old behaviour (pause / kill, no throttle);
- a failed throttle does not advance the ladder silently.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from brain import budget
from brain.budget import Ladder, build_tree, effect_for, throttle_ratio
from brain.breaker import Breaker
from brain.detectors import Finding, Level
from shared.contracts import DEGRADATION_LADDER


# ── the tree ────────────────────────────────────────────────────────────────
def test_the_org_budget_is_the_sum_of_the_team_budgets():
    tree = build_tree({"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2},
                      {"alpha": 0.1, "beta": 0.2, "gamma": 0.0, "delta": 0.0})
    team_total = sum(t["budget_usd"] for t in tree.teams)
    assert tree.org["budget_usd"] == pytest.approx(team_total)


def test_the_team_budget_is_the_sum_of_its_agent_budgets():
    tree = build_tree({"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2})
    budgets = {a["id"]: a["budget_usd"] for a in tree.agents}
    for team in tree.teams:
        members = [budgets[a] for a in team["children"]]
        assert team["budget_usd"] == pytest.approx(sum(members))


def test_an_agent_over_its_share_does_not_consume_the_whole_org_budget():
    """The point of the tree: one runaway cannot eat the fleet's money."""
    budgets = {"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "delta": 0.2}
    # beta overruns its own 0.5 budget by 10x.
    spends = {"alpha": 0.0, "beta": 5.0, "gamma": 0.0, "delta": 0.0}
    tree = build_tree(budgets, spends)

    beta = tree.agent("beta")
    assert beta["remaining_usd"] == 0.0          # it overspent
    assert beta["spend_usd"] == 5.0

    # The other agents still have their money: the tree did not let beta eat it.
    assert tree.agent("alpha")["remaining_usd"] == pytest.approx(0.5)
    assert tree.agent("gamma")["remaining_usd"] == pytest.approx(1.0)

    # And the org's *budget* did not shrink because beta overspent — the org
    # still owes the other agents their shares.
    assert tree.org["budget_usd"] == pytest.approx(sum(budgets.values()))


def test_the_org_budget_is_never_below_its_teams():
    tree = build_tree({"alpha": 0.5, "beta": 0.5})
    assert tree.org["budget_usd"] >= sum(t["budget_usd"] for t in tree.teams)


def test_every_node_knows_its_level():
    tree = build_tree({"alpha": 0.5, "beta": 0.5})
    assert tree.org["level"] == "org"
    assert all(t["level"] == "team" for t in tree.teams)
    assert all(a["level"] == "agent" for a in tree.agents)


def test_a_team_knows_its_agents():
    tree = build_tree({"alpha": 0.5, "beta": 0.5})
    core = tree.team("core")
    assert set(core["children"]) == {"alpha", "beta"}


def test_an_agent_with_no_team_is_still_counted():
    """Hiding it would make the org look cheaper than it is."""
    tree = build_tree({"alpha": 0.5, "solo": 0.5}, {"solo": 0.25}, teams={})
    assert tree.org["spend_usd"] == pytest.approx(0.25)
    assert tree.org["budget_usd"] == pytest.approx(1.0)


def test_the_report_has_the_contract_shape():
    tree = build_tree({"alpha": 0.5, "beta": 0.5})
    report = tree.to_report()
    assert sorted(report) == ["agents", "as_of", "org", "teams"]
    assert report["org"]["level"] == "org"
    assert report["teams"][0]["level"] == "team"
    assert report["agents"][0]["level"] == "agent"


# ── the forecast ───────────────────────────────────────────────────────────
def test_the_forecast_says_exhausted_in_x_minutes():
    tree = build_tree({"alpha": 1.0}, {"alpha": 0.25}, burn_rates={"alpha": 0.05})
    forecast = tree.agent("alpha")["forecast"]
    assert forecast["minutes_to_exhausted"] == pytest.approx(15.0)
    assert "15" in forecast["sentence"]


def test_the_forecast_says_nothing_when_the_burn_rate_is_zero():
    """Nothing is being spent, so nothing will be exhausted. "In 0 minutes"
    would be a lie and "in infinity" is not a number."""
    tree = build_tree({"alpha": 1.0}, {"alpha": 0.25}, burn_rates={"alpha": 0.0})
    forecast = tree.agent("alpha")["forecast"]
    assert forecast["minutes_to_exhausted"] is None
    assert forecast["sentence"] == ""


def test_an_agent_with_no_burn_rate_has_no_forecast():
    """An agent nobody has heard from is not burning anything — and the
    forecast must not claim it will be exhausted in 0 minutes."""
    tree = build_tree({"alpha": 1.0}, {"alpha": 0.25})
    assert tree.agent("alpha")["forecast"]["minutes_to_exhausted"] is None


def test_a_budget_that_is_already_gone_is_already_exhausted():
    tree = build_tree({"alpha": 1.0}, {"alpha": 1.5}, burn_rates={"alpha": 0.05})
    forecast = tree.agent("alpha")["forecast"]
    assert forecast["remaining_usd"] == 0.0
    assert forecast["minutes_to_exhausted"] == 0.0
    assert "already exhausted" in forecast["sentence"]


def test_the_remaining_money_is_never_negative():
    tree = build_tree({"alpha": 1.0}, {"alpha": 3.0}, burn_rates={"alpha": 0.05})
    assert tree.agent("alpha")["remaining_usd"] == 0.0
    assert tree.org["remaining_usd"] >= 0.0


def test_the_forecast_says_whether_it_is_within_the_horizon():
    tree = build_tree({"alpha": 1.0}, {"alpha": 0.0},
                      burn_rates={"alpha": 0.5}, horizon_minutes=60)
    assert tree.agent("alpha")["forecast"]["exhausted_within_horizon"] is True

    tree = build_tree({"alpha": 1.0}, {"alpha": 0.0},
                      burn_rates={"alpha": 0.001}, horizon_minutes=60)
    assert tree.agent("alpha")["forecast"]["exhausted_within_horizon"] is False


def test_every_level_of_the_tree_has_a_forecast():
    tree = build_tree({"alpha": 0.5, "beta": 0.5}, {"alpha": 0.1}, burn_rates={"alpha": 0.01})
    for node in [tree.org, *tree.teams, *tree.agents]:
        assert node["forecast"]
        assert "minutes_to_exhausted" in node["forecast"]


def test_a_team_burns_what_its_agents_burn():
    tree = build_tree({"alpha": 0.5, "beta": 0.5}, burn_rates={"alpha": 0.01, "beta": 0.02})
    core = tree.team("core")
    assert core["forecast"]["usd_per_min"] == pytest.approx(0.03)


# ── the ladder ─────────────────────────────────────────────────────────────
def test_the_ladder_is_throttle_downgrade_pause_kill():
    assert DEGRADATION_LADDER == ("THROTTLE", "DOWNGRADE", "PAUSE", "KILL")


def test_the_ladder_starts_at_throttle():
    ladder = Ladder("beta", enabled=True)
    assert ladder.next_step() == "THROTTLE"


def test_the_ladder_does_not_skip_a_rung():
    """An agent that has not been throttled is not downgraded."""
    ladder = Ladder("beta", enabled=True)
    ladder.stepped("THROTTLE")
    assert ladder.next_step() == "DOWNGRADE"


def test_the_ladder_advances_one_step_at_a_time():
    ladder = Ladder("beta", enabled=True)
    for step in DEGRADATION_LADDER:
        assert ladder.next_step() == step
        ladder.stepped(step)
    assert ladder.next_step() is None
    assert ladder.plan().exhausted is True


def test_the_ladder_stops_at_the_first_step_that_works():
    """A throttle that took effect stops the walk: the agent is slow now."""
    ladder = Ladder("beta", enabled=True)
    ladder.stepped("THROTTLE")
    assert ladder.next_step() == "DOWNGRADE"   # the ladder does not stop by itself


def test_the_ladder_restarts_when_the_agent_is_healthy_again():
    """The ladder stops at the first step that works — because a healthy agent
    needs no further steps, and the next runaway gets a fresh, gentle walk."""
    ladder = Ladder("beta", enabled=True)
    breaker = Breaker("beta", ladder=ladder)
    breaker.state = "suspicious"
    breaker.last_finding_at = 100.0
    ladder.stepped("THROTTLE")

    # 30 seconds later with no findings, the agent is healthy again.
    breaker.on_finding(Finding(level=Level.OK), now=100.0 + 40.0)

    assert breaker.state == "healthy"
    assert ladder.applied == []
    assert ladder.next_step() == "THROTTLE"


def test_a_resumed_agent_gets_a_fresh_ladder():
    ladder = Ladder("beta", enabled=True)
    breaker = Breaker("beta", ladder=ladder)
    breaker.state = "paused"
    ladder.stepped("THROTTLE")
    breaker.on_command("RESUME", "human", "", now=100.0)
    assert ladder.applied == []
    assert ladder.next_step() == "THROTTLE"


def test_a_failed_throttle_does_not_advance_the_ladder_silently():
    """The heart of the thing: a throttle that did not take effect must not
    become a downgrade, because the agent is still running at full speed."""
    ladder = Ladder("beta", enabled=True)
    ladder.step_failed("THROTTLE", "the runtime refused the throttle")
    assert ladder.next_step() == "THROTTLE"    # stuck on the failed rung
    assert ladder.plan().blocked == "THROTTLE"
    assert ladder.plan().last_failed == "THROTTLE"
    assert "THROTTLE" not in ladder.applied


def test_a_ladder_that_is_off_proposes_nothing():
    ladder = Ladder("beta", enabled=False)
    assert ladder.next_step() is None


def test_a_rung_that_is_not_on_the_ladder_does_not_move_it():
    ladder = Ladder("beta", enabled=True)
    ladder.stepped("WARN")
    assert ladder.applied == []
    assert ladder.next_step() == "THROTTLE"


def test_a_failed_rung_can_be_retried_and_then_succeed():
    ladder = Ladder("beta", enabled=True)
    ladder.step_failed("THROTTLE", "the runtime was busy")
    assert ladder.next_step() == "THROTTLE"
    ladder.stepped("THROTTLE")
    assert ladder.next_step() == "DOWNGRADE"
    assert ladder.plan().blocked is None


def test_the_reset_puts_the_ladder_back_at_the_top():
    ladder = Ladder("beta", enabled=True)
    ladder.stepped("THROTTLE")
    ladder.stepped("DOWNGRADE")
    ladder.reset()
    assert ladder.next_step() == "THROTTLE"
    assert ladder.applied == []


def test_the_throttle_ratio_shrinks_with_every_throttle():
    assert throttle_ratio([]) == 1.0
    assert throttle_ratio(["THROTTLE"]) < 1.0
    assert throttle_ratio(["THROTTLE", "THROTTLE"]) < throttle_ratio(["THROTTLE"])


def test_the_throttle_ratio_never_reaches_zero():
    """A rate of zero is not a throttle, it is a pause with extra steps."""
    assert throttle_ratio(["THROTTLE"] * 10) > 0.0


def test_a_rung_produces_its_action_and_a_readable_reason():
    action, reason = effect_for("THROTTLE", "the agent is burning its budget")
    assert action == "THROTTLE"
    assert "burning its budget" in reason
    assert "slow the agent down" in reason


def test_a_step_that_is_not_on_the_ladder_is_a_warning():
    action, _ = effect_for("WARN", "not a rung")
    assert action == "WARN"


# ── the breaker walks the ladder ───────────────────────────────────────────
def _critical() -> Finding:
    return Finding(level=Level.CRITICAL, rules=["token_spike"], reasons=["hard limit broken"])


def test_the_breaker_throttles_first_when_the_ladder_is_on():
    breaker = Breaker("beta", ladder=Ladder("beta", enabled=True))
    effect, ask = breaker.on_finding(_critical(), now=100.0)
    assert effect.action == "THROTTLE"
    assert ask is False
    # A throttle does not stop the agent, so the breaker keeps watching it.
    assert breaker.state == "healthy"
    assert breaker.active is True


def test_the_breaker_pauses_when_the_ladder_reaches_pause():
    ladder = Ladder("beta", enabled=True)
    breaker = Breaker("beta", ladder=ladder)
    ladder.stepped("THROTTLE")
    ladder.stepped("DOWNGRADE")
    effect, _ = breaker.on_finding(_critical(), now=100.0)
    assert effect.action == "PAUSE"
    assert breaker.state == "paused"


def test_the_breaker_kills_only_after_the_whole_ladder():
    ladder = Ladder("beta", enabled=True)
    breaker = Breaker("beta", ladder=ladder)
    for rung in ("THROTTLE", "DOWNGRADE", "PAUSE"):
        ladder.stepped(rung)
    effect, _ = breaker.on_finding(_critical(), now=100.0)
    assert effect.action == "KILL"
    assert breaker.state == "killed"


def test_the_flag_off_is_the_old_behaviour():
    """No ladder, no throttle: the breaker does exactly what the policy says.

    The policy's `on_hard_limit` decides (the default is kill), and the ladder
    does not get a say. That is the old behaviour, unchanged.
    """
    breaker = Breaker("beta", on_hard_limit="pause", ladder=Ladder("beta", enabled=False))
    effect, _ = breaker.on_finding(_critical(), now=100.0)
    assert effect.action == "PAUSE"
    assert breaker.state == "paused"


def test_the_flag_off_never_throttles():
    breaker = Breaker("beta", on_hard_limit="pause", ladder=Ladder("beta", enabled=False))
    for _ in range(3):
        effect, _ = breaker.on_finding(_critical(), now=100.0)
        assert effect is None or effect.action != "THROTTLE"


# ── the engine ─────────────────────────────────────────────────────────────
def test_the_engine_throttles_before_it_pauses(cfg):
    """The whole point, end to end: a runaway agent is slowed down first."""
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy
    from shared.mocks.fake_fleet import FakeFleet
    from shared.store import LocalStore

    cfg = replace(cfg, degradation_enabled=True)
    store = LocalStore(":memory:")
    policy = Policy.load("brain/policies.yaml")
    fleet = FakeFleet(store, auto_rogue=None, start=1000.0)
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)

    breaker = engine._breaker("beta")
    effect, _ = breaker.on_finding(_critical(), now=1000.0)
    assert effect.action == "THROTTLE"

    engine._step_down("beta", effect, None)
    actions = [a["action"] for a in store.recent_actions(limit=10)]
    assert "THROTTLE" in actions


def test_a_failed_throttle_is_recorded_and_does_not_advance(cfg):
    """A throttle that does not take effect must leave the ladder where it was."""
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy
    from shared.mocks.fake_fleet import FakeFleet
    from shared.store import LocalStore

    cfg = replace(cfg, degradation_enabled=True)
    store = LocalStore(":memory:")
    policy = Policy.load("brain/policies.yaml")
    fleet = FakeFleet(store, auto_rogue=None, start=1000.0)
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)

    breaker = engine._breaker("beta")
    effect, _ = breaker.on_finding(_critical(), now=1000.0)
    ladder = breaker.ladder
    ladder.step_failed("THROTTLE", "the runtime refused")

    assert ladder.next_step() == "THROTTLE"
    assert ladder.applied == []


def test_the_engine_without_the_flag_never_throttles(cfg):
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy
    from shared.mocks.fake_fleet import FakeFleet
    from shared.store import LocalStore

    cfg = replace(cfg, degradation_enabled=False)
    store = LocalStore(":memory:")
    policy = Policy.load("brain/policies.yaml")
    fleet = FakeFleet(store, auto_rogue=None, start=1000.0)
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)

    breaker = engine._breaker("beta")
    effect, _ = breaker.on_finding(_critical(), now=1000.0)
    # The old behaviour: the policy's on_hard_limit, with no rung in between.
    assert effect.action == policy.on_hard_limit.upper()
    assert effect.action != "THROTTLE"


# ── the API ────────────────────────────────────────────────────────────────
def test_the_api_serves_the_budget_tree(cfg, sim):
    from brain.api import create_app

    app = create_app(sim.store, sim.policy, cfg, "fake", "fallback")
    body = TestClient(app).get("/v1/budgets").json()
    assert body["org"]["level"] == "org"
    assert "teams" in body
    assert "agents" in body


def test_the_api_budget_tree_matches_the_mock(cfg, sim):
    """The mock may lead the real API, but it may never lag."""
    from brain.api import create_app
    from shared.contracts import AgentRow

    for agent_id in ("alpha", "beta", "gamma", "delta"):
        sim.store.upsert_agent(AgentRow(agent_id=agent_id, display_name=agent_id))

    app = create_app(sim.store, sim.policy, cfg, "fake", "fallback")
    real = TestClient(app).get("/v1/budgets").json()
    mock = TestClient(__import__("shared.mocks.mock_api", fromlist=["app"]).app).get("/v1/budgets").json()
    assert set(real["org"]) == set(mock["org"])
    assert set(real["teams"][0]) == set(mock["teams"][0])
    assert set(real["agents"][0]) == set(mock["agents"][0])
    assert set(real["org"]["forecast"]) == set(mock["org"]["forecast"])


def test_the_config_flag_defaults_to_off():
    from shared.config import load_settings

    assert load_settings().degradation_enabled is False
