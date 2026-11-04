from fastapi.testclient import TestClient

from brain.api import create_app


def client(sim, cfg):
    return TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback"))


def test_fleet_commands_memory_tool_calls(sim, cfg):
    sim.run(3)
    c = client(sim, cfg)
    assert c.get("/v1/health").json()["contract"] == 2
    agents = c.get("/v1/fleet").json()["agents"]
    assert {a["agent_id"] for a in agents} == {"alpha", "beta", "gamma", "delta"}
    assert c.post("/v1/agents/beta/commands", json={"command": "PAUSE"}).json()["status"] == "pending"
    assert c.post("/v1/agents/beta/commands", json={"command": "EXPLODE"}).status_code == 400
    assert c.get("/v1/agents/zzz/memory").status_code == 404
    m = c.put("/v1/agents/beta/memory", json={"content": {"a": 1}, "edited_by": "human"}).json()
    assert m["version"] == 1
    conflict = c.put("/v1/agents/beta/memory", json={"content": {"a": 2}, "edited_by": "agent", "base_version": 0})
    assert conflict.status_code == 409
    call = c.post("/v1/agents/delta/tool-calls", json={"tool_name": "issue_refund", "args": {"amount": 9000},
                                                       "value_usd": 75}).json()
    assert call["decision"] == "pending"
    assert c.get("/v1/tool-calls", params={"status": "pending"}).json()["items"][0]["id"] == call["id"]
    done = c.post(f"/v1/tool-calls/{call['id']}/decision", json={"decision": "deny"}).json()
    assert done["decision"] == "deny"
    assert c.post(f"/v1/tool-calls/{call['id']}/decision", json={"decision": "allow"}).status_code == 409
    assert c.post("/v1/agents/delta/tool-calls", json={"tool_name": "delete_all"}).json()["decision"] == "deny"
    assert c.get("/v1/roi").json()["saved_usd"] >= 75
    assert "nodes" in c.get("/v1/graph").json()


def test_token_auth(sim, cfg):
    from dataclasses import replace
    c = client(sim, replace(cfg, api_token="s3cret"))
    assert c.get("/v1/fleet").status_code == 401
    assert c.get("/v1/fleet", headers={"X-CS-Token": "s3cret"}).status_code == 200
    assert c.get("/v1/health").status_code == 200


def test_tripped_agent_gets_no_tools(sim, cfg):
    from shared.contracts import AgentRow
    sim.store.upsert_agent(AgentRow("ghost", state="paused"))
    call = client(sim, cfg).post("/v1/agents/ghost/tool-calls", json={"tool_name": "search_kb"}).json()
    assert call["decision"] == "deny" and "paused" in call["reason"]
