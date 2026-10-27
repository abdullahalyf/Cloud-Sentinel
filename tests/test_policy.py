"""Per-agent limits from container labels override the global settings."""
from dataclasses import replace

from sentinel.brain import Brain
from sentinel.collector import AgentState
from sentinel.engine import Sentinel
from sentinel.sources import AgentHandle, DockerSource
from shared.config import load_settings
from shared.contracts import AgentEvent
from shared.store import LocalStore
from tests.test_docker_source import FakeClient, FakeContainer

cfg = load_settings()
offline = replace(cfg, anthropic_api_key="")


def labelled(**labels):
    c = FakeContainer("c1", "alpha")
    c.labels.update({f"cloudsentinel.{k}": v for k, v in labels.items()})
    return DockerSource(cfg, client=FakeClient([c])).list_agents()[0]


def test_labels_are_read():
    h = labelled(soft_tokens_per_min="5000", hard_tokens_per_min="9000", token_budget="20000")
    assert (h.soft_tokens_per_min, h.hard_tokens_per_min, h.token_budget) == (5000, 9000, 20000)


def test_missing_or_bad_labels_fall_back_to_global():
    h = labelled(soft_tokens_per_min="lots", hard_tokens_per_min="-1", token_budget="abc")
    assert h.soft_tokens_per_min is None and h.hard_tokens_per_min is None
    assert h.token_budget == cfg.default_token_budget


def busy_state(h):
    st = AgentState(h.name, h.id, h.token_budget)
    for i in range(10):  # 10 × 600 tokens in the last 10s → 24,000 tokens/min
        st.add(AgentEvent(h.name, "llm_call", 1000.0 - 10 + i, tokens_in=600, prompt=f"task {i}"))
    return st


class Recording(Brain):
    def __init__(self):
        super().__init__(offline)
        self.seen_cfg = None

    def judge(self, snap, finding, recent, cfg=None):
        self.seen_cfg = cfg
        return super().judge(snap, finding, recent, cfg)


def run_once(tmp_path, h, brain=None):
    store = LocalStore(str(tmp_path / "t.db"))

    class OneAgent:
        def list_agents(self): return [h]
        def read_events(self, _): return []
        def read_memory(self, _): return (50.0, 10.0)
        def is_paused(self, _): return False
        def kill(self, _): return "killed"

    s = Sentinel(OneAgent(), store, brain or Brain(offline), cfg)
    s.states[h.id] = busy_state(h)
    s.tick(now=1000.0)
    for f in list(s.pending.values()):
        f.result(timeout=5)
    return s, store


def test_global_limits_leave_a_24k_agent_alone(tmp_path):
    h = AgentHandle("c1", "alpha", 150_000)
    s, store = run_once(tmp_path, h)
    assert not s.pending
    assert [a for a in store.recent_alerts() if a["rule"] != "sentinel_heartbeat"] == []   # only the heartbeat


def test_lower_soft_label_makes_it_suspicious_and_reaches_the_brain(tmp_path):
    brain = Recording()
    h = AgentHandle("c1", "alpha", 150_000, soft_tokens_per_min=10_000)
    s, store = run_once(tmp_path, h, brain)
    assert any(a["rule"] == "token_spike" for a in store.recent_alerts())
    assert brain.seen_cfg.soft_tokens_per_min == 10_000


def test_lower_hard_label_kills_without_the_brain(tmp_path):
    h = AgentHandle("c1", "alpha", 150_000, soft_tokens_per_min=10_000, hard_tokens_per_min=20_000)
    s, store = run_once(tmp_path, h)
    kills = [a for a in store.recent_actions() if a["action"] == "KILL"]
    assert kills and kills[0]["actor"] == "rules"


def test_budget_label_is_the_agents_budget(tmp_path):
    h = AgentHandle("c1", "alpha", 5_000)   # from cloudsentinel.token_budget
    s, store = run_once(tmp_path, h)
    assert any(a["rule"] == "budget_exceeded" for a in store.recent_alerts())
