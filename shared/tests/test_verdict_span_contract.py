"""
The brain's verdict on the agent's trace (A15) — the contract side.

The agent's behaviour lives on an OpenTelemetry trace; the brain's decision about it
lived only in CloudSentinel's own tables. A15 puts the verdict on the trace, so the
person looking at the agent in Phoenix sees *why* it was stopped next to *what it did*.

What is pinned here is the **contract** — the names and the shape, so the brain and
any reader of the trace agree on what a verdict looks like:

  1. **The attribute names** — every one of them `cloudsentinel.*`, so a reader can
     tell our attributes from the standard ones.
  2. **The operation** — a verdict is a span like any other, so the collector stores
     it like one.
  3. **The setting that turns it on** — off by default, because a brain that was not
     asked to put its verdicts on the trace must not start doing it.

The behaviour of the emitter itself is on the brain side (`brain/tests/test_verdict_span.py`),
because that is where the emitter lives.
"""
from __future__ import annotations

from shared.contracts import OPERATIONS, Attr


# ── the shape ────────────────────────────────────────────────────────────────
def test_the_verdict_attributes_exist():
    """Every attribute the brain writes has a name in the contract.

    A name written twice — once in the contract and once in the brain — is a name
    that will drift. The contract is where it is written down once.
    """
    for name in ("CS_VERDICT_ACTION", "CS_VERDICT_SOURCE", "CS_VERDICT_CONFIDENCE",
                 "CS_VERDICT_REASON", "CS_LOOP_SCORE", "CS_EXACT_REPEATS"):
        assert hasattr(Attr, name), f"the contract has no {name}"
        assert getattr(Attr, name).startswith("cloudsentinel.")


def test_the_verdict_attributes_are_namespaced():
    """`cloudsentinel.*` — so a reader can tell our attributes from the standard ones."""
    assert Attr.CS_VERDICT_ACTION == "cloudsentinel.verdict.action"
    assert Attr.CS_VERDICT_SOURCE == "cloudsentinel.verdict.source"
    assert Attr.CS_VERDICT_CONFIDENCE == "cloudsentinel.verdict.confidence"
    assert Attr.CS_VERDICT_REASON == "cloudsentinel.verdict.reason"
    assert Attr.CS_LOOP_SCORE == "cloudsentinel.loop.score"
    assert Attr.CS_EXACT_REPEATS == "cloudsentinel.loop.exact_repeats"


def test_the_verdict_is_an_operation():
    """A verdict is a span like any other, so the collector stores it like one."""
    assert "cs_verdict" in OPERATIONS


def test_the_existing_operations_are_untouched():
    """The contract is additive — an agent that emits a chat span still works."""
    for op in ("invoke_agent", "chat", "execute_tool", "graph_node"):
        assert op in OPERATIONS


def test_the_verdict_operation_is_not_a_behaviour_operation():
    """`cs_verdict` is the brain *talking about* the agent, not the agent doing
    something. If it were ever confused with `chat` or `execute_tool`, the brain
    would read its own verdict back as behaviour and start judging its judgement."""
    assert "cs_verdict" not in ("invoke_agent", "chat", "execute_tool", "graph_node")


# ── the setting that turns it on ────────────────────────────────────────────
def test_the_verdict_export_is_off_by_default():
    """Off by default. A brain that was not asked to put its verdicts on the trace
    must not start doing it — and the default has to be *empty*, not the collector's
    address, because a brain with no collector must not retry every tick."""
    from shared.config import load_settings

    assert load_settings().verdict_otlp_endpoint == ""


def test_the_verdict_export_is_read_from_the_environment(monkeypatch):
    from shared.config import load_settings

    monkeypatch.setenv("CS_VERDICT_OTLP_ENDPOINT", "http://collector:4318")
    assert load_settings().verdict_otlp_endpoint == "http://collector:4318"


def test_the_verdict_endpoint_loses_its_trailing_slash(monkeypatch):
    """The exporter appends `/v1/traces` itself. A trailing slash would make it
    `/v1/traces` twice over a double slash."""
    from shared.config import load_settings

    monkeypatch.setenv("CS_VERDICT_OTLP_ENDPOINT", "http://collector:4318/")
    assert load_settings().verdict_otlp_endpoint == "http://collector:4318"


def test_the_env_example_leaves_the_verdict_export_off():
    """`.env.example` is copied by people. A non-empty value there would turn the
    feature on for everybody who copies it — so it ships empty, with the comment
    saying what it is."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("CS_VERDICT_OTLP_ENDPOINT="))
    assert line.split("=", 1)[1].strip() == "", "the verdict export must ship off"
