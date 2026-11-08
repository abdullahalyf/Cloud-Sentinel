"""
The contract test for B1's new span attributes: the `verified_heal` flow.

The shadow dry-run's verdict and the decision it produced ride on the agent's own trace as a
`verified_heal` span event. The attribute names live in `shared/contracts.py`, which is the
contract, so the test lives in `shared/tests/`.

Additive only: these names are new, nothing existing is renamed or removed.
"""
from __future__ import annotations

from shared.contracts import Attr


def test_the_shadow_attributes_exist():
    """Every attribute the shadow flow writes must be in the contract."""
    for name in (
        "CS_HEAL_SHADOW_VERDICT",
        "CS_HEAL_APPLIED",
        "CS_HEAL_CONFIDENCE",
        "CS_HEAL_LOOP_SCORE_BEFORE",
        "CS_HEAL_LOOP_SCORE_AFTER",
        "CS_HEAL_REASON",
    ):
        assert hasattr(Attr, name), f"Attr.{name} must exist"


def test_the_shadow_attributes_are_namespaced():
    """Every new attribute is under `cloudsentinel.heal.` — nothing lands on a bare name."""
    for name in ("CS_HEAL_SHADOW_VERDICT", "CS_HEAL_APPLIED", "CS_HEAL_CONFIDENCE",
                 "CS_HEAL_LOOP_SCORE_BEFORE", "CS_HEAL_LOOP_SCORE_AFTER", "CS_HEAL_REASON"):
        value = getattr(Attr, name)
        assert value.startswith("cloudsentinel.heal."), f"{name} = {value}"


def test_the_shadow_attribute_names_are_unique():
    """Two attributes with the same name would silently overwrite each other on the span."""
    names = [
        Attr.CS_HEAL_SHADOW_VERDICT,
        Attr.CS_HEAL_APPLIED,
        Attr.CS_HEAL_CONFIDENCE,
        Attr.CS_HEAL_LOOP_SCORE_BEFORE,
        Attr.CS_HEAL_LOOP_SCORE_AFTER,
        Attr.CS_HEAL_REASON,
    ]
    assert len(set(names)) == len(names)


def test_the_shadow_attributes_are_documented_in_the_contracts():
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "CONTRACTS.md"
    text = doc.read_text(encoding="utf-8")
    for value in (
        Attr.CS_HEAL_SHADOW_VERDICT,
        Attr.CS_HEAL_APPLIED,
        Attr.CS_HEAL_CONFIDENCE,
        Attr.CS_HEAL_LOOP_SCORE_BEFORE,
        Attr.CS_HEAL_LOOP_SCORE_AFTER,
        Attr.CS_HEAL_REASON,
    ):
        assert value in text, f"docs/CONTRACTS.md §4 must document {value}"
