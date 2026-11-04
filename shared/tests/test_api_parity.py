"""The mock API (dashboard development) must return the same shapes as the real API."""
from fastapi.testclient import TestClient

from brain.api import create_app
from shared.mocks.mock_api import app as mock_app

GETS = ["/v1/health", "/v1/fleet", "/v1/agents/beta", "/v1/metrics", "/v1/graph", "/v1/verdicts",
        "/v1/actions", "/v1/alerts", "/v1/tool-calls", "/v1/roi"]


def keys(obj):
    if isinstance(obj, dict):
        return set(obj)
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return set(obj[0])
    return set()


def test_mock_and_real_api_have_the_same_shapes(sim, cfg):
    sim.fleet.go_rogue("beta", "paraphrase_loop", sim.now)
    sim.fleet.go_rogue("delta", "bad_tool_call", sim.now)
    sim.run(30)
    real, mock = TestClient(create_app(sim.store, sim.policy, cfg, "fake", "fallback")), TestClient(mock_app)
    for path in GETS:
        r, m = real.get(path).json(), mock.get(path).json()
        assert keys(r) == keys(m), path
        for k in r:
            if isinstance(r[k], list) and r[k] and m.get(k):
                assert keys(r[k]) == keys(m[k]), f"{path} → {k}"
