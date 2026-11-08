"""
The incident postmortem (B2).

An incident *is* an alert: the moment the brain flagged an agent and said
"something is wrong here". The verdict that followed, the action that was taken
and the heal that fixed it are all part of *that* incident — so the incident id
is the alert id, and `GET /v1/incidents/{id}/postmortem` answers 404 for an id
no alert ever had.

**The shape lives in `shared/contracts.py`**, not here, for the same reason the
explain report lives there: the mock API and the real API must say the same
thing. Written twice they would drift, and the golden test would only compare
the mock with itself. This module is the *builder* — it finds the rows, works
out the numbers, and hands them to the contract.

**The store is Fojle's folder**, so this module filters in the brain's own layer
rather than asking for new store methods: `recent_alerts` and `recent_actions`
have no agent filter, so the rows are filtered here.

**A number that cannot be measured is `None`, never a made-up zero.** "0.0
seconds" and "we do not know" are different facts and only one of them is true.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from shared.contracts import (POSTMORTEM_SAVING_ACTIONS, postmortem_event,
                              postmortem_report, postmortem_root_cause)

log = logging.getLogger("brain.postmortem")

# How many rows of each kind are pulled before the filters are applied. The
# store's list methods are newest-first and have no agent filter, so a fleet of
# fifty agents could push one agent's alert out of the top 50.
_FETCH_LIMITS = {"alerts": 500, "verdicts": 50, "actions": 200, "heals": 100}

# How far back the evidence is looked for. An incident's evidence is the
# behaviour that caused it, and that can be a while before the brain noticed:
# an agent can loop for ten minutes and only then cross the threshold. The
# window is generous, and the *first* span inside it is the evidence.
_EVIDENCE_WINDOW_SECONDS = 30 * 60

# How many spans the evidence list holds. A postmortem is a summary a human
# reads; a hundred spans is a data dump.
_EVIDENCE_LIMIT = 10

# How many spans are read before the incident's own window is applied. The
# store's `spans_after` has no time filter, so a busy fleet would push the
# incident's own spans out of the read.
_SPAN_FETCH_LIMIT = 5000


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


def _find_alert(store, incident_id: int) -> Optional[dict]:
    """The alert that *is* the incident, or `None` when there is no such alert.

    The alerts are pulled newest-first and the ids only grow, so the search can
    stop as soon as it passes the id — but it does not: the ids in a sharded
    store are not guaranteed to be ordered, so the whole list is scanned.
    """
    for row in store.recent_alerts(limit=_FETCH_LIMITS["alerts"]):
        if int(row.get("id") or 0) == int(incident_id):
            return row
    return None


def _evidence_spans(store, agent_id: str, before_ts: float, limit: int = _EVIDENCE_LIMIT) -> list[dict]:
    """
    The real spans that led to the alert — the evidence a reader can pull out
    of Phoenix by hand.

    These are the *real* span ids, not a summary of them: a postmortem whose
    evidence cannot be opened is a story, not a record. The spans are the ones
    that happened **before** the alert (a span after the alert cannot have
    caused it) and, when they carry a timestamp, close enough to it to be part
    of the same story.

    The store's `recent_spans` filters on the *wall clock* — "the last five
    minutes" — which is the wrong question here. A postmortem is written about
    an incident that already happened, so its evidence can be hours old; and
    the incident's own clock is not the server's clock. So the spans are read
    without a time filter and the window is applied here, around the alert.
    """
    picked: list[dict] = []
    for row in store.spans_after(0, limit=_SPAN_FETCH_LIMIT):
        if row.get("agent_id") != agent_id:
            continue
        start_ts = float(row.get("start_ts") or 0)
        if start_ts and start_ts > before_ts:
            continue  # a span after the alert cannot have caused it
        if start_ts and before_ts - start_ts > _EVIDENCE_WINDOW_SECONDS:
            continue  # too old to be part of this story
        picked.append({
            "span_id": str(row.get("span_id") or ""),
            "trace_id": str(row.get("trace_id") or ""),
            "operation": str(row.get("operation") or ""),
            "start_ts": start_ts,
        })
    picked.sort(key=lambda s: s["start_ts"])
    # The newest evidence is the closest to the alert, and the closest is the
    # most explanatory — the loop that is still spinning when the brain gave up.
    return picked[-limit:]


def build_postmortem(store, incident_id: int, now: Optional[float] = None) -> Optional[dict]:
    """
    The whole `PostmortemReport` for one incident, or `None` when the incident
    does not exist.

    `None` (rather than a report about an alert that never fired) is what lets
    the API answer 404, the way the mock does — a postmortem of nothing would
    be a confident account of a thing that never happened.
    """
    now_ts = float(now) if now is not None else time.time()
    alert = _find_alert(store, incident_id)
    if alert is None:
        return None

    agent_id = str(alert.get("agent_id") or "")
    alert_ts = _parse_ts(alert.get("created_at"))
    rule = str(alert.get("rule") or "")

    # The judge is the one who says *why*; the rule is what the detectors
    # measured. When the judge said nothing, the rule is the pattern too — a
    # rule that fired is a pattern even when nobody explained it.
    verdict = _verdict_for(store, agent_id, alert_ts)
    pattern = str(verdict.get("pattern") or "") if verdict else ""
    reason = str(verdict.get("reason") or "") if verdict else ""
    detector = str(verdict.get("source") or "rules") if verdict else "rules"

    timeline = [
        postmortem_event("alert", alert_ts, rule or "flagged",
                         str(alert.get("message") or ""), ref=str(alert.get("id"))),
    ]
    if verdict:
        timeline.append(postmortem_event(
            "verdict", _parse_ts(verdict.get("created_at")),
            str(verdict.get("action") or "?"), reason, ref=str(verdict.get("id"))))

    actions = _actions_for(store, agent_id, alert_ts)
    for row in actions:
        timeline.append(postmortem_event(
            "action", _parse_ts(row.get("created_at")),
            str(row.get("action") or "?"), str(row.get("reason") or ""),
            ref=str(row.get("id"))))

    heals = _heals_for(store, agent_id, alert_ts)
    for row in heals:
        timeline.append(postmortem_event(
            "heal", _parse_ts(row.get("created_at")),
            str(row.get("kind") or "patch"), str(row.get("reason") or ""),
            ref=str(row.get("id"))))

    evidence = _evidence_spans(store, agent_id, alert_ts)
    if evidence:
        first_evidence_ts = min(s["start_ts"] for s in evidence if s["start_ts"])
        timeline.append(postmortem_event(
            "evidence", first_evidence_ts, "the agent started misbehaving",
            f"{len(evidence)} span(s) before the alert", ref=evidence[0]["span_id"]))

    # The timings. Both are *measured*, never guessed: the detection time is
    # the gap between the first evidence and the alert, and the heal time is
    # the gap between the alert and the action that answered it. When the gap
    # cannot be measured, the answer is `None` — "we do not know", which is a
    # true thing to say, unlike "0.0 seconds".
    detect_seconds = _seconds(alert_ts - first_evidence_ts) if evidence else None
    heal_seconds = None
    healed_at = None
    if actions:
        healed_at = _parse_ts(actions[0].get("created_at"))
        heal_seconds = _seconds(healed_at - alert_ts) if alert_ts else None

    saved_usd, saved_tokens = _saved_money(actions)
    spend_usd = _spend_of(store, agent_id)

    return postmortem_report(
        int(alert.get("id") or 0), agent_id,
        postmortem_root_cause(rule, pattern, reason, detector=detector),
        timeline, evidence,
        {"usd_saved": saved_usd, "tokens_saved": saved_tokens, "spend_usd": spend_usd},
        {"time_to_detect_seconds": detect_seconds, "time_to_heal_seconds": heal_seconds,
         "detected_at": alert_ts or None, "healed_at": healed_at},
        resolution=_resolution(actions, agent_id),
    )


def _seconds(delta) -> Optional[float]:
    """A gap in seconds, or `None` when there is no gap to measure."""
    if delta is None:
        return None
    value = float(delta)
    # A negative gap means the clock went backwards or a row was misdated.
    # Reporting a negative "time to detect" would be a lie in the other
    # direction, so it is not measured.
    return round(value, 1) if value >= 0 else None


def _verdict_for(store, agent_id: str, alert_ts: float) -> Optional[dict]:
    """The judge's verdict on this agent, closest to the alert.

    The verdict that *caused* the alert is the one that came after it (the
    brain flags, then the judge decides) — but a verdict from long before the
    alert is not this incident's verdict either, so the closest one after the
    alert wins.
    """
    candidates = []
    for row in store.recent_verdicts(limit=_FETCH_LIMITS["verdicts"], agent_id=agent_id):
        ts = _parse_ts(row.get("created_at"))
        if ts >= alert_ts:
            candidates.append((ts, row))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


def _actions_for(store, agent_id: str, alert_ts: float) -> list[dict]:
    """The actions that answered this alert, oldest first.

    Only the actions that came *after* the alert belong to this incident — an
    action from before it is somebody else's story.
    """
    rows = []
    for row in store.recent_actions(limit=_FETCH_LIMITS["actions"]):
        if row.get("agent_id") != agent_id:
            continue
        if _parse_ts(row.get("created_at")) < alert_ts:
            continue
        rows.append(row)
    rows.sort(key=lambda r: _parse_ts(r.get("created_at")))
    return rows


def _heals_for(store, agent_id: str, alert_ts: float) -> list[dict]:
    """The heal proposals that came after the alert, oldest first."""
    rows = []
    for row in store.list_heal_proposals(agent_id=agent_id, limit=_FETCH_LIMITS["heals"]):
        if _parse_ts(row.get("created_at")) < alert_ts:
            continue
        rows.append(row)
    rows.sort(key=lambda r: _parse_ts(r.get("created_at")))
    return rows


def _saved_money(actions: list[dict]) -> tuple[float, int]:
    """
    The money the actions saved — added up from the actions themselves.

    Only the actions that actually stop a runaway count: a KILL or a PAUSE
    stops the spending, while a WARN or a SET_BUDGET does not save anything by
    itself. This is the same set the ROI formula names (`POSTMORTEM_SAVING_ACTIONS`).
    """
    usd = 0.0
    tokens = 0
    for row in actions:
        if str(row.get("action") or "") not in POSTMORTEM_SAVING_ACTIONS:
            continue
        usd += float(row.get("usd_saved_estimate") or 0)
        tokens += int(row.get("tokens_saved_estimate") or 0)
    return round(usd, 4), tokens


def _spend_of(store, agent_id: str) -> float:
    """What the agent had spent when the incident was handled."""
    try:
        from brain import service
        view = next((a for a in service.fleet_view(store) if a["agent_id"] == agent_id), None)
        return round(float((view or {}).get("spend_usd") or 0.0), 4)
    except Exception as exc:  # the money is a nice-to-have; the story is not
        log.warning("could not read the spend for %s: %s", agent_id, exc)
        return 0.0


def _resolution(actions: list[dict], agent_id: str) -> str:
    """One line: what finally happened to this agent."""
    if not actions:
        return f"{agent_id} was flagged and no action was taken."
    last = actions[-1]
    action = str(last.get("action") or "?")
    reason = str(last.get("reason") or "")
    if reason:
        return f"{agent_id} was {action}: {reason}"
    return f"{agent_id} was {action}."
