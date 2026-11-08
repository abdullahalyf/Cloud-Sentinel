"""
The brain-side tests for B6's cascade.

A cascade is the case where **one runaway is not enough**: the agents keep each
other running, so stopping one of them only moves the problem.

Four things must hold, and the last one is the one people forget:

- the chain is found **from the call graph**, not from "these agents were busy
  at the same time" — being nearby is not being connected;
- a **cycle is one cascade**, not two separate agents;
- the containment stops **the whole chain in the same tick**;
- a **healthy agent that merely appears in the same window is not swept up**.

And with the flag off the brain does the old thing: every agent on its own.
"""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from brain import cascade as brain_cascade
from brain.api import create_app
from shared.config import Settings
from shared.contracts import CASCADE_ACTOR, CASCADE_RULES, SpanRow
from shared.store import LocalStore


# ── the traces ──────────────────────────────────────────────────────────────
def _span(agent_id: str, ts: float, span_id: str, parent: str = "", prompt: str = "") -> SpanRow:
    """One span. `parent` is the span_id of the span that caused this one."""
    return SpanRow(agent_id, "chat", f"chat {ts}", trace_id=f"t-{agent_id}",
                   span_id=span_id, parent_span_id=parent,
                   input_tokens=100, output_tokens=25, cost_usd=0.01,
                   prompt_preview=prompt or f"{agent_id} work", prompt_hash=f"h-{span_id}",
                   start_ts=ts)


def _chain(store, *, a_calls_b: int = 6, b_calls_a: int = 6, base: Optional[float] = None) -> None:
    """
    A → B → A: the two agents call each other back and forth.

    Each span's `parent_span_id` is the span of the agent that **called** it,
    so the graph reads "the caller called the callee". The turns alternate:
    alpha calls beta, beta calls alpha, alpha calls beta again.
    """
    t = (time.time() - 120.0) if base is None else base
    rows = []
    parent = ""
    turn = 0
    for i in range(a_calls_b + b_calls_a):
        caller, callee = ("alpha", "beta") if turn % 2 == 0 else ("beta", "alpha")
        span_id = f"s{i}"
        rows.append(_span(callee, t + i * 0.5, span_id, parent=parent,
                          prompt=f"{caller} asks {callee}"))
        parent = span_id
        turn += 1
    store.insert_spans(rows)


def _flood(store, *, source: str = "delta", target: str = "gamma",
           calls: int = 25, base: Optional[float] = None) -> None:
    """One agent flooding another: `calls` calls into `target` in the window."""
    t = (time.time() - 120.0) if base is None else base
    rows = []
    for i in range(calls):
        parent = f"src{i}"
        rows.append(_span(source, t + i * 0.1, parent, prompt="the flood"))
        rows.append(_span(target, t + i * 0.1 + 0.01, f"dst{i}", parent=parent,
                          prompt="the victim"))
    store.insert_spans(rows)


def _healthy_neighbour(store, base: Optional[float] = None) -> None:
    """An agent that is busy in the same window but calls nobody and is called by nobody."""
    t = (time.time() - 120.0) if base is None else base
    store.insert_spans([_span("epsilon", t + i, f"e{i}", prompt="epsilon works alone")
                        for i in range(10)])


@pytest.fixture
def store():
    return LocalStore(":memory:")


@pytest.fixture
def on(cfg):
    """The brain with the cascade on."""
    return replace(cfg, cascade_enabled=True, cascade_window_minutes=60.0,
                   cascade_fanout_calls=20)


# ── the call graph ──────────────────────────────────────────────────────────
def test_the_graph_sees_who_called_who(store):
    _chain(store)
    graph = brain_cascade.build_call_graph(store.recent_spans(minutes=60))
    assert "beta" in graph.callees("alpha")
    assert "alpha" in graph.callees("beta")
    assert graph.call_count("alpha", "beta") >= 1


def test_an_agent_calling_itself_is_not_a_call_between_two_agents(store):
    """An agent's own inner steps are not a chain."""
    t = time.time() - 120.0
    store.insert_spans([_span("alpha", t + i, f"a{i}", parent=f"a{i - 1}") for i in range(1, 6)])
    graph = brain_cascade.build_call_graph(store.recent_spans(minutes=60))
    assert graph.is_empty()


