from eval.roi import build_report, spend_by_agent, total_spend


def test_spend_and_savings():
    spans = [{"agent_id": "a", "cost_usd": 0.1}, {"agent_id": "b", "cost_usd": 0.2}, {"agent_id": "a", "cost_usd": 0.3}]
    actions = [{"id": 1, "agent_id": "a", "action": "PAUSE", "actor": "claude", "usd_saved_estimate": 2.5},
               {"id": 2, "agent_id": "b", "action": "WARN", "actor": "claude", "usd_saved_estimate": 0},
               {"id": 3, "agent_id": "b", "action": "TOOL_DENY", "actor": "human", "usd_saved_estimate": 410}]
    assert total_spend(spans) == 0.6 and spend_by_agent(spans) == {"a": 0.4, "b": 0.2}
    r = build_report(spans, actions, [], 60)
    assert r["saved_usd"] == 412.5 and r["interventions"] == 2 and "60 min" in r["formula"]
