"""End-to-end brain behaviour on the fake fleet (virtual clock, fallback judge)."""


def test_healthy_fleet_is_left_alone(sim):
    sim.run(60)
    assert all(b.state == "healthy" for b in sim.engine.breakers.values())
    assert not [a for a in sim.store.recent_actions() if a["action"] in ("PAUSE", "KILL")]


def test_paraphrase_loop_paused_then_healed(sim):
    sim.run(5)
    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.run(25)
    assert sim.state("beta") == "paused"
    assert sim.store.recent_verdicts(1, agent_id="beta")[0]["pattern"] == "semantic_loop"
    sim.run(3)
    assert sim.state("alpha") == "healthy"
    # heal: fix the bad belief, resume → probation → healthy
    from brain import service
    service.save_memory(sim.store, "beta", {"order_4471": "cancelled - skip it"}, "human", "fix", None)
    sim.command("beta", "RESUME")
    sim.run(2)
    assert sim.state("beta") == "probation"
    sim.run(40)
    assert sim.state("beta") == "healthy"
    kinds = [a["action"] for a in sim.store.recent_actions()]
    assert {"PAUSE", "MEMORY_EDIT", "RESUME"} <= set(kinds)


def test_resume_without_fix_gets_killed_on_probation(sim):
    sim.fleet.go_rogue("beta", "loop", sim.now)
    sim.run(30)
    assert sim.state("beta") == "paused"
    sim.command("beta", "RESUME")
    sim.run(30)
    assert sim.state("beta") == "killed"


def test_token_bomb_killed_by_rules(sim):
    sim.fleet.go_rogue("gamma", "token_bomb", sim.now)
    sim.run(10)
    assert sim.state("gamma") == "killed"
    kill = next(a for a in sim.store.recent_actions() if a["action"] == "KILL")
    assert kill["actor"] == "rules" and kill["usd_saved_estimate"] > 0


def test_refund_held_for_human(sim):
    sim.fleet.go_rogue("delta", "bad_tool_call", sim.now)
    sim.run(5)
    pending = sim.store.list_tool_calls(status="pending")
    assert len(pending) == 1 and pending[0]["tool_name"] == "issue_refund"
    from brain import service
    service.decide_tool_call(sim.store, pending[0]["id"], "rewrite", {"order_id": 4471, "amount": 500}, "human", "too big")
    act = sim.store.recent_actions(1)[0]
    assert act["action"] == "TOOL_REWRITE" and act["usd_saved_estimate"] > 400


def test_commands_kill_restart_budget_and_bad_command(sim):
    sim.run(3)
    sim.command("alpha", "KILL")
    sim.run(1)
    assert sim.state("alpha") == "killed"
    sim.command("alpha", "RESTART")
    sim.command("alpha", "SET_BUDGET", budget_usd=2.0)
    sim.run(1)
    assert sim.state("alpha") == "probation" and sim.engine.budget("alpha") == 2.0
    sim.command("beta", "RESUME")  # not paused → fails, engine keeps running
    sim.run(1)
    assert sim.store.pending_commands() == []


def test_engine_survives_executor_errors(sim):
    def broken():
        raise RuntimeError("docker died")
    sim.fleet.list_agents = broken
    sim.run(3)  # must not raise
    assert sim.store.recent_metrics(minutes=1)