def test_a_span_with_no_parent_is_not_an_edge(store):
    """The brain will not guess a call it cannot point at."""
    t = time.time() - 120.0
    store.insert_spans([_span("alpha", t + i, f"a{i}") for i in range(5)])
    graph = brain_cascade.build_call_graph(store.recent_spans(minutes=60))
    assert graph.is_empty()


# ── a cycle is one cascade ──────────────────────────────────────────────────
def test_an_a_to_b_to_a_chain_is_detected_as_one_cascade(store, on):
    _chain(store)
    cascades = brain_cascade.detect_cascades(store.recent_spans(minutes=60), on)
    loops = [c for c in cascades if c["kind"] == "loop"]
    assert len(loops) == 1
    assert {a["agent_id"] for a in loops[0]["agents"]} == {"alpha", "beta"}


def test_two_separate_incidents_are_not_one_cascade(store, on):
    """Two agents that never call each other are two agents, not a chain."""
    t = time.time() - 120.0
    store.insert_spans([_span("alpha", t + i, f"a{i}", prompt="a works") for i in range(5)])
    store.insert_spans([_span("beta", t + i, f"b{i}", prompt="b works") for i in range(5)])
    cascades = brain_cascade.detect_cascades(store.recent_spans(minutes=60), on)
    assert cascades == []


def test_a_healthy_agent_in_the_same_window_is_not_swept_up(store, on):
    """
    Being nearby is not being connected.

    epsilon is busy in the same window as the chain, but it calls nobody and
    nobody calls it — so it is not in the chain.
    """
    _chain(store)
    _healthy_neighbour(store)
    cascades = brain_cascade.detect_cascades(store.recent_spans(minutes=60), on)
    for cascade in cascades:
        assert "epsilon" not in {a["agent_id"] for a in cascade["agents"]}


# ── a contagion ─────────────────────────────────────────────────────────────
def test_one_agent_flooding_another_is_a_contagion(store, on):
    _flood(store, calls=25)
    cascades = brain_cascade.detect_cascades(store.recent_spans(minutes=60), on)
    kinds = {c["kind"] for c in cascades}
    assert "contagion" in kinds
    contagion = [c for c in cascades if c["kind"] == "contagion"][0]
    assert {a["agent_id"] for a in contagion["agents"]} == {"delta", "gamma"}


def test_a_small_fanout_is_not_a_contagion(store, on):
    """Three calls is normal traffic; twenty-five is a flood."""
    _flood(store, calls=3)
    cascades = brain_cascade.detect_cascades(store.recent_spans(minutes=60), on)
    assert [c for c in cascades if c["kind"] == "contagion"] == []


def test_the_contagion_names_who_flooded_and_who_was_flooded(store, on):
    _flood(store, calls=25)
    cascade = [c for c in brain_cascade.detect_cascades(store.recent_spans(minutes=60), on)
               if c["kind"] == "contagion"][0]
    roles = {a["agent_id"]: a["role"] for a in cascade["agents"]}
    assert roles["delta"] == "source"
    assert roles["gamma"] == "target"


# ── the containment: the whole chain, in one tick ───────────────────────────
def test_the_containment_stops_every_agent_in_the_chain_together(store, on, cfg):
    """Pausing one link of a cycle only moves the problem."""
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy

    policy = Policy.load("brain/policies.yaml")
    engine = Engine(store, _FakeExecutor(), Judge(cfg), policy, on)
    _chain(store)
    engine.tick(time.time())

    states = {agent: engine.breakers[agent].state for agent in ("alpha", "beta")
              if agent in engine.breakers}
    assert states == {"alpha": "paused", "beta": "paused"}


def test_the_containment_is_written_to_the_store_so_it_can_be_read_back(store, on, cfg):
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy

    policy = Policy.load("brain/policies.yaml")
    engine = Engine(store, _FakeExecutor(), Judge(cfg), policy, on)
    _chain(store)
    engine.tick(time.time())

    alerts = store.recent_alerts(limit=50)
    rules = {str(r.get("rule") or "") for r in alerts}
    assert rules & set(CASCADE_RULES)
    actions = store.recent_actions(limit=50)
    actors = {str(r.get("actor") or "") for r in actions}
    assert CASCADE_ACTOR in actors


