"""
The contract test for B6's cascade.

A cascade is the case where **one runaway is not enough**: the agents keep each
other running, so stopping one of them only moves the problem.

The shape has to say three things:

- **the whole chain** — every agent in it, and its role (`source`, `member`,
  `target`);
- **the call graph** that made the chain — the edges, so a reader can see *why*
  the brain believes these agents are connected;
- **who was actually stopped** — `contained`, which is **not** always everyone in
  `agents`. An agent that was already dead, or one the brain does not own, is in
  the chain and not in `contained`. The two lists are separate on purpose: the
  chain is bigger than the part the brain got to.

And the two kinds are different facts: a **loop** is a cycle, a **contagion** is
one agent flooding the others.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.contracts import (CASCADE_ACTION, CASCADE_ACTOR, CASCADE_KINDS, CASCADE_RULES,
                              cascade_agent, cascade_edge, cascade_report, cascade_summary, cascade_view)
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    mock_api.seed()
    yield
    mock_api.seed()


# ── the shape ───────────────────────────────────────────────────────────────
def test_an_empty_cascade_view_reports_zeroes_not_an_error():
    """No chain seen yet is a fact, not a failure."""
    view = cascade_view()
    assert view["counts"] == {"cascades": 0, "agents": 0, "contained": 0}
    assert view["cascades"] == []


def test_the_view_has_every_field_the_api_serves():
    assert set(cascade_view()) == {"cascades", "counts", "as_of"}


def test_a_cascade_names_its_kind_its_agents_and_its_edges():
    report = cascade_report(kind="loop", cascade_id="loop-a-b",
                            agents=[cascade_agent("a", "source"), cascade_agent("b", "member")],
                            edges=[cascade_edge("a", "b", calls=14), cascade_edge("b", "a", calls=12)],
                            contained=["a", "b"], detected_at=1000.0)
    assert report["kind"] == "loop"
    assert report["cascade_id"] == "loop-a-b"
    assert [a["agent_id"] for a in report["agents"]] == ["a", "b"]
    assert report["edges"][0] == {"source": "a", "target": "b", "calls": 14}
    assert report["contained"] == ["a", "b"]
    assert report["detected_at"] == 1000.0


def test_an_agent_names_its_role_in_the_chain():
    assert cascade_agent("alpha", "source", "it started it") == {
        "agent_id": "alpha", "role": "source", "reason": "it started it"}


def test_the_counts_match_the_lists():
    report = cascade_report(agents=[cascade_agent("a"), cascade_agent("b")],
                            edges=[cascade_edge("a", "b")], contained=["a"])
    assert report["counts"] == {"agents": 2, "edges": 1, "contained": 1}


def test_the_whole_chain_and_the_stopped_part_are_two_different_facts():
    """
    An agent can be in the chain and not stopped — it was already dead, or the
    brain does not own it. Collapsing the two lists would make the brain look
    like it contained more than it did.
    """
    report = cascade_report(agents=[cascade_agent("a"), cascade_agent("b")], contained=["a"])
    assert len(report["agents"]) == 2
    assert report["contained"] == ["a"]
    assert report["counts"]["agents"] == 2
    assert report["counts"]["contained"] == 1


def test_the_money_is_rounded_to_four_places():
    report = cascade_report(usd_saved=1.23456789)
    assert report["usd_saved"] == 1.2346


# ── the two kinds ───────────────────────────────────────────────────────────
def test_a_loop_is_a_cycle_and_a_contagion_is_a_flood():
    assert set(CASCADE_KINDS) == {"loop", "contagion"}


def test_a_cascade_is_paused_not_killed():
    """The chain is still there — an operator may want to look at it."""
    assert CASCADE_ACTION == "PAUSE"


def test_the_cascade_has_its_own_actor_and_its_own_rules():
    """The audit log must say the cascade did this, not a stray rule."""
    assert CASCADE_ACTOR == "brain:cascade"
    assert set(CASCADE_RULES) == {"cascade_loop", "cascade_contagion"}


# ── the summary ─────────────────────────────────────────────────────────────
def test_the_summary_says_how_many_agents_and_how_many_were_contained():
    report = cascade_report(kind="loop", agents=[cascade_agent("a"), cascade_agent("b")],
                            contained=["a"])
    line = cascade_summary(report)
    assert "loop" in line
    assert "2 agents" in line
    assert "a, b" in line
    assert "1 contained" in line


def test_the_summary_of_an_empty_cascade_is_readable():
    line = cascade_summary(cascade_report())
    assert "0 agents" in line and "0 contained" in line


# ── the mock endpoint ───────────────────────────────────────────────────────
def test_the_mock_serves_the_cascades():
    view = TestClient(mock_app).get("/v1/cascades").json()
    assert view["counts"]["cascades"] > 0
    assert view["cascades"]


def test_the_mock_shows_both_kinds():
    """The dashboard has to be able to show a loop and a contagion."""
    view = TestClient(mock_app).get("/v1/cascades").json()
    kinds = {c["kind"] for c in view["cascades"]}
    assert "loop" in kinds
    assert "contagion" in kinds


def test_the_mock_cascades_have_the_same_fields_as_the_contract():
    view = TestClient(mock_app).get("/v1/cascades").json()
    assert set(view) == set(cascade_view())
    assert set(view["cascades"][0]) == set(cascade_report())
    assert set(view["cascades"][0]["agents"][0]) == set(cascade_agent("a"))
    assert set(view["cascades"][0]["edges"][0]) == set(cascade_edge("a", "b"))


def test_the_mock_cascade_names_the_agents_and_the_edges():
    """A chain with no edges and no agents is not a chain."""
    view = TestClient(mock_app).get("/v1/cascades").json()
    for cascade in view["cascades"]:
        assert cascade["agents"]
        assert cascade["edges"]
        assert cascade["reason"]
