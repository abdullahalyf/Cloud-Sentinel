"""The copy-paste snippets in docs/handoff/tamjid-dashboard-data.md really run against real data."""
import re
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from sentinel.brain import Brain
from sentinel.engine import Sentinel
from sentinel.sources import FakeSource
from shared.config import load_settings
from shared.contracts import AlertRow, CommandRow
from shared.store import LocalStore

DOC = Path(__file__).resolve().parent.parent / "docs" / "handoff" / "tamjid-dashboard-data.md"
cfg = replace(load_settings(), anthropic_api_key="", gemini_api_key="", webhook_url="", heartbeat_seconds=0.3)
BLOCKS = re.findall(r"```python\n(.*?)```", DOC.read_text(), re.S)


def load_helpers() -> dict:
    ns: dict = {}
    exec(BLOCKS[0], ns)
    return ns


def ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_online_offline_from_the_heartbeat():
    h = load_helpers()
    beat = lambda s: {"rule": "sentinel_heartbeat", "created_at": ago(s)}  # noqa: E731
    assert h["sentinel_status"]([beat(2), beat(7)])[0] is True
    online, age = h["sentinel_status"]([beat(16), beat(21)])
    assert online is False and 15 < age < 18
    assert h["sentinel_status"]([{"rule": "loop_detected", "created_at": ago(1)}]) == (False, None)
    assert h["sentinel_status"]([]) == (False, None)


def test_verdict_cost_and_paused_helpers():
    h = load_helpers()
    alerts = [
        {"agent": "beta", "rule": "fallback_verdict", "created_at": ago(30), "message": "WARN (50%, other): odd"},
        {"agent": "beta", "rule": "claude_verdict", "created_at": ago(5),
         "message": "KILL (80%, infinite_loop): Same prompt repeated 5× in a minute"},
        {"agent": "beta", "rule": "brain_cost", "created_at": ago(9),
         "message": "Sentinel spent $0.0021 to save $1.40 — claude call 800 in + 90 out [spent_usd=0.002100 saved_usd=1.4000]"},
    ]
    v = h["latest_verdict"](alerts)
    assert v["source"] == "claude" and v["text"].startswith("KILL (80%, infinite_loop)")
    assert h["brain_cost"](alerts) == (0.0021, 1.4)
    assert h["latest_verdict"]([]) is None and h["brain_cost"]([]) is None
    latest = pd.DataFrame({"status": ["running", "paused"]}, index=["alpha", "gamma"])
    assert h["paused_agents"](latest) == ["gamma"]


def test_header_strip_snippet_runs_against_a_live_sentinel(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    source = FakeSource(cfg, auto_rogue=None, rogue_type="loop")
    s = Sentinel(source, store, Brain(cfg), cfg)
    source.agents["beta"].go_rogue()
    store.insert_command(CommandRow("gamma", "PAUSE", "dashboard", "test"))
    end = time.time() + 12
    while time.time() < end and source.agents["beta"].alive:
        s.tick()
        for f in list(s.pending.values()):
            f.result(timeout=5)
        time.sleep(0.2)
    s.tick()
    ns = load_helpers()
    metrics = pd.DataFrame(store.recent_metrics(minutes=5))
    latest = metrics.sort_values("created_at").groupby("agent").tail(1).set_index("agent")
    ns.update(st=MagicMock(), pd=pd, store=store, latest=latest)
    st = ns["st"]
    st.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    exec(BLOCKS[1], ns)                                   # the header strip
    st.success.assert_called_once()                       # heartbeat is fresh → ONLINE
    assert "ONLINE" in st.success.call_args[0][0] and not st.error.called
    b1, b2, b3 = ns["b1"], ns["b2"], ns["b3"]
    assert "Brain verdict (fallback)" in b1.metric.call_args[0][0]
    assert b2.metric.call_args[0][1].startswith("spent $")
    assert b3.metric.call_args[0] == ("Paused", 1) and "gamma" in b3.caption.call_args[0][0]
    exec(BLOCKS[2], ns)                                   # the alerts table without heartbeats
    assert all(a["rule"] != "sentinel_heartbeat" for a in ns["shown"])


def test_offline_when_the_sentinel_stopped(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    store.insert_alert(AlertRow("sentinel", "info", "sentinel_heartbeat", "alive", created_at=ago(40)))
    ns = load_helpers()
    ns.update(st=MagicMock(), store=store, latest=pd.DataFrame({"status": []}))
    ns["st"].columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    exec(BLOCKS[1], ns)
    assert ns["st"].error.called and "OFFLINE" in ns["st"].error.call_args[0][0]


def test_taseen_checklist_only_uses_commands_that_exist():
    text = (DOC.parent / "taseen-laptop-checklist.md").read_text()
    root = DOC.parent.parent.parent
    for script in set(re.findall(r"python ((?:scripts|db)/\w+\.py)", text)):
        assert (root / script).exists(), script
    for flag, source in {"--docker": "scripts/demo.py", "--all": "scripts/demo.py", "--offline": "scripts/eval_brain.py",
                         "--yes": "db/reset.py"}.items():
        assert flag in (root / source).read_text(), (flag, source)
    env_example = (root / ".env.example").read_text()
    for key in ("BRAIN_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL", "SUPABASE_URL",
                "SUPABASE_KEY", "WEBHOOK_URL"):
        assert key in text and key in env_example, key
    for service in ("agent-alpha", "agent-beta", "agent-gamma"):
        assert service in (root / "docker-compose.yml").read_text()
    order = [text.index(f"## {n}.") for n in range(1, 9)]
    assert order == sorted(order)
