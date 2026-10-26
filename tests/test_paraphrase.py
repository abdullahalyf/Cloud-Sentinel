"""Paraphrase detection: the same task in new words is a loop; different work is not."""
import importlib.util
import random
import sys
from pathlib import Path

import pytest

from sentinel.brain import fallback_verdict
from sentinel.collector import AgentState, biggest_cluster, signature
from sentinel.detector import Level, evaluate
from shared.config import load_settings
from shared.contracts import AgentEvent

cfg = load_settings()
ROOT = Path(__file__).resolve().parent.parent


def agent_module():
    spec = importlib.util.spec_from_file_location("real_agent", ROOT / "agents" / "agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def state_with(prompts, gap=0.7, tokens=400):
    st = AgentState("x", "c", 10**9)
    for i, p in enumerate(prompts):
        st.add(AgentEvent("x", "llm_call", 1000 + i * gap, tokens_in=tokens, tokens_out=0, model="m", prompt=p))
    return st, 1000 + len(prompts) * gap


def test_signature_normalizes_punctuation_stopwords_and_plurals():
    assert signature("Fetch order #4471 status!") == signature("fetch ORDER 4471, status")
    assert signature("Query the orders API for 4471")[1] == {"query", "order", "api"}


def cluster(*prompts):
    return biggest_cluster([signature(p) for p in prompts])


def test_reworded_same_job_counts_but_different_ids_do_not():
    reworded = ["Fetch order 4471 status", "Get the status of order #4471", "Retrieve order 4471 status info",
                "Look up status of order 4471", "Check order #4471 status"]
    assert cluster(*reworded) == 5
    assert cluster(*[f"Classify invoice line item #{5000 + i}" for i in range(8)]) == 0
    assert cluster(*[f"Summarize tickets (job {1111 * i})" for i in range(1, 8)]) == 0
    assert cluster("Fetch order 4471 status", "Draft email about invoice 4471") == 0


def test_multi_step_work_on_one_id_is_not_a_paraphrase_loop():
    steps = ["Fetch order 40001", "Validate address on order 40001", "Charge payment for order 40001",
             "Reserve stock for order 40001", "Print shipping label for order 40001",
             "Send confirmation email for order 40001", "Update CRM record for order 40001",
             "Notify warehouse about order 40001", "Close ticket for order 40001", "Archive order 40001"]
    assert cluster(*steps) == 0   # the shared id and the word "order" do not make ten different steps a loop
    st, now = state_with(steps, gap=0.5)
    snap = st.snapshot(now)
    assert snap.similar_repeats == 0
    assert "paraphrase_loop" not in evaluate(snap, cfg).rules


def test_real_paraphrase_loop_is_flagged_within_ten_seconds():
    agent = agent_module()
    random.seed(1)
    st, now = state_with([agent.make_paraphrase() for _ in range(14)], gap=0.7)   # ~10s of the real agent's output
    snap = st.snapshot(now)
    assert snap.loop_repeats < cfg.loop_repeat_threshold   # exact-match rule is blind to it
    assert snap.similar_repeats >= cfg.paraphrase_repeat_threshold
    finding = evaluate(snap, cfg)
    assert finding.level == Level.SUSPICIOUS and "paraphrase_loop" in finding.rules
    assert fallback_verdict(snap, finding, cfg).action == "KILL"   # reworded + spending


def test_reworded_alone_only_warns():
    # same job reworded, but cheap and slow: one signal is not enough to kill
    st, now = state_with([f"Fetch order 4471 status, attempt {w}" for w in "abcdefghij"], gap=1.4, tokens=30)
    snap = st.snapshot(now)
    finding = evaluate(snap, cfg)
    assert "paraphrase_loop" in finding.rules
    assert fallback_verdict(snap, finding, cfg).action == "WARN"


@pytest.mark.parametrize("seed", range(5))
def test_healthy_agent_is_never_flagged(seed):
    agent = agent_module()
    random.seed(seed)
    prompts = [f"{random.choice(agent.TASKS)} (job {random.randint(1000, 9999)})" for _ in range(30)]
    st, now = state_with(prompts, gap=2.0, tokens=400)
    assert st.snapshot(now).similar_repeats <= 1


def test_busy_burst_of_different_invoices_is_not_a_paraphrase_loop():
    st, now = state_with([f"Classify invoice line item #{5000 + 7 * i} (office) into a category" for i in range(30)],
                         gap=0.45)
    assert st.snapshot(now).similar_repeats == 0


def test_clustering_is_fast_enough_for_a_tick():
    import time

    words = ["alpha", "bravo", "delta", "echo", "gamma"]
    sigs = [signature(f"Fetch order 4471 status {random.choice(words)} {random.choice(words)}") for _ in range(150)]
    started = time.time()
    assert biggest_cluster(sigs) == 150
    assert time.time() - started < 0.2


def test_old_prompts_leave_the_window():
    st, now = state_with(["Fetch order 4471 status", "Get the status of order #4471"] * 6, gap=0.5)
    assert st.snapshot(now).similar_repeats == 12
    assert st.snapshot(now + 20).similar_repeats == 0   # older than 15s


def test_prompts_without_ids_are_never_paraphrases():
    names = ["Alice", "Bob", "Carla", "Dev", "Emma", "Farid", "Grace", "Hana", "Ivan", "Jin"]
    st, now = state_with([f"Draft a polite reply to customer {n} about the delayed shipment" for n in names] * 2,
                         gap=0.5)
    assert st.snapshot(now).similar_repeats == 0


def test_a_shared_year_is_not_an_id():
    assert signature("Summarize 2026 tickets of Alice")[0] == frozenset()
    st, now = state_with([f"Summarize the 2026 support tickets of customer {n}"
                          for n in ["Alice", "Bob", "Carla", "Dev", "Emma", "Farid", "Grace", "Hana", "Ivan", "Jin"]],
                         gap=0.5)
    assert st.snapshot(now).similar_repeats == 0


def test_small_numbers_are_counts_not_ids():
    assert signature("Summarize top 10 tickets for Alice")[0] == frozenset()
    assert signature("Fetch order #4471 and 2026 report")[0] == frozenset({"4471"})


def test_wording_that_drifts_does_not_chain_into_one_group():
    # each prompt shares only one word with the next and one with the previous: never most of its own words
    chain = ["alpha bravo charlie delta 4471", "delta echo foxtrot golf 4471", "golf hotel india juliet 4471",
             "juliet kilo lima mike 4471", "mike november oscar papa 4471", "papa quebec romeo sierra 4471"]
    assert cluster(*chain) == 0
