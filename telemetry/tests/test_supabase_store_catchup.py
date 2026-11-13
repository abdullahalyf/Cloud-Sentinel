"""Tests for what main added after F3 (A3 heal proposals, A4 agent baseline, insert_verdict returning its id).

Same idea as test_supabase_store_reads.py: no network, a fake Supabase client, and the SAME story run on
LocalStore and SupabaseStore, which must give the same answers. The fake client comes from that file.
"""
import pytest

from shared.store import LocalStore
from test_supabase_store_reads import Row, iso, make_supabase


@pytest.fixture(params=["local", "supabase"])
def store(request, monkeypatch):
    if request.param == "local":
        return LocalStore(":memory:")
    return make_supabase(monkeypatch)[0]


def agent(baseline, state="healthy"):
    return Row(agent_id="alpha", display_name="Alpha", runtime="fake", runtime_id="c-alpha", state=state,
               budget_usd=1.0, spend_usd=0.1, total_tokens=100, last_seen_ts=1.0, baseline=baseline,
               updated_at=iso(0))


def proposal(agent_id, n, status="pending"):
    return Row(agent_id=agent_id, kind="memory_patch", patch='{"order_4471": "skip it"}', confidence=0.9,
               status=status, verdict_id=n, base_version=1, reason=f"reason {n}", decided_by="",
               decided_at="", created_at=iso(n))


def verdict(n):
    return Row(agent_id="alpha", source="fallback", action="PAUSE", confidence=0.7, pattern="other",
               reason=f"reason {n}", suggested_fix="", latency_ms=5.0, created_at=iso(n))


def heal_story(s):
    ids = [s.insert_heal_proposal(proposal("alpha", 1)), s.insert_heal_proposal(proposal("beta", 2)),
           s.insert_heal_proposal(proposal("alpha", 3))]
    s.decide_heal_proposal(ids[1], "applied", "brain", "sure about it")
    s.decide_heal_proposal(ids[2], "rejected", "human")

    def clean(rows):  # decided_at is the clock of the moment of the decision
        return [{k: v for k, v in r.items() if k != "decided_at"} for r in rows]

    return {
        "ids": ids,
        "one": clean([s.get_heal_proposal(ids[0])]),
        "decided": clean([s.get_heal_proposal(ids[1]), s.get_heal_proposal(ids[2])]),
        "none": s.get_heal_proposal(999),
        "all": clean(s.list_heal_proposals()),
        "pending": clean(s.list_heal_proposals(status="pending")),
        "applied": clean(s.list_heal_proposals(status="applied")),
        "alpha": clean(s.list_heal_proposals(agent_id="alpha")),
        "alpha rejected": clean(s.list_heal_proposals(status="rejected", agent_id="alpha")),
        "limit 1": clean(s.list_heal_proposals(limit=1)),
    }


def test_heal_proposals_give_the_same_answers_on_both_stores(monkeypatch):
    local = heal_story(LocalStore(":memory:"))
    remote = heal_story(make_supabase(monkeypatch)[0])
    for key in local:
        assert remote[key] == local[key], key


def test_the_heal_story_really_checks_something():
    answers = heal_story(LocalStore(":memory:"))
    assert answers["ids"] == [1, 2, 3] and answers["none"] is None
    assert [p["id"] for p in answers["all"]] == [3, 2, 1]                  # newest first
    assert [p["id"] for p in answers["pending"]] == [1]
    assert answers["applied"][0]["decided_by"] == "brain" and answers["applied"][0]["reason"] == "sure about it"
    assert [p["id"] for p in answers["alpha"]] == [3, 1] and len(answers["limit 1"]) == 1
    assert answers["one"][0]["patch"] == {"order_4471": "skip it"}          # JSON text decoded


def test_insert_verdict_returns_its_id(store):
    assert store.insert_verdict(verdict(1)) == 1
    assert store.insert_verdict(verdict(2)) == 2


def test_a_plain_agent_write_does_not_wipe_the_learned_baseline(store):
    store.upsert_agent(agent('{"tokens_per_min": 500}'))
    assert store.get_agent("alpha")["baseline"] == {"tokens_per_min": 500}
    store.upsert_agent(agent("{}", state="paused"))              # the brain writes the agent row every tick
    got = store.get_agent("alpha")
    assert got["state"] == "paused" and got["baseline"] == {"tokens_per_min": 500}
    store.upsert_agent(agent('{"tokens_per_min": 900}'))         # a NEW baseline does replace the old one
    assert store.get_agent("alpha")["baseline"] == {"tokens_per_min": 900}


def test_a_new_agent_without_a_baseline_gets_an_empty_one(store):
    store.upsert_agent(agent("{}"))
    assert store.get_agent("alpha")["baseline"] == {}


def test_supabase_gets_the_baseline_as_a_json_object(monkeypatch):
    s, fake = make_supabase(monkeypatch)
    s.upsert_agent(agent('{"tokens_per_min": 500}'))
    assert fake.tables["agents"][0]["baseline"] == {"tokens_per_min": 500}   # the column is json, not text


def test_reset_also_empties_the_heal_proposals(store):
    heal_story(store)
    store.reset()
    assert store.list_heal_proposals() == []