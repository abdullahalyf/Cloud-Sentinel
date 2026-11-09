"""
The budget is a *session* budget (CONTRACTS §11), so a restart begins a new session
and the spend of the old one must not count against the new one.

These tests check that:
  - an agent killed for spending too much can be revived
  - a restart really does start the session's spend at zero
  - a restart does not turn the budget into a free pass: the spend accumulates again
  - the refund agent's budget outlives the approval window, so the 50,000 BDT refund
    can actually reach a human

The bug they pin down, seen live in the local demo run:

    delta | RESTART | restarted on probation
    delta | KILL     | Hard limit: spent $0.202 of $0.20 budget   <-- 2 ms later

The agent was killed again for money it had already spent, so it could never come back,
and the demo could not be run twice.
"""
from dataclasses import replace

from brain.policy import Policy
from brain.state import AgentWindow
from shared.config import settings


def _span(cost: float = 0.01, tokens: int = 100) -> dict:
    """A chat span, which is what carries the cost and the tokens."""
    return {
        "operation": "chat", "name": "chat sim", "agent_id": "delta",
        "input_tokens": tokens, "output_tokens": 0, "cost_usd": cost,
        "start_ts": 1000.0, "provider": "sim", "model": "sim",
    }


# ── the session boundary ──────────────────────────────────────────────────────


def test_a_restart_starts_the_session_spend_at_zero():
    """The whole point: the money spent before the restart is not the new session's."""
    win = AgentWindow("delta")
    win.add(_span(cost=0.10, tokens=500))
    win.add(_span(cost=0.10, tokens=500))
    assert win.spend_usd == 0.20 and win.total_tokens == 1000

    win.reset_activity()

    assert win.spend_usd == 0.0
    assert win.total_tokens == 0


def test_a_restart_also_forgets_the_old_activity():
    """The old behaviour: the agent is judged on fresh behaviour only."""
    win = AgentWindow("delta")
    win.add(_span())
    win.reset_activity()
    assert not win.chats and not win.tools


def test_the_spend_accumulates_again_after_the_restart():
    """A reset is not a free pass: the next span costs what it costs."""
    win = AgentWindow("delta")
    win.add(_span(cost=0.10))
    win.reset_activity()
    win.add(_span(cost=0.05))
    assert win.spend_usd == 0.05


# ── the agent can come back ───────────────────────────────────────────────────


def test_an_agent_killed_for_spending_can_be_revived(sim):
    """Killed for the budget → restarted → it must not be killed again for the old spend."""
    sim.command("delta", "SET_BUDGET", budget_usd=0.05)  # tiny, so it dies quickly
    sim.run(200)
    assert sim.state("delta") == "killed"

    sim.command("delta", "RESTART")
    sim.run(2)

    assert sim.state("delta") == "probation"
    # and it stays alive: no second kill for the spend of the old session
    kills = [a for a in sim.store.recent_actions() if a["action"] == "KILL" and a["agent_id"] == "delta"]
    assert len(kills) == 1


def test_a_revived_agent_can_be_killed_again_for_new_spending(sim):
    """The budget still applies to the new session — the reset is not a loophole."""
    sim.command("delta", "SET_BUDGET", budget_usd=0.05)
    sim.run(200)
    assert sim.state("delta") == "killed"

    sim.command("delta", "RESTART")
    sim.run(200)   # the new session spends again, so it dies again

    assert sim.state("delta") == "killed"
    kills = [a for a in sim.store.recent_actions() if a["action"] == "KILL" and a["agent_id"] == "delta"]
    assert len(kills) == 2


# ── the budget has to outlive the approval window ─────────────────────────────


def test_the_refund_agents_budget_outlives_the_approval_window(sim):
    """A budget smaller than the approval window kills the agent before a human
    can approve, and the 50,000 BDT refund expires unheard.

    The budget buys *time*, so the comparison is against the burn rate: how long
    can the agent keep working before its budget runs out?
    """
    policy = Policy.load("brain/policies.yaml")
    timeout = settings.tool_approval_timeout_seconds

    # measure the agent's own burn rate over 60 seconds of normal work
    sim.run(60)
    win = sim.engine.windows["delta"]
    burn_per_second = win.spend_usd / 60.0
    assert burn_per_second > 0

    seconds_the_budget_buys = policy.budget_for("delta") / burn_per_second
    assert seconds_the_budget_buys > timeout, (
        f"delta's budget (${policy.budget_for('delta'):.2f}) only buys "
        f"{seconds_the_budget_buys:.0f}s of work, but the approval window is {timeout:.0f}s")


def test_the_refund_is_held_and_the_agent_is_still_alive_to_wait(sim):
    """The card must still be there a good while after the call was made."""
    sim.fleet.go_rogue("delta", "bad_tool_call", sim.now)
    sim.run(5)
    pending = sim.store.list_tool_calls(status="pending")
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "issue_refund"
    assert pending[0]["args"]["amount"] == 50000
    # the agent has not been killed while the human is reading the card
    assert sim.state("delta") != "killed"
