"""
The learned tool risk (A14).

A human approves the same refund five times a day. The fifth time, asking again
is friction, not safety: the person has already answered the same question five
times, and the answer was yes. This module learns that — and, more importantly,
learns **nothing else**.

**What counts as an approval.** Only a human answer. A `policy` allow is the rules
doing their job; an `mcp` answer is another agent's opinion. Neither is a person
saying "yes, this is fine", so neither may teach the brain to stop asking. The rule
lives in `shared/contracts.py` (`tool_risk_from_history`) so the mock and the real
API cannot drift on it — this module only *applies* what that rule decided.

**A denial is a veto.** A call a human refused is never auto-approved, however many
approvals arrive later. Five yeses and one no is not a pattern of trust; it is a
pattern of a person who changed their mind, or of two people who disagreed.

**The learned score never loosens a deny.** It only turns a call that would have
been *held for approval* into one that is allowed. A policy rule that says `deny`
still denies, and the injection gate (A6) still denies. The brain learns to stop
asking about safe calls; it never learns to wave a dangerous one through.

**The audit trail.** Every auto-approval writes a `TOOL_AUTO_ALLOW` action by the
`brain:toolrisk` actor, naming how many approvals it was based on. An operator can
always see which calls went through on their own and why.

**The store is Fojle's folder**, so the history is read through the existing
`list_tool_calls` and filtered here, by agent.
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.contracts import (TOOL_RISK_AUTO_APPROVE_AFTER, tool_risk_from_history, tool_risk_signature,
                              tool_risk_view)

log = logging.getLogger("brain.tool_risk")

# How many tool calls to read when learning. The history that matters is the recent
# one: a call a human approved two years ago says nothing about today. The number is
# big enough that a busy fleet's approvals are not cut off mid-window.
HISTORY_LIMIT = 2000


def learn(store, agent_id: Optional[str] = None, threshold: int = TOOL_RISK_AUTO_APPROVE_AFTER) -> dict:
    """
    What has a human approved, and which calls may now go through on their own.

    The whole `ToolRiskReport`, exactly the shape the mock serves.
    """
    try:
        calls = store.list_tool_calls(limit=HISTORY_LIMIT)
    except Exception as exc:
        # A store that cannot be read must not stop the tool gate: the gate falls
        # back to asking a human, which is the safe direction.
        log.warning("could not read the tool-call history: %s", exc)
        calls = []
    if agent_id:
        calls = [c for c in calls if c.get("agent_id") == agent_id]
    return tool_risk_view(tool_risk_from_history(calls, threshold), threshold)


def is_auto_approved(store, agent_id: str, tool_name: str, args: dict,
                     threshold: int = TOOL_RISK_AUTO_APPROVE_AFTER) -> Optional[dict]:
    """
    May this exact call go through without a human? The entry, or `None`.

    `None` means "no — a human must decide", which is also the answer when the
    history cannot be read. The safe answer is always the default.
    """
    signature = tool_risk_signature(tool_name, args)
    for entry in learn(store, agent_id=agent_id, threshold=threshold)["entries"]:
        if entry["signature"] == signature:
            return entry if entry["auto_approved"] else None
    return None


def auto_approve_reason(entry: dict) -> str:
    """The reason written to the tool call and to the audit log."""
    return (f"auto-approved by the learned tool risk: {entry['approvals']} human approvals of this "
            f"exact call (threshold {entry['threshold']})")
