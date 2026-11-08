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


# The mock and the real API must have the same shape.
#
# They live in **different folders**, so a change to one cannot land in the same PR as
# the other: the contract lands the mock first, and the brain branch that implements the
# same shape on the real API follows it. In between, the mock leads — it has fields the
# real API does not have yet.
#
# So the rule is one-sided: **the real API's fields must be a subset of the mock's.** The
# mock may lead; the mock may never lag. A field the real API has and the mock does not
# is a bug, because a client written against the mock would break on the real thing.
#
# The gaps are recorded in docs/CONTRACTS.md ("the mock may lead the real API"), not here.
# A test that pinned the exact gap list would have to be edited by whichever side closed
# it — and the side that closes it is usually the one that is not allowed to edit
# shared/. That is how a parity test ends up blocking the very change it was written to
# check.
#
# This list is the machine-readable half of that record: the fields the mock has and the
# real API does not (yet). It is empty when the two have caught up.
MOCK_AHEAD_OF_REAL: dict[str, set[str]] = {
    # A8's gap — /v1/health gained "workers" and "agents_total" — closed when b22d509 merged.
}


def test_mock_and_real_api_have_the_same_shapes(sim, cfg):
    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.fleet.go_rogue("delta", "bad_tool_call", sim.now)
    sim.run(30)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for path in GETS:
        r, m = real.get(path).json(), mock.get(path).json()
        # The real API's fields must all be in the mock. The mock may have more: it leads.
        missing = keys(r) - keys(m)
        assert not missing, f"{path}: the mock is missing {sorted(missing)} that the real API has"
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


def test_the_recorded_gaps_are_real_gaps(sim, cfg):
    """Every gap recorded in docs/CONTRACTS.md must be one the mock really leads on.

    This is the "the record is not fantasy" check. It does not insist the gap still
    exists — the brain side closes it — only that the mock really has the fields, so
    the record cannot drift into naming fields nobody ever added.
    """
    sim.run(3)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for path, fields in MOCK_AHEAD_OF_REAL.items():
        m = keys(mock.get(path).json())
        assert fields <= m, f"{path}: the mock should have {sorted(fields)}"


def test_the_shapes_are_the_same_now(sim, cfg):
    """The mock and the real API should have caught up: the same fields, not just the
    same rule. A8 was the last gap — the workers on /v1/health.

    This is the check that the two-sided parity is back. While a gap is open the shapes
    differ, and this test says so by name, so the next person knows what is left.
    """
    sim.run(3)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for path in GETS:
        r, m = keys(real.get(path).json()), keys(mock.get(path).json())
        assert r == m, (
            f"{path}: the real API has {sorted(r - m)} that the mock does not, and the mock has "
            f"{sorted(m - r)} that the real API does not. If the mock leads, record it in "
            f"docs/CONTRACTS.md and in MOCK_AHEAD_OF_REAL")


def test_the_explain_endpoint_has_the_same_shape_on_both_sides(sim, cfg):
    """`/explain` needs an agent id, so it cannot go in the static GETS list.

    The mock leads here (the contract lands the mock first, the brain branch follows),
    so the real API's fields must be a subset of the mock's until the brain lands.
    """
    sim.run(3)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    r = real.get("/v1/agents/beta/explain")
    m = mock.get("/v1/agents/beta/explain")
    if r.status_code == 404:
        # the brain side has not landed yet — the mock leads, which is allowed
        assert m.status_code == 200, "the mock must serve /explain once the contract lands"
        return
    assert r.status_code == 200 and m.status_code == 200
    rb, mb = r.json(), m.json()
    missing = keys(rb) - keys(mb)
    assert not missing, f"the mock is missing {sorted(missing)} that the real API has"


def test_the_tool_risk_endpoint_has_the_same_shape_on_both_sides(sim, cfg):
    """`/tool-risk` (A14) — the mock leads here, the brain branch follows.

    The real API's fields must be a subset of the mock's until the brain lands.
    """
    sim.run(3)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    r = real.get("/v1/tool-risk")
    m = mock.get("/v1/tool-risk")
    if r.status_code == 404:
        # the brain side has not landed yet — the mock leads, which is allowed
        assert m.status_code == 200, "the mock must serve /tool-risk once the contract lands"
        return
    assert r.status_code == 200 and m.status_code == 200
    rb, mb = r.json(), m.json()
    missing = keys(rb) - keys(mb)
    assert not missing, f"the mock is missing {sorted(missing)} that the real API has"
    assert keys(rb["counts"]) == keys(mb["counts"])


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
