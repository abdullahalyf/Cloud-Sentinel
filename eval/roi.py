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


# ── cost → per-task success (example prompt P5: "ROI attribution engine") ─────────────────────────────
def task_costs(spans: list[dict]) -> tuple[list[dict], dict[str, float]]:
    """
    Attribute every span's cost to the task it belongs to. A task = one `invoke_agent` span; its chat /
    tool / graph_node children share its trace_id. Returns (tasks, unattributed_by_agent):
      tasks = [{task_id, agent_id, status, cost_usd}]   status: success | failure | abandoned
      unattributed = cost of spans whose task has not finished yet (e.g. a graph stuck in a loop) or
                     that were sent without a task — shown, never silently dropped.
    """
    roots: dict[str, dict] = {}
    for s in spans:
        if s.get("operation") == "invoke_agent" and s.get("trace_id"):
            roots[s["trace_id"]] = s
    cost: dict[str, float] = defaultdict(float)
    unattributed: dict[str, float] = defaultdict(float)
    for s in spans:
        c = float(s.get("cost_usd") or 0)
        if s.get("trace_id") in roots:
            cost[s["trace_id"]] += c
        elif c:
            unattributed[s.get("agent_id", "unknown")] += c
    tasks = [{"task_id": r.get("task_id") or trace, "agent_id": r.get("agent_id", "unknown"),
              "status": r.get("task_status") or "abandoned", "cost_usd": round(cost[trace], 6)}
             for trace, r in roots.items()]
    return tasks, {k: round(v, 6) for k, v in unattributed.items()}


def cost_per_successful_task(spans: list[dict]) -> float:
    """Fully loaded unit cost: ALL spend (including failed and unfinished work) ÷ tasks that succeeded."""
    tasks, _ = task_costs(spans)
    succeeded = sum(1 for t in tasks if t["status"] == "success")
    return round(total_spend(spans) / succeeded, 4) if succeeded else 0.0


def tasks_by_agent(spans: list[dict]) -> dict[str, dict]:
    """Per agent: how many tasks, how many succeeded, what they cost, and what was wasted."""
    tasks, unattributed = task_costs(spans)
    out: dict[str, dict] = {}
    for agent in sorted({t["agent_id"] for t in tasks} | set(unattributed)):
        mine = [t for t in tasks if t["agent_id"] == agent]
        ok = [t for t in mine if t["status"] == "success"]
        spend = sum(t["cost_usd"] for t in mine) + unattributed.get(agent, 0.0)
        wasted = sum(t["cost_usd"] for t in mine if t["status"] != "success") + unattributed.get(agent, 0.0)
        out[agent] = {"tasks": len(mine), "succeeded": len(ok), "failed": sum(t["status"] == "failure" for t in mine),
                      "abandoned": sum(t["status"] == "abandoned" for t in mine),
                      "success_rate": round(len(ok) / len(mine), 3) if mine else 0.0,
                      "spend_usd": round(spend, 4), "wasted_usd": round(wasted, 4),
                      "unattributed_usd": round(unattributed.get(agent, 0.0), 4),
                      "cost_per_success_usd": round(spend / len(ok), 4) if ok else 0.0}
    return out


def explain_agent(agent_id: str, stats: dict) -> str:
    """Human-readable ROI sentence for an agent (O3)."""
    tasks = stats.get("tasks", 0)
    succeeded = stats.get("succeeded", 0)
    pct = int(round(stats.get("success_rate", 0) * 100))
    spend = stats.get("spend_usd", 0.0)
    wasted = stats.get("wasted_usd", 0.0)
    cost_per = stats.get("cost_per_success_usd", 0.0)
    if succeeded == 0:
        return f"{agent_id}: {tasks} tasks, 0 succeeded; ${spend:.4f} spent, ${wasted:.4f} wasted; no successful task yet"
    return f"{agent_id}: {tasks} tasks, {succeeded} succeeded ({pct}%); ${spend:.4f} spent, ${wasted:.4f} wasted; ${cost_per:.4f} per successful task"


def build_report(spans: list[dict], actions: list[dict], tool_calls: list[dict], horizon_minutes: float) -> dict:
    saved = saved_by_action(actions)
    per_agent = tasks_by_agent(spans)
    for agent_id, stats in per_agent.items():
        stats["sentence"] = explain_agent(agent_id, stats)
    return {
        "total_spend_usd": total_spend(spans),
        "spend_by_agent": spend_by_agent(spans),
        "saved_usd": round(sum(i["usd"] for i in saved), 4),
        "saved_by_action": saved,
        "interventions": sum(1 for a in actions if a.get("action") in SAVING_ACTIONS),
        "tool_calls_held": sum(1 for t in tool_calls if t.get("decided_by") in ("human", "mcp", "timeout")),
        "tasks_total": sum(a["tasks"] for a in per_agent.values()),
        "tasks_succeeded": sum(a["succeeded"] for a in per_agent.values()),
        "cost_per_successful_task_usd": cost_per_successful_task(spans),
        "wasted_usd": round(sum(a["wasted_usd"] for a in per_agent.values()), 4),
        "tasks_by_agent": per_agent,
        "horizon_minutes": horizon_minutes,
        "formula": ROI_FORMULA.replace("horizon", f"horizon ({horizon_minutes:g} min)"),
    }
