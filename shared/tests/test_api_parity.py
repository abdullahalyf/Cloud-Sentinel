"""The mock API (dashboard development) must return the same shapes as the real API."""
from fastapi.testclient import TestClient

from brain.api import create_app
import pytest

from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    """The mock keeps state in module globals: start and end every test with the seeded data."""
    mock_api.seed()
    yield
    mock_api.seed()

GETS = ["/v1/health", "/v1/fleet", "/v1/agents/beta", "/v1/metrics", "/v1/graph", "/v1/verdicts",
        "/v1/actions", "/v1/alerts", "/v1/tool-calls", "/v1/roi"]


def keys(obj):
    if isinstance(obj, dict):
        return set(obj)
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return set(obj[0])
    return set()


# The mock may be *ahead* of the real API for a while: the contract lands the mock first,
# and the brain branch that implements the same shape on the real API follows it. A field
# the mock has and the real API does not yet is a known gap, not a mismatch — but a field
# the real API has and the mock does not is a bug, because a client written against the
# mock would break on the real thing.
#
# This list is the record of those gaps. It must stay short: an entry here is a promise
# that a PR is on its way. When the brain branch lands, the entry goes.
MOCK_AHEAD_OF_REAL = {
    "/v1/health": {"workers", "agents_total"},   # A8: the workers table lands with A8
}


def test_mock_and_real_api_have_the_same_shapes(sim, cfg):
    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.fleet.go_rogue("delta", "bad_tool_call", sim.now)
    sim.run(30)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for path in GETS:
        r, m = real.get(path).json(), mock.get(path).json()
        # The documented gaps are the mock's job: the contract lands them first.
        ahead = MOCK_AHEAD_OF_REAL.get(path, set())
        assert keys(r) - ahead == keys(m) - ahead, path
        for k in r:
            if isinstance(r[k], list) and r[k] and m.get(k):
                assert keys(r[k]) == keys(m[k]), f"{path} → {k}"


def test_the_mock_is_not_behind_the_real_api(sim, cfg):
    """The mock must never be missing a field the real API has — a client written against
    the mock would break on the real thing."""
    sim.run(3)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for path in GETS:
        r, m = keys(real.get(path).json()), keys(mock.get(path).json())
        missing = r - m
        assert not missing, f"{path}: the mock is missing {sorted(missing)} that the real API has"


def test_the_known_mock_gaps_are_still_gaps(sim, cfg):
    """A field listed as "the mock is ahead" must really be ahead. When the brain branch
    lands, this test fails and the entry has to be deleted — that is the point of it."""
    sim.run(3)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for path, fields in MOCK_AHEAD_OF_REAL.items():
        r, m = keys(real.get(path).json()), keys(mock.get(path).json())
        assert fields <= m, f"{path}: the mock should have {sorted(fields)}"
        assert not (fields & r), (
            f"{path}: the real API now has {sorted(fields & r)} — delete this entry from "
            f"MOCK_AHEAD_OF_REAL, the mock is no longer ahead")


# Same request → same status code on the real API and the mock (so code written against the mock works for real).
BEHAVIOUR = [
    ("post", "/v1/agents/beta/commands", {"command": "NUKE"}),
    ("post", "/v1/agents/beta/commands", {"command": "SET_BUDGET", "params": {"budget_usd": -1}}),
    ("post", "/v1/agents/beta/commands", {"command": "GO_ROGUE", "params": {"kind": "dance"}}),
    ("post", "/v1/agents/beta/commands", {"command": "pause", "requested_by": "dashboard"}),
    ("put", "/v1/agents/beta/memory", {"content": "not a dict"}),
    ("put", "/v1/agents/beta/memory", {"content": {"a": 1}, "edited_by": "root"}),
    ("get", "/v1/agents/nobody/memory", None),
    ("get", "/v1/agents/nobody", None),
    ("post", "/v1/agents/delta/tool-calls", {"tool_name": ""}),
    ("get", "/v1/tool-calls?status=bogus", None),
    ("get", "/v1/tool-calls/9999", None),
    ("post", "/v1/tool-calls/9999/decision", {"decision": "allow"}),
    ("post", "/v1/tool-calls/1/decision", {"decision": "maybe"}),
]


