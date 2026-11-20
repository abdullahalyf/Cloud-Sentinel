"""CS_DEMO_BUDGET_USD: a budget floor for an always-on public demo. Off by default."""
from dataclasses import replace

from brain.budget import tree_from_store
from brain.policy import Policy
from shared.config import load_settings

POLICY = {"defaults": {"budget_usd": 0.5}, "agents": {"gamma": {"budget_usd": 1.0}}}


def test_budget_for_without_floor_is_unchanged():
    p = Policy.from_dict(POLICY)
    assert p.budget_for("beta") == 0.5 and p.budget_for("gamma") == 1.0


def test_floor_raises_small_budgets_only():
    p = Policy.from_dict(POLICY)
    assert p.budget_for("beta", 100) == 100 and p.budget_for("gamma", 100) == 100
    assert p.budget_for("gamma", 0.75) == 1.0      # a bigger policy budget stays


def test_setting_defaults_to_off(monkeypatch):
    monkeypatch.delenv("CS_DEMO_BUDGET_USD", raising=False)
    assert load_settings().demo_budget_usd == 0.0
    monkeypatch.setenv("CS_DEMO_BUDGET_USD", "100")
    assert load_settings().demo_budget_usd == 100.0


def test_engine_and_budget_report_use_the_floor(cfg):
    from brain.tests.conftest import Sim

    sim = Sim(replace(cfg, demo_budget_usd=100.0))
    sim.run(3)                                     # the agents appear in the store
    assert sim.engine.budget("beta") == 100.0
    assert sim.engine.budget("gamma") == 100.0
    node = tree_from_store(sim.store, sim.policy, replace(cfg, demo_budget_usd=100.0)).agent("beta")
    assert 100.0 in node.values()
    sim.engine.budgets["beta"] = 2.0               # an explicit SET_BUDGET still wins
    assert sim.engine.budget("beta") == 2.0


def test_floor_off_keeps_the_policy_budgets(sim):
    assert sim.engine.budget("beta") == 0.5 and sim.engine.budget("gamma") == 1.0