def test_the_cascade_is_read_back_from_the_store(store, on, cfg):
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy

    policy = Policy.load("brain/policies.yaml")
    engine = Engine(store, _FakeExecutor(), Judge(cfg), policy, on)
    _chain(store)
    engine.tick(time.time())

    view = brain_cascade.cascades_from_store(store)
    assert view["counts"]["cascades"] >= 1
    contained = view["cascades"][0]["contained"]
    assert set(contained) == {"alpha", "beta"}


def test_the_whole_chain_and_the_stopped_part_are_two_different_facts(store, on, cfg):
    """
    An agent that is already dead is in the chain and not in `contained` — a
    report that collapsed the two would make the brain look like it stopped
    more than it did.
    """
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy

    policy = Policy.load("brain/policies.yaml")
    engine = Engine(store, _FakeExecutor(), Judge(cfg), policy, on)
    _chain(store)
    # beta is dead before the tick: it is in the chain, but there is nothing to pause.
    engine.breakers["beta"] = engine._breaker("beta")
    engine.breakers["beta"].state = "killed"
    engine.tick(time.time())

    cascades = brain_cascade.detect_cascades(store.recent_spans(minutes=60), on)
    chain = [c for c in cascades if c["kind"] == "loop"]
    assert chain
    # the chain still names both agents…
    assert {a["agent_id"] for a in chain[0]["agents"]} == {"alpha", "beta"}
    # …and only alpha could be stopped.
    view = brain_cascade.cascades_from_store(store)
    assert "beta" not in view["cascades"][0]["contained"]
    assert "alpha" in view["cascades"][0]["contained"]


def test_a_chain_is_not_contained_again_on_the_next_tick(store, on, cfg):
    """The same chain every tick would fill the audit log with the same pause."""
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy

    policy = Policy.load("brain/policies.yaml")
    engine = Engine(store, _FakeExecutor(), Judge(cfg), policy, on)
    _chain(store)
    engine.tick(time.time())
    first = len(store.recent_actions(limit=200))
    engine.tick(time.time() + 1)
    second = len(store.recent_actions(limit=200))
    assert second == first


# ── the flag ────────────────────────────────────────────────────────────────
def test_the_flag_off_means_the_old_behaviour_each_agent_on_its_own(store, cfg):
    """With the flag off the brain never looks for a chain."""
    from brain.engine import Engine
    from brain.judge import Judge
    from brain.policy import Policy

    assert cfg.cascade_enabled is False
    policy = Policy.load("brain/policies.yaml")
    engine = Engine(store, _FakeExecutor(), Judge(cfg), policy, cfg)
    _chain(store)
    engine.tick(time.time())

    actions = store.recent_actions(limit=50)
    assert not [r for r in actions if str(r.get("actor") or "") == CASCADE_ACTOR]


# ── the API ─────────────────────────────────────────────────────────────────
def _client(store, cfg, on):
    from brain.policy import Policy
    return TestClient(create_app(store, Policy.load("brain/policies.yaml"), on, "fake", "fallback"))


def test_the_api_is_off_by_default(store, cfg):
    assert cfg.cascade_enabled is False
    assert _client(store, cfg, cfg).get("/v1/cascades").status_code == 404


def test_the_api_serves_the_cascades_when_the_flag_is_on(store, on):
    _chain(store)
    view = _client(store, on, on).get("/v1/cascades").json()
    assert set(view) == {"cascades", "counts", "as_of"}


def test_the_api_matches_the_mock(store, on):
    """The mock and the real API must say the same thing."""
    from shared.mocks import mock_api
    from shared.mocks.mock_api import app as mock_app

    _chain(store)
    real = _client(store, on, on).get("/v1/cascades").json()
    mock = TestClient(mock_app).get("/v1/cascades").json()
    assert set(real) == set(mock)
    assert set(real["counts"]) == set(mock["counts"])


class _FakeExecutor:
    """The smallest executor the engine needs: it pauses, and it lists nobody."""

    def list_agents(self):
        return []

    def pause(self, agent_id: str):
        from shared.contracts import ExecutorResult
        return ExecutorResult(True, f"{agent_id} paused")

    def kill(self, agent_id: str):
        from shared.contracts import ExecutorResult
        return ExecutorResult(True, f"{agent_id} killed")

    def resume(self, agent_id: str):
        from shared.contracts import ExecutorResult
        return ExecutorResult(True, f"{agent_id} resumed")

    def restart(self, agent_id: str):
        from shared.contracts import ExecutorResult
        return ExecutorResult(True, f"{agent_id} restarted")
