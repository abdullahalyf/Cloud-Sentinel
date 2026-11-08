"""
The contract test for B7's tamper-evident audit log.

An audit log that can be edited after the fact is not an audit log. The whole
point of this one is the **chain**: every entry carries the hash of the entry
before it, so an edit in the middle breaks every link after it — and a deletion
breaks it the same way.

So the shape has to say three things:

- **the chain** — the entries, in the order they happened;
- **the head** — the hash of the last entry, the one-line proof;
- **whether it still verifies** — and if it does not, **which entry broke it**.

And the hash rule has to be in the contract, not in the brain: the mock and the
real API must compute the same hash, or a client that verifies one would
reject the other.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.contracts import (AUDIT_GENESIS, AUDIT_KINDS, audit_entry, audit_hash, audit_verify_result,
                              audit_view)
from shared.mocks import mock_api
from shared.mocks.mock_api import app as mock_app


@pytest.fixture(autouse=True)
def fresh_mock():
    mock_api.seed()
    yield
    mock_api.seed()


# ── the shape ───────────────────────────────────────────────────────────────
def test_an_empty_audit_view_reports_zeroes_not_an_error():
    """Nothing has happened yet — that is a fact, not a failure."""
    view = audit_view()
    assert view["counts"] == {"entries": 0, "decisions": 0, "human": 0, "policy": 0}
    assert view["entries"] == []
    assert view["valid"] is True


def test_the_view_has_every_field_the_api_serves():
    assert set(audit_view()) == {"entries", "head_hash", "valid", "broken_at", "enabled", "counts", "as_of"}


def test_an_entry_names_what_happened_and_where_it_links():
    entry = audit_entry(seq=3, agent_id="beta", kind="decision", actor="rules",
                        action="PAUSE", reason="semantic loop on order 4471",
                        prev_hash="abc123", hash="def456")
    assert entry["seq"] == 3
    assert entry["agent_id"] == "beta"
    assert entry["kind"] == "decision"
    assert entry["actor"] == "rules"
    assert entry["action"] == "PAUSE"
    assert entry["reason"] == "semantic loop on order 4471"
    assert entry["prev_hash"] == "abc123"
    assert entry["hash"] == "def456"


def test_the_counts_match_the_entries():
    view = audit_view(entries=[audit_entry(kind="decision"), audit_entry(kind="human"),
                               audit_entry(kind="human")])
    assert view["counts"] == {"entries": 3, "decisions": 1, "human": 2, "policy": 0}


def test_the_three_kinds_are_the_three_kinds_of_thing_that_happens():
    """A brain decision, a human action and a policy action are different facts."""
    assert set(AUDIT_KINDS) == {"decision", "human", "policy"}


def test_a_broken_chain_says_which_entry_broke_it():
    """'Your log is broken' without a position is not an answer an operator can act on."""
    view = audit_view(entries=[audit_entry(seq=1)], valid=False, broken_at=1)
    assert view["valid"] is False
    assert view["broken_at"] == 1


def test_the_verify_result_says_the_same_thing():
    result = audit_verify_result(ok=False, entries=9, head_hash="abc", broken_at=4,
                                 reason="the hash of entry 4 does not match")
    assert result["ok"] is False
    assert result["entries"] == 9
    assert result["broken_at"] == 4
    assert "entry 4" in result["reason"]


# ── the hash rule ───────────────────────────────────────────────────────────
def test_the_hash_is_the_previous_hash_plus_this_entry_s_content():
    """The chain rule, spelled out: change either the link or the content, the hash moves."""
    entry = audit_entry(seq=1, agent_id="beta", kind="decision", actor="rules",
                        action="PAUSE", reason="why", prev_hash=AUDIT_GENESIS)
    first = audit_hash(entry)
    assert first and isinstance(first, str)

    # the same entry always gives the same hash
    assert audit_hash(entry) == first

    # a different link gives a different hash
    moved = audit_entry(seq=1, agent_id="beta", kind="decision", actor="rules",
                        action="PAUSE", reason="why", prev_hash="something-else")
    assert audit_hash(moved) != first

    # different content gives a different hash
    changed = audit_entry(seq=1, agent_id="beta", kind="decision", actor="rules",
                          action="PAUSE", reason="a different reason", prev_hash=AUDIT_GENESIS)
    assert audit_hash(changed) != first


def test_the_clock_is_not_part_of_the_hash():
    """
    Two sides that wrote the same decision at slightly different times must still
    agree on the chain. A clock is not a fact about the decision.
    """
    early = audit_entry(seq=1, agent_id="beta", kind="decision", actor="rules",
                        action="PAUSE", reason="why", created_at=1000.0)
    late = audit_entry(seq=1, agent_id="beta", kind="decision", actor="rules",
                       action="PAUSE", reason="why", created_at=2000.0)
    assert audit_hash(early) == audit_hash(late)


def test_the_hash_is_not_empty_and_not_the_genesis():
    entry = audit_entry(seq=1, agent_id="beta", kind="decision", actor="rules",
                        action="PAUSE", reason="why")
    assert audit_hash(entry) != AUDIT_GENESIS
    assert len(audit_hash(entry)) == 32


# ── the mock endpoint ───────────────────────────────────────────────────────
def test_the_mock_serves_the_audit_chain():
    view = TestClient(mock_app).get("/v1/audit").json()
    assert view["entries"]
    assert view["head_hash"]
    assert view["valid"] is True


def test_the_mock_chain_has_the_same_fields_as_the_contract():
    view = TestClient(mock_app).get("/v1/audit").json()
    assert set(view) == set(audit_view())
    assert set(view["entries"][0]) == set(audit_entry())


def test_the_mock_chain_holds_together():
    """
    The mock's hashes are **real** — a client written against the mock must be
    able to verify the mock's chain the same way it verifies the real one. A mock
    with fake hashes would teach the client to skip the check.
    """
    entries = TestClient(mock_app).get("/v1/audit").json()["entries"]
    prev = AUDIT_GENESIS
    for seq, entry in enumerate(entries, start=1):
        assert entry["seq"] == seq
        assert entry["prev_hash"] == prev
        assert entry["hash"] == audit_hash(entry)
        prev = entry["hash"]


def test_the_mock_shows_all_three_kinds():
    """The dashboard has to be able to show a decision, a human action and a policy action."""
    view = TestClient(mock_app).get("/v1/audit").json()
    kinds = {e["kind"] for e in view["entries"]}
    assert kinds == set(AUDIT_KINDS)
