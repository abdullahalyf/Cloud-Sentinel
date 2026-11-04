"""The dashboard client works against the mock API (no network: requests are routed to a TestClient)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_client  # noqa: E402
from shared.mocks.mock_api import app  # noqa: E402


def test_client_against_mock(monkeypatch):
    tc = TestClient(app)
    monkeypatch.setattr(api_client.httpx, "request",
                        lambda method, url, timeout=None, **kw: tc.request(method, url.replace(api_client.API_URL, ""), **kw))
    assert api_client.health()["mode"] == "mock"
    assert len(api_client.fleet()) == 4
    assert api_client.memory("beta")["content"]["order_4471"]
    assert api_client.memory("nobody") is None
    saved = api_client.save_memory("beta", {"order_4471": "cancelled"}, "fix", base_version=1)
    assert saved["version"] == 2
    pending = api_client.tool_calls(status="pending")
    assert api_client.decide(pending[0]["id"], "deny")["decision"] == "deny"
    assert api_client.command("beta", "RESUME")["status"] == "pending"
    assert api_client.roi()["saved_usd"] > 0
