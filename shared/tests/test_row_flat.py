"""
The rows' `to_row()` — fast, and byte-for-byte the same as before.

The rows are **flat**: every field is a scalar, and the JSON columns hold JSON
*text* (`tool_args`, `detail`, `baseline`, `patch` are strings), not nested
Python objects. That is why `to_row()` can build the dict directly instead of
calling `dataclasses.asdict` — `asdict` is a **deep** copy, and a deep copy of
a flat row buys nothing.

Two things have to be true, and this file checks both:

1. **the fast path is exactly the old result.** A row that used to produce
   `{"a": 1}` must still produce `{"a": 1}`. A speed-up that changes a value is
   a bug with a good excuse;
2. **a row that grows a nested field is still correct.** The fast path is
   opt-in per row class, so a new row that is not known to be flat falls back
   to `asdict` and cannot silently write a nested object into the row dict.
"""
from __future__ import annotations

import timeit
from dataclasses import asdict, dataclass, field, fields

from shared.contracts import (ActionRow, AgentRow, AlertRow, AuditRow, CommandRow, HealProposalRow,
                              MemoryRow, MetricRow, SpanRow, ToolCallRow, ToolRegistryRow, VerdictRow)


def _rows():
    """One instance of every row, with its required fields filled in."""
    return [
        SpanRow("beta", "chat", "chat sim", tool_args='{"x": 1}', detail='{"node": "n"}'),
        MetricRow("beta", "healthy", tokens_per_min=10),
        AlertRow("beta", "warning", "reason", "message"),
        VerdictRow("beta", 1, "PAUSE", 0.9, "semantic_loop", "it loops"),
        ActionRow("beta", "PAUSE", "rules", "loop", 1.5, 100),
        CommandRow("beta", "pause", "rules"),
        AuditRow(1, "beta", "decision", "rules", "PAUSE", "loop", "prev", "hash"),
        MemoryRow("beta", 1, '{"k": "v"}'),
        ToolCallRow("beta", "refund", '{"amount": 50000}'),
        ToolRegistryRow("mcp", "refund", "a tool", "mcp", "clean", "", 0.0),
        AgentRow("beta", state="healthy"),
        HealProposalRow("beta", confidence=0.9),
    ]


def test_every_row_to_row_is_the_same_as_asdict():
    """The fast path must not change a single value."""
    for row in _rows():
        assert row.to_row() == asdict(row), f"{type(row).__name__} changed"


def test_every_row_to_row_has_exactly_the_table_columns():
    """A row dict is the table's columns — no more, no less."""
    for row in _rows():
        expected = {f.name for f in fields(row)}
        assert set(row.to_row()) == expected, type(row).__name__


def test_the_json_columns_are_text_and_not_objects():
    """The JSON columns travel as JSON *text*, which is what the schema says."""
    span = SpanRow("beta", "chat", "n", tool_args='{"x": 1}').to_row()
    assert span["tool_args"] == '{"x": 1}'
    assert isinstance(span["tool_args"], str)


def test_the_agent_baseline_still_goes_out_as_json_text():
    """`AgentRow` overrides `to_row()`, so it is not on the fast path — and it
    must still turn a dict into JSON text, because that is the column type."""
    row = AgentRow("beta", baseline={"tokens_per_min": {"median": 4000}})
    out = row.to_row()
    assert out["baseline"] == '{"tokens_per_min": {"median": 4000}}'
    assert isinstance(out["baseline"], str)


def test_a_row_that_is_not_known_to_be_flat_falls_back_to_asdict():
    """
    The safety net.

    If a row class is not on the flat list, `to_row()` must behave exactly as
    `asdict` does — including deep-copying a nested value. A row that grows a
    nested field must not suddenly write a live object into the row dict.
    """
    from shared import contracts

    @dataclass
    class NestedRow(contracts._Row):
        agent_id: str
        payload: dict = field(default_factory=dict)

    row = NestedRow("beta", payload={"k": [1, 2]})
    out = row.to_row()
    assert out == {"agent_id": "beta", "payload": {"k": [1, 2]}}
    # and the nested value is a copy, not the same object
    assert out["payload"] is not row.payload


def test_the_flat_rows_are_the_ones_we_think_they_are():
    """The marking is a claim about the schema, so it is checked against the schema."""
    from shared.contracts import _Row

    marked = [cls for cls in vars(__import__("shared.contracts", fromlist=["_Row"])).values()
              if isinstance(cls, type) and issubclass(cls, _Row)
              and getattr(cls, "_FLAT_FIELDS", None) is not None]
    assert marked, "some rows must be marked flat, or the speed-up is gone"

    for cls in marked:
        for f in fields(cls):
            assert not isinstance(f.default, (dict, list)), \
                f"{cls.__name__}.{f.name} has a container default, so the row is not flat"
            assert f.type not in (dict, list), \
                f"{cls.__name__}.{f.name} is a container type, so the row is not flat"


def test_to_row_is_faster_than_asdict():
    """
    The reason this change exists.

    The collector writes every span the fleet produces, and `asdict` deep-copies
    every value on the way. This is the number the change was made for, and it
    is a **ratio**, not an absolute: it must hold on a slow machine and a fast
    one alike.
    """
    span = SpanRow("beta", "chat", "chat sim", tool_args='{"x": 1}', detail='{"n": 1}')
    number = 20000

    fast = timeit.timeit(span.to_row, number=number) / number
    slow = timeit.timeit(lambda: asdict(span), number=number) / number

    assert fast < slow, f"the fast path ({fast:.3f} ms) is not faster than asdict ({slow:.3f} ms)"
    # and it is faster by a margin, not by noise
    assert fast * 1.5 < slow, f"the speed-up is too small to be worth the risk ({fast:.3f} vs {slow:.3f})"
