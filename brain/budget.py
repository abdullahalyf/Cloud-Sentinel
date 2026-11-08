"""
The budget tree and the degradation ladder (CONTRACTS §6, B4).

Two ideas carry the whole module:

- **the budget is a tree** — org → team → agent — and every level is the sum
  of the level below it, so one runaway agent cannot eat the fleet's money;
- **the ladder steps down gently** — throttle → downgrade → pause → kill —
  and it never skips a rung.

The *shapes* live in `shared/contracts.py` (the contract folder), so the mock and
the real API say exactly the same thing. What lives here is the **builder**: the
part that knows about the store, the policy and the fleet.

Why the tree matters. A budget is a promise about money, and the money belongs to
somebody. If the fleet has $2.20 and one agent spends all of it, the other three
agents get nothing — and the operator never asked for that. So the fleet's money
is divided into teams, and each team's money into agents, and an agent that
overruns eats *its own share* and no more. The tree says so out loud, so a
dashboard can show it without a spreadsheet.

Why the ladder matters. Killing is the most expensive thing the brain can do:
the agent's state is gone, and the work it was doing is gone with it. But
killing a runaway agent that a throttle would have slowed down is wasteful too.
So the ladder walks from the gentlest step to the harshest, and **it never skips a
rung**: an agent that has not been throttled is not downgraded, because a
downgrade is a bigger promise than a throttle and deserves the smaller one's
evidence. The ladder stops at the first step that *works* — and if a step
fails, the ladder does not move on silently, because a brain that believes the
agent was throttled when it was not is worse than one that never tried.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from shared.contracts import (DEGRADATION_LADDER, budget_forecast, budget_node,
                              budget_report, degradation_plan)

log = logging.getLogger("brain.budget")


# ─────────────────────────────────────────────────────────────────────────────
# 1. The tree
# ─────────────────────────────────────────────────────────────────────────────

# How the agents are grouped into teams. The team's budget is the sum of its
# agents' budgets, so this mapping is *where* the money goes, not *how much*.
#
# A team id of "" means "no team" — the agent still gets a budget and still
# appears in the tree, just at the org level.
DEFAULT_TEAMS: dict[str, str] = {
    "alpha": "core", "beta": "core", "gamma": "ml", "delta": "ml",
}

# The org id. It is the root of the tree.
ORG_ID = "org"

# How many minutes ahead the forecast looks. One hour is the operator's
# question: "will this be a problem before I go home?"
DEFAULT_HORIZON_MINUTES = 60.0


@dataclass
class BudgetTree:
    """
    The org → team → agent budget tree, with a forecast at every level.

    Built from what the store knows (each agent's spend) and what the policy
    says (each agent's budget). It is a *snapshot*: it says what is true now,
    not what will be true later.
    """

    org: dict
    teams: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    as_of: Optional[float] = None

    def to_report(self) -> dict:
        """The shape the API serves (CONTRACTS §6, BudgetReport)."""
        return budget_report(self.org, self.teams, self.agents, as_of=self.as_of)

    def agent(self, agent_id: str) -> Optional[dict]:
        for node in self.agents:
            if node["id"] == agent_id:
                return node
        return None

    def team(self, team_id: str) -> Optional[dict]:
        for node in self.teams:
            if node["id"] == team_id:
                return node
        return None


def team_of(agent_id: str, teams: Optional[dict[str, str]] = None) -> str:
    """The team an agent belongs to ("" = no team)."""
    return (teams or DEFAULT_TEAMS).get(agent_id, "")


def build_tree(agent_budgets: dict[str, float],
               agent_spends: Optional[dict[str, float]] = None,
               teams: Optional[dict[str, str]] = None,
               burn_rates: Optional[dict[str, float]] = None,
               org_budget: Optional[float] = None,
               horizon_minutes: float = DEFAULT_HORIZON_MINUTES,
               as_of: Optional[float] = None) -> BudgetTree:
    """
    Build the tree from the budgets and the spends.

    The org budget is **computed**, never hand-set: it is the sum of the team
    budgets, and each team budget is the sum of its agents' budgets. A
    hand-set org budget would let the tree disagree with itself, and the tree
    is the whole point.

    `burn_rates` is the $/min each agent is burning right now. An agent with no
    burn rate burns nothing, and the forecast for it says nothing — "exhausted
    in 0 minutes" would be a lie.
    """
    spends = agent_spends or {}
    rates = burn_rates or {}
    mapping = teams if teams is not None else DEFAULT_TEAMS

    agent_nodes: list[dict] = []
    for agent_id in sorted(agent_budgets):
        budget = float(agent_budgets[agent_id] or 0.0)
        spend = float(spends.get(agent_id) or 0.0)
        burn = float(rates.get(agent_id) or 0.0)
        agent_nodes.append(budget_node(
            "agent", agent_id, budget, spend,
            children=[],
            forecast=budget_forecast(budget, spend, burn, horizon_minutes=horizon_minutes)))

    # Group the agents into teams. An agent with no team still gets counted —
    # it is in the org's spend, and hiding it would make the org look cheaper
    # than it is.
    team_ids = sorted({team_of(a["id"], mapping) for a in agent_nodes} - {""})
    team_nodes: list[dict] = []
    for team_id in team_ids:
        members = [a for a in agent_nodes if team_of(a["id"], mapping) == team_id]
        budget = sum(a["budget_usd"] for a in members)
        spend = sum(a["spend_usd"] for a in members)
        # A team's burn rate is the sum of its members' burn rates: the team
        # burns what its agents burn.
        burn = sum(float(rates.get(a["id"]) or 0.0) for a in members)
        team_nodes.append(budget_node(
            "team", team_id, round(budget, 6), round(spend, 6),
            children=[a["id"] for a in members],
            forecast=budget_forecast(round(budget, 6), round(spend, 6), burn,
                                     horizon_minutes=horizon_minutes)))

    # The agents with no team are the org's own agents.
    unassigned = [a for a in agent_nodes if not team_of(a["id"], mapping)]
    org_budget_total = sum(t["budget_usd"] for t in team_nodes) + sum(a["budget_usd"] for a in unassigned)
    org_spend_total = sum(t["spend_usd"] for t in team_nodes) + sum(a["spend_usd"] for a in unassigned)
    org_burn_total = sum(float(rates.get(a["id"]) or 0.0) for a in agent_nodes)

    if org_budget is not None:
        # An explicit org budget is honoured, but the tree is still the truth
        # about the parts: an org budget larger than its teams' is the org's
        # own unallocated money, and smaller is a budget the teams cannot use.
        # The forecast is computed on the number that is actually there.
        org_budget_total = float(org_budget)

    org_node = budget_node(
        "org", ORG_ID, round(org_budget_total, 6), round(org_spend_total, 6),
        children=[t["id"] for t in team_nodes] + [a["id"] for a in unassigned],
        forecast=budget_forecast(round(org_budget_total, 6), round(org_spend_total, 6),
                                 org_burn_total, horizon_minutes=horizon_minutes))

    return BudgetTree(org=org_node, teams=team_nodes, agents=agent_nodes, as_of=as_of)


def tree_from_store(store, policy, cfg, agent_burn_rates: Optional[dict[str, float]] = None,
                    as_of: Optional[float] = None) -> BudgetTree:
    """
    Build the tree from the live fleet: the budgets the policy sets, the spend
    the store has recorded, and the burn rate the brain is seeing right now.
    """
    budgets: dict[str, float] = {}
    spends: dict[str, float] = {}
    for agent in store.list_agents():
        agent_id = agent["agent_id"]
        budgets[agent_id] = float(policy.budget_for(agent_id))
        spends[agent_id] = float(agent.get("spend_usd") or 0.0)
    return build_tree(budgets, spends, teams=DEFAULT_TEAMS,
                      burn_rates=agent_burn_rates, horizon_minutes=cfg.roi_horizon_minutes,
                      as_of=as_of)


# ─────────────────────────────────────────────────────────────────────────────
# 2. The ladder
# ─────────────────────────────────────────────────────────────────────────────

# What each rung *does*. The key is the action it emits; the value says how,
# in words an operator can read in the audit log.
LADDER_MEANING: dict[str, str] = {
    "THROTTLE": "slow the agent down to a fraction of its rate",
    "DOWNGRADE": "move the agent to a cheaper model",
    "PAUSE": "stop the agent but keep its state",
    "KILL": "end the agent and its state",
}

# How much of its rate a throttled agent keeps. It is a fraction, not a
# setting: a throttle that halves the rate is not a throttle, it is a pause.
THROTTLE_FACTOR = 0.25

# How much cheaper the downgraded model is (a fraction of the usual cost).
# The brain does not choose the model — the operator's policy does — it only
# records that the step happened.
DOWNGRADE_FACTOR = 0.5


@dataclass
class Degradation:
    """
    Where an agent stands on the ladder, and what to do next.

    `applied` are the rungs already walked. `next_step` is the next rung, or
    None when the ladder is exhausted (everything has been tried).

    `blocked` is the important one: when a step *failed*, the ladder does not
    move on. `next_step` then stays where it was, and `blocked` says why —
    so a brain can never believe an agent was throttled when it was not.
    """

    applied: list[str] = field(default_factory=list)
    next_step: Optional[str] = None
    exhausted: bool = False
    blocked: Optional[str] = None       # the reason the last step failed
    last_failed: Optional[str] = None   # the rung that failed

    @property
    def plan(self) -> dict:
        """The contract shape (CONTRACTS §6)."""
        return degradation_plan(current_step=None, applied=list(self.applied))


class Ladder:
    """
    The degradation ladder for one agent.

    The ladder is per agent, and it is *stateful*: it remembers which rungs
    have been walked, so it can never skip one. A failed step does not advance
    it — a rung that did not work is a rung that must be tried again (or
    escalated by a human), not a rung to step over.

    With `enabled=False` the ladder is inert: it proposes nothing, and the
    brain does the old thing — pause or kill, straight away. That is the
    default, so the new behaviour is opt-in.
    """

    def __init__(self, agent_id: str, enabled: bool = False):
        self.agent_id = agent_id
        self.enabled = enabled
        self.applied: list[str] = []
        self.failed: dict[str, str] = {}     # rung → why it failed
        self.blocked = False

    # ── asking where we are ──
    def next_step(self) -> Optional[str]:
        """The next rung, or None when the ladder is done."""
        if not self.enabled:
            return None
        if self.failed:
            # A step failed: the ladder is stuck on that rung, not past it.
            return self.failed_rung()
        if len(self.applied) >= len(DEGRADATION_LADDER):
            return None
        return DEGRADATION_LADDER[len(self.applied)]

    def failed_rung(self) -> Optional[str]:
        """The rung the ladder is stuck on (the last one that failed)."""
        if not self.failed:
            return None
        return list(self.failed)[-1]

    def plan(self) -> Degradation:
        next_step = self.next_step()
        return Degradation(
            applied=list(self.applied),
            next_step=next_step,
            exhausted=next_step is None,
            blocked=self.failed_rung() if self.failed else None,
            last_failed=self.failed_rung(),
        )

    def contract_plan(self) -> dict:
        """The plan in the contract's shape (CONTRACTS §6)."""
        p = self.plan()
        return degradation_plan(current_step=p.next_step, applied=list(p.applied))

    # ── moving along it ──
    def stepped(self, rung: str) -> None:
        """Record that a rung was walked successfully."""
        if rung not in DEGRADATION_LADDER:
            return
        if rung not in self.applied:
            self.applied.append(rung)
        # A rung that worked is no longer a failure — the agent moved past it.
        self.failed.pop(rung, None)

    def step_failed(self, rung: str, reason: str = "") -> None:
        """
        Record that a rung **failed**.

        The ladder does not advance. This is the whole point: a failed throttle
        must not silently become a downgrade, because the agent is still
        running at full speed and the brain would believe it was not.
        """
        if rung not in DEGRADATION_LADDER:
            return
        self.failed[rung] = reason or "the step did not take effect"
        log.warning("%s: %s did not take effect (%s) — the ladder stays put",
                    self.agent_id, rung, self.failed[rung])

    def reset(self) -> None:
        """The agent is healthy again: the ladder starts from the top."""
        self.applied = []
        self.failed = {}


def effect_for(step: str, reason: str) -> tuple[str, str]:
    """
    The (action, reason) pair a rung produces.

    The action is the contract's action type, so it lands in the audit log and
    in the `actions` table like any other decision.
    """
    if step not in DEGRADATION_LADDER:
        return "WARN", reason
    meaning = LADDER_MEANING.get(step, "")
    return step, f"{reason} — stepping down: {meaning}".strip(" —")


def throttle_ratio(applied: list[str]) -> float:
    """
    How much of its normal rate an agent that has been throttled keeps.

    Throttled once: the throttle factor. Throttled twice (the ladder went
    around again): the factor twice over, but never below a floor — a rate of
    zero is not a throttle, it is a pause with extra steps.
    """
    count = sum(1 for a in applied if a == "THROTTLE")
    if count <= 0:
        return 1.0
    return max(0.05, THROTTLE_FACTOR ** count)


__all__ = [
    "DEFAULT_HORIZON_MINUTES", "DEFAULT_TEAMS", "Degradation", "DOWNGRADE_FACTOR",
    "LADDER_MEANING", "Ladder", "ORG_ID", "THROTTLE_FACTOR", "BudgetTree",
    "build_tree", "effect_for", "team_of", "throttle_ratio", "tree_from_store",
]
