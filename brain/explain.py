"""
The incident explanation (A13).

"Explain what happened to this agent, and why" is the question an operator asks first.
Today the answer is spread over four endpoints — alerts, verdicts, actions, heal
proposals — and the operator has to stitch it together by hand. This module turns
those four into one story: **alert → verdict → action → heal**, oldest first, with a
plain-English paragraph on top.

**The paragraph is deterministic.** No key, no network, no clock of its own: the same
agent and the same store always produce the same words. That is what makes it
testable (a golden-text test pins the exact sentences) and what makes it safe to
cache. The optional Claude polish is layered on top and can only ever *add* a field —
it can never make the endpoint fail.

**The store is Fojle's folder**, so this module filters in the brain's own layer
rather than asking for new store methods: `recent_alerts` and `recent_actions` have
no agent filter, so the rows are filtered here, by agent and by window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from shared.contracts import explain_event, explain_report

log = logging.getLogger("brain.explain")

# How many rows of each kind are pulled before the window filter is applied.
# The store's list methods are newest-first and have no agent filter, so a fleet of
# fifty agents could push one agent's alert out of the top 50. These limits are big
# enough that the window filter still has something to work with.
_FETCH_LIMITS = {"alerts": 200, "verdicts": 50, "actions": 100, "heals": 50}


def _parse_ts(value) -> float:
    """An ISO timestamp → a unix timestamp. 0.0 when it cannot be read."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def _in_window(row: dict, since: float) -> bool:
    """Is this row inside the window? A row with no readable timestamp is kept.

    A row we cannot date is more likely to be old than new, but dropping it would
    silently hide the very alert that explains the agent's state — and an
    explanation that is quietly missing its cause is worse than no explanation.
    """
    ts = _parse_ts(row.get("created_at"))
    return ts <= 0.0 or ts >= since


def collect_events(store, agent_id: str, minutes: float = 10.0, now: Optional[float] = None) -> list[dict]:
    """
    The story of one agent in the last `minutes` minutes, oldest first.

    The order is the point: an alert that came *after* a verdict cannot have caused
    it, and an operator reading the events in the wrong order would draw the wrong
    conclusion. So the events are sorted by the time they happened, not by the table
    they came from.
    """
    import time as _time

    now_ts = float(now) if now is not None else _time.time()
    since = now_ts - float(minutes) * 60.0
    events: list[dict] = []

    for row in store.recent_alerts(limit=_FETCH_LIMITS["alerts"]):
        if row.get("agent_id") != agent_id or not _in_window(row, since):
            continue
        events.append(explain_event(
            "alert", _parse_ts(row.get("created_at")),
            str(row.get("rule") or "flagged"),
            str(row.get("message") or ""),
        ))

    for row in store.recent_verdicts(limit=_FETCH_LIMITS["verdicts"], agent_id=agent_id):
        if not _in_window(row, since):
            continue
        events.append(explain_event(
            "verdict", _parse_ts(row.get("created_at")),
            str(row.get("action") or "?"),
            str(row.get("reason") or ""),
        ))

    for row in store.recent_actions(limit=_FETCH_LIMITS["actions"]):
        if row.get("agent_id") != agent_id or not _in_window(row, since):
            continue
        events.append(explain_event(
            "action", _parse_ts(row.get("created_at")),
            str(row.get("action") or "?"),
            str(row.get("reason") or ""),
        ))

    for row in store.list_heal_proposals(agent_id=agent_id, limit=_FETCH_LIMITS["heals"]):
        if not _in_window(row, since):
            continue
        events.append(explain_event(
            "heal", _parse_ts(row.get("created_at")),
            str(row.get("kind") or "patch"),
            str(row.get("reason") or ""),
        ))

    events.sort(key=lambda e: e["ts"])
    return events


def build_explanation(store, agent_id: str, minutes: float = 10.0,
                      now: Optional[float] = None) -> Optional[dict]:
    """
    The whole `ExplainReport` for one agent, or `None` when the agent is unknown.

    The agent's state and money come from the same view the dashboard shows, so the
    explanation and the dashboard never disagree about what the agent is doing.

    `None` (rather than a report for an agent that does not exist) is what lets the
    API answer 404, the way the mock does — an explanation for a typo'd agent id
    would otherwise be a confident paragraph about nothing.
    """
    import time as _time

    from brain import service

    view = next((a for a in service.fleet_view(store) if a["agent_id"] == agent_id), None)
    if view is None:
        return None

    # The clock is read once, here, and used for the whole report. Two reads would
    # mean two windows: a row could fall inside one and outside the other.
    now_ts = float(now) if now is not None else _time.time()
    events = collect_events(store, agent_id, minutes=minutes, now=now_ts)
    # The saved money is on the actions, not on the events, so it is added up here.
    saved = 0.0
    for row in store.recent_actions(limit=_FETCH_LIMITS["actions"]):
        if row.get("agent_id") == agent_id and _in_window(row, now_ts - float(minutes) * 60.0):
            saved += float(row.get("usd_saved_estimate") or 0)
    return explain_report(
        agent_id, view.get("state", "unknown"), events, minutes=minutes,
        spend_usd=float(view.get("spend_usd") or 0),
        budget_usd=float(view.get("budget_usd") or 0),
        saved_usd=saved,
    )


def polish(report: dict, cfg=None, client=None) -> dict:
    """
    The optional Claude polish: rewrite `summary` into something smoother.

    **The endpoint never fails because of this.** If there is no key, no SDK, no
    network, or the model says something silly, the deterministic `summary` stays and
    `polished_summary` stays `None`. A slow third-party call must not be able to take
    the endpoint down — it is an extra, not a dependency.
    """
    report.setdefault("polished_summary", None)
    if not report.get("summary"):
        return report
    try:
        from brain.judge import Judge

        judge = Judge(cfg) if cfg is not None else None
        if judge is None:
            return report
        if judge.provider == "fallback":
            return report
        polished = judge.polish_explanation(report)
        if polished:
            report["polished_summary"] = polished
    except Exception as exc:
        log.warning("could not polish the explanation for %s: %s", report.get("agent_id"), exc)
    return report
