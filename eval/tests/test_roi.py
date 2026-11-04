from eval.roi import build_report, spend_by_agent, total_spend


def test_spend_and_savings():
    spans = [{"agent_id": "a", "cost_usd": 0.1}, {"agent_id": "b", "cost_usd": 0.2}, {"agent_id": "a", "cost_usd": 0.3}]
    actions = [{"id": 1, "agent_id": "a", "action": "PAUSE", "actor": "claude", "usd_saved_estimate": 2.5},
               {"id": 2, "agent_id": "b", "action": "WARN", "actor": "claude", "usd_saved_estimate": 0},
               {"id": 3, "agent_id": "b", "action": "TOOL_DENY", "actor": "human", "usd_saved_estimate": 410}]
    assert total_spend(spans) == 0.6 and spend_by_agent(spans) == {"a": 0.4, "b": 0.2}
    r = build_report(spans, actions, [], 60)
    assert r["saved_usd"] == 412.5 and r["interventions"] == 2 and "60 min" in r["formula"]


def _task(trace, agent, status, *child_costs):
    rows = [{"trace_id": trace, "agent_id": agent, "operation": "invoke_agent", "task_id": f"t-{trace}",
             "task_status": status, "cost_usd": 0}]
    rows += [{"trace_id": trace, "agent_id": agent, "operation": "chat", "cost_usd": c} for c in child_costs]
    return rows


def test_cost_is_attributed_to_tasks_and_success():
    from eval.roi import cost_per_successful_task, tasks_by_agent

    spans = (_task("1", "a", "success", 0.10, 0.05) + _task("2", "a", "failure", 0.20) + _task("3", "a", "success", 0.05)
             + _task("4", "b", "abandoned", 0.30)
             + [{"trace_id": "open", "agent_id": "b", "operation": "chat", "cost_usd": 0.40}])  # task still running
    per = tasks_by_agent(spans)
    assert per["a"] == {"tasks": 3, "succeeded": 2, "failed": 1, "abandoned": 0, "success_rate": 0.667,
                        "spend_usd": 0.4, "wasted_usd": 0.2, "unattributed_usd": 0.0, "cost_per_success_usd": 0.2}
    assert per["b"]["succeeded"] == 0 and per["b"]["wasted_usd"] == 0.7 and per["b"]["unattributed_usd"] == 0.4
    assert per["b"]["cost_per_success_usd"] == 0.0
    assert cost_per_successful_task(spans) == round(1.1 / 2, 4)   # fully loaded: all spend ÷ successes


def test_zero_tasks_and_report_keys():
    from eval.roi import cost_per_successful_task

    assert cost_per_successful_task([{"agent_id": "a", "cost_usd": 1.0}]) == 0.0
    r = build_report(_task("1", "a", "success", 0.1), [], [], 60)
    assert r["tasks_total"] == 1 and r["tasks_succeeded"] == 1 and r["cost_per_successful_task_usd"] == 0.1
    assert r["wasted_usd"] == 0 and r["tasks_by_agent"]["a"]["success_rate"] == 1.0


def test_roi_on_the_fake_fleet_shows_waste_from_a_loop(sim):
    """End to end: a looping agent's per-task numbers get worse than a healthy one's."""
    from eval.roi import tasks_by_agent

    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.run(20)
    per = tasks_by_agent(sim.store.spans_after(0, limit=100_000))   # virtual clock: read every span
    assert per["alpha"]["success_rate"] > per["beta"]["success_rate"]
    assert per["beta"]["wasted_usd"] > per["alpha"]["wasted_usd"]