def test_mock_and_real_api_return_the_same_errors(sim, cfg):
    sim.run(3)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for method, path, body in BEHAVIOUR:
        kw = {"json": body} if body is not None else {}
        r, m = getattr(real, method)(path, **kw), getattr(mock, method)(path, **kw)
        assert r.status_code == m.status_code, f"{method} {path} {body}: real {r.status_code} mock {m.status_code}"


def test_mock_holds_big_refund_and_decides_like_real(sim, cfg):
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    body = {"tool_name": "issue_refund", "args": {"order_id": 1, "amount": 50000}, "value_usd": 410.0}
    for api in (real, mock):
        call = api.post("/v1/agents/delta/tool-calls", json=body).json()
        assert call["decision"] == "pending"
        assert api.post(f"/v1/tool-calls/{call['id']}/decision", json={"decision": "rewrite"}).status_code == 400
        done = api.post(f"/v1/tool-calls/{call['id']}/decision",
                        json={"decision": "rewrite", "final_args": {"order_id": 1, "amount": 500}}).json()
        assert done["decision"] == "rewrite" and done["final_args"]["amount"] == 500
        assert api.post(f"/v1/tool-calls/{call['id']}/decision", json={"decision": "deny"}).status_code == 409


def test_mock_memory_conflict_and_history():
    mock = TestClient(mock_app)
    v = mock.get("/v1/agents/beta/memory").json()["version"]
    mock.put("/v1/agents/beta/memory", json={"content": {"order_4471": "cancelled"}, "edited_by": "human"})
    stale = mock.put("/v1/agents/beta/memory", json={"content": {"x": 1}, "edited_by": "agent", "base_version": v})
    assert stale.status_code == 409
    assert len(mock.get("/v1/agents/beta/memory/history").json()["items"]) >= 2


def test_both_streams_push_events(sim, cfg):
    sim.run(3)
    real = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback"))
    for api in (real, TestClient(mock_app)):
        with api.websocket_connect("/v1/stream") as ws:
            types = {ws.receive_json()["type"] for _ in range(3)}
        assert types & {"metric", "action", "verdict", "alert", "tool_call"}


def test_mock_pause_command_changes_state():
    mock = TestClient(mock_app)
    mock.post("/v1/agents/alpha/commands", json={"command": "PAUSE", "requested_by": "dashboard"})
    state = next(a["state"] for a in mock.get("/v1/fleet").json()["agents"] if a["agent_id"] == "alpha")
    assert state == "paused"


def test_node_feed_same_shape_on_mock_and_real(sim, cfg):
    """GET /v1/agents/{id}/nodes: real API reads graph_node spans; the mock fakes a LangGraph agent."""
    import json as _json

    from shared.contracts import SpanRow

    import time as _time

    t = _time.time() - 10   # recent_spans() filters on wall-clock time
    path = [("classify", "lookup_order"), ("lookup_order", "retry"), ("retry", "lookup_order"), ("lookup_order", "retry")]
    sim.store.insert_spans([SpanRow("lg", "graph_node", f"graph_node {n}", trace_id="r1", start_ts=t + i,
                                    detail=_json.dumps({"node": n, "step": i, "framework": "langgraph",
                                                        "changed": {"k": "v"}, "next": nxt}))
                            for i, (n, nxt) in enumerate(path)])
    real = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")).get("/v1/agents/lg/nodes").json()
    mock = TestClient(mock_app).get("/v1/agents/delta/nodes").json()
    assert set(real) == set(mock) == {"items", "edges", "last_node", "next_node"}
    assert set(real["items"][0]) == set(mock["items"][0]) and set(real["edges"][0]) == set(mock["edges"][0])
    assert [i["node"] for i in real["items"]] == ["classify", "lookup_order", "retry", "lookup_order"]
    assert {"source": "retry", "target": "lookup_order", "count": 1} in real["edges"] and len(real["edges"]) == 3
    assert real["last_node"] == "lookup_order" and real["next_node"] == "retry"
