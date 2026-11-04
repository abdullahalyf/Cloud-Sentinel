"""
ROI attribution engine (CONTRACTS §8).   Owner: Orin.

Pure functions over plain dict rows (spans, actions, tool_calls) — no database, no network.
The brain's GET /v1/roi calls build_report().
"""
from __future__ import annotations

from collections import defaultdict

from shared.contracts import ROI_FORMULA

SAVING_ACTIONS = ("KILL", "PAUSE", "TOOL_DENY", "TOOL_REWRITE")


def total_spend(spans: list[dict]) -> float:
    return round(sum(float(s.get("cost_usd") or 0) for s in spans), 4)


def spend_by_agent(spans: list[dict]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for s in spans:
        out[s.get("agent_id", "unknown")] += float(s.get("cost_usd") or 0)
    return {k: round(v, 4) for k, v in sorted(out.items())}


def saved_by_action(actions: list[dict]) -> list[dict]:
    """Every intervention that saved money, using the estimate the brain stored at action time."""
    items = []
    for a in actions:
        if a.get("action") in SAVING_ACTIONS and float(a.get("usd_saved_estimate") or 0) > 0:
            items.append({"action_id": a.get("id"), "agent_id": a.get("agent_id"), "action": a.get("action"),
                          "actor": a.get("actor"), "usd": round(float(a["usd_saved_estimate"]), 4)})
    return items


def build_report(spans: list[dict], actions: list[dict], tool_calls: list[dict], horizon_minutes: float) -> dict:
    saved = saved_by_action(actions)
    return {
        "total_spend_usd": total_spend(spans),
        "spend_by_agent": spend_by_agent(spans),
        "saved_usd": round(sum(i["usd"] for i in saved), 4),
        "saved_by_action": saved,
        "interventions": sum(1 for a in actions if a.get("action") in SAVING_ACTIONS),
        "tool_calls_held": sum(1 for t in tool_calls if t.get("decided_by") in ("human", "mcp", "timeout")),
        # TODO(Orin, Day 2): implement cost_per_successful_task() and fill these two keys
        "tasks_succeeded": 0,
        "cost_per_successful_task_usd": 0.0,
        "horizon_minutes": horizon_minutes,
        "formula": ROI_FORMULA.replace("horizon", f"horizon ({horizon_minutes:g} min)"),
    }
