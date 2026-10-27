"""Dashboard smoke tests with Streamlit AppTest: it must render with an empty and with a populated database."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import shared.store as store_module
from shared.contracts import ActionRow, AlertRow, MetricRow
from shared.store import LocalStore

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
EVIL = "<script>alert(1)</script>"


def iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = LocalStore(str(tmp_path / "dash.db"))
    monkeypatch.setattr(store_module, "_store", s)
    return s


def run() -> AppTest:
    return AppTest.from_file(APP, default_timeout=30).run()


def page(at: AppTest) -> str:
    return " ".join(m.value for m in [*at.markdown, *at.caption])


def populate(store, evil_by: str = "rules") -> None:
    store.insert_alert(AlertRow("sentinel", "info", "sentinel_heartbeat", "alive", created_at=iso(1)))
    for i in range(5):
        for agent, status in (("alpha", "running"), ("beta", "killed"), (EVIL, "running")):
            store.insert_metric(MetricRow(agent, "c1", 1000 * (i + 1), 0.5, 5000, 150000, 2, 80.0, 16.0,
                                          status, created_at=iso(30 - i * 5)))
    store.insert_alert(AlertRow("beta", "critical", "fallback_verdict",
                                "KILL (80%, infinite_loop): same prompt 9x", created_at=iso(20)))
    store.insert_alert(AlertRow("beta", "info", "brain_cost", "x [spent_usd=0.002000 saved_usd=1.4000]", created_at=iso(19)))
    store.insert_action(ActionRow("beta", "KILL", "fallback", "same prompt 9x", created_at=iso(19)))
    store.insert_action(ActionRow(EVIL, "KILL", evil_by, "limit", created_at=iso(5)))


def test_empty_database_renders_without_exceptions(store):
    at = run()
    assert not at.exception
    assert "Offline" in page(at) and "No agents reporting yet" in page(at)


def test_populated_database_renders_without_exceptions(store):
    populate(store)
    at = run()
    assert not at.exception
    text = page(at)
    assert "Online" in text and "spent to save $1.40" in text
    assert {b.label for b in at.button if b.label.startswith("Simulate rogue")} == {
        "Simulate rogue: alpha", "Simulate rogue: beta", f"Simulate rogue: {EVIL}"}
    assert not at.selectbox                                  # the useless rogue-type select is gone


def test_latest_decision_is_the_newest_of_any_kind(store):
    populate(store)
    text = page(at := run())
    assert "Decided by <b" in text and "rules" in text       # newest = KILL by rules, not the older brain verdict
    store.insert_action(ActionRow("alpha", "PAUSE", "human", "quarantine", created_at=iso(1)))
    text = page(run())
    assert ">PAUSE <span" in text and "<b style=\"color:#E6EAF0\">human</b>" in text
    assert not at.exception


def test_brain_verdict_shows_confidence_and_pattern(store):
    store.insert_alert(AlertRow("beta", "critical", "claude_verdict",
                                "KILL (91%, token_bomb): huge prompts", created_at=iso(2)))
    text = page(run())
    assert "91%" in text and "token_bomb" in text and ">claude</b>" in text


def test_agent_names_and_by_column_are_html_escaped(store):
    populate(store, evil_by="<img src=x>")
    at = run()
    assert not at.exception
    text = page(at)
    assert EVIL not in text and "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<img src=x>" not in text and "&lt;img src=x&gt;" in text
