"""
The cascade: the chains where agents keep each other running (CONTRACTS §6, B6).

One runaway is one agent. A **cascade** is worse: the agents keep each other
running, so pausing one of them leaves the chain alive and the next one starts
the whole thing again. Stopping the chain one link at a time is not containing
it — it is moving the problem.

Two ideas carry the whole module:

- **the evidence is the call graph between the agents.** Agent A's span whose
  `parent_span_id` is a span of agent B means **B called A**. That gives a
  directed graph, and a **cycle** in it (A → B → A) is a cascade. A **fan-out**
  — one agent called by many, or calling many, in the window — is a
  **contagion**;
- **the containment is the whole chain, in one tick.** Every agent in the chain
  is paused together, because pausing one link of a cycle only moves it.

Why the call graph and not "these agents were busy at the same time". Being
nearby is not being connected. Two agents that happen to run in the same minute
are not a chain, and sweeping them up together would stop healthy work. The
graph is what makes the claim honest: an edge exists only when one agent
*actually called* the other.

Why the two lists are kept apart. `agents` is the **whole chain** and
`contained` is the part the brain actually stopped. An agent that was already
dead, or one this worker does not own, is in the chain and not in `contained`.
A report that collapsed the two would make the brain look like it contained
more than it did.

The *shapes* live in `shared/contracts.py` (the contract folder), so the mock
and the real API say exactly the same thing. What lives here is the **builder**:
the part that knows about the store, the fleet and the breaker.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from shared.contracts import (CASCADE_ACTION, CASCADE_ACTOR, CASCADE_RULES, ActionRow, AlertRow,
                              cascade_agent, cascade_edge, cascade_report, cascade_view)

log = logging.getLogger("brain.cascade")

# The rule that names each kind of cascade in the alerts table.
RULE_FOR_KIND = {"loop": "cascade_loop", "contagion": "cascade_contagion"}

# How many agents a chain may hold. A cycle in a fleet of two hundred agents
# would otherwise pause the whole fleet, and a chain that long is not a chain
# the brain can reason about — it is a broken trace.
MAX_CHAIN_AGENTS = 12


@dataclass
class CallGraph:
    """
    The agent-to-agent call graph, built from the spans in the window.

    `edges` maps a caller to its callees, with the number of calls. `calls`
    maps a caller to the *same* counts — the fan-out is read off it.
    """

    edges: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(dict))
    #: how many times each agent called another agent, per caller
    calls: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(dict))
    #: how many times each agent was called by another agent
    called: dict[str, int] = field(default_factory=dict)

    def callees(self, agent_id: str) -> list[str]:
        return sorted(self.edges.get(agent_id, {}))

    def callers(self, agent_id: str) -> list[str]:
        return sorted(src for src, targets in self.edges.items() if agent_id in targets)

    def call_count(self, source: str, target: str) -> int:
        return int(self.calls.get(source, {}).get(target, 0))

    def is_empty(self) -> bool:
        return not self.edges


def build_call_graph(spans: list[dict]) -> CallGraph:
    """
    Build the call graph from the spans.

    The evidence is the `parent_span_id`: a span by agent A whose parent is a
    span by agent B means **B called A**. A span with no parent — or with a
    parent the store has not seen — is not an edge: the brain will not guess a
    call it cannot point at.

    The window's own spans are ignored when they are the parent of themselves
    (a span cannot call itself) and a parent that belongs to the *same* agent
    is an ordinary in-agent step, not a call between two agents.
    """
    # span_id → agent_id, so a parent id can be resolved to the agent that made it.
    owner: dict[str, str] = {}
    for span in spans or []:
        span_id = str(span.get("span_id") or "").strip()
        agent_id = str(span.get("agent_id") or "").strip()
        if span_id and agent_id:
            owner[span_id] = agent_id

    graph = CallGraph()
    for span in spans or []:
        agent_id = str(span.get("agent_id") or "").strip()
        parent_id = str(span.get("parent_span_id") or "").strip()
        if not agent_id or not parent_id:
            continue
        parent_agent = owner.get(parent_id)
        if not parent_agent or parent_agent == agent_id:
            continue    # no parent we can see, or the agent's own inner step
        graph.edges[parent_agent][agent_id] = graph.edges[parent_agent].get(agent_id, 0) + 1
        graph.calls[parent_agent][agent_id] = graph.calls[parent_agent].get(agent_id, 0) + 1
        graph.called[agent_id] = graph.called.get(agent_id, 0) + 1
    return graph


def find_cycles(graph: CallGraph, max_agents: int = MAX_CHAIN_AGENTS) -> list[list[str]]:
    """
    The cycles in the call graph.

    Every cycle is found by walking from every agent and following the edges
    until an agent repeats — the repeated agent is the start of the cycle, and
    the walk from it is the cycle itself. The same cycle is only reported
    once, as the same set of agents in the same order (rotated so it always
    starts at the same agent), so a chain does not change its identity between
    ticks.
    """
    seen_cycles: set[tuple[str, ...]] = set()
    cycles: list[list[str]] = []
    for start in sorted(graph.edges):
        if len(cycles) >= max_agents:
            break
        path: list[str] = []
        on_path: set[str] = set()
        node = start
        while node not in on_path:
            if len(path) > max_agents:
                break   # a chain this long is a broken trace, not a chain
            path.append(node)
            on_path.add(node)
            callees = graph.callees(node)
            if not callees:
                break
            node = callees[0]        # the first callee keeps the walk deterministic
        if node in on_path:
            cycle = path[path.index(node):]
            if len(cycle) >= 2:     # a self-call is not a chain between two agents
                # rotate so the cycle always starts at the same agent
                pivot = cycle.index(min(cycle))
                cycle = cycle[pivot:] + cycle[:pivot]
                key = tuple(cycle)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(cycle)
    return cycles


def find_contagions(graph: CallGraph, fanout_calls: int) -> list[list[str]]:
    """
    The fan-outs: one agent flooding the others.

    A contagion is one agent making a lot of calls *into* another agent in the
    window — the flood. The two agents are the chain: the one flooding and the
    one being flooded. The victim is in the chain because its own spike is a
    symptom; it is **not** the one that started it.
    """
    if fanout_calls <= 0:
        return []
    chains: list[list[str]] = []
    for source in sorted(graph.calls):
        for target, count in sorted(graph.calls[source].items()):
            if count >= fanout_calls:
                chains.append([source, target])
    return chains


def _roles(chain: list[str], graph: CallGraph, kind: str) -> list[dict]:
    """
    The role each agent plays in the chain.

    In a **loop** the chain is a cycle, so every member both calls and is
    called — there is no single source. The agent that is called the most is
    the "source" of the pressure and the rest are "members".

    In a **contagion** the first agent is the "source" (it is doing the
    flooding) and the second is the "target" (it is being flooded).
    """
    if kind == "contagion" and len(chain) >= 2:
        return [cascade_agent(chain[0], "source", "it is flooding the others"),
                cascade_agent(chain[1], "target", "its own spike is a symptom of the flood")]
    counts = {agent: graph.called.get(agent, 0) for agent in chain}
    source = max(chain, key=lambda a: (counts.get(a, 0), a)) if chain else ""
    return [cascade_agent(agent, "source" if agent == source else "member",
                          f"calls {graph.call_count(agent, nxt)}× {nxt}" if nxt else "")
            for agent, nxt in ((a, chain[(i + 1) % len(chain)]) for i, a in enumerate(chain))] \
        if chain else []


def detect_cascades(spans: list[dict], cfg, minutes: Optional[float] = None) -> list[dict]:
    """
    Every cascade in the spans, as the contract's shape.

    A **loop** is a cycle in the call graph; a **contagion** is a fan-out. The
    chains are sorted so the same traces always give the same list, in the same
    order — a cascade that changes its identity between ticks is a cascade the
    operator cannot follow.
    """
    window_minutes = float(minutes if minutes is not None else cfg.cascade_window_minutes)
    graph = build_call_graph(spans or [])
    if graph.is_empty():
        return []

    chains: list[tuple[str, list[str]]] = []
    for cycle in find_cycles(graph):
        chains.append(("loop", cycle))
    for chain in find_contagions(graph, cfg.cascade_fanout_calls):
        chains.append(("contagion", chain))

    reports: list[dict] = []
    for kind, chain in chains:
        chain = sorted(set(chain))
        if not chain:
            continue
        edges = []
        for i, source in enumerate(chain):
            target = chain[(i + 1) % len(chain)]
            calls = graph.call_count(source, target)
            if calls:
                edges.append(cascade_edge(source, target, calls=calls))
        # The edges of the chain itself, plus every edge inside it — a cycle is
        # a cycle, and a reader must see the calls that made it.
        for source in chain:
            for target, calls in sorted(graph.calls.get(source, {}).items()):
                if target in chain and not any(e["source"] == source and e["target"] == target
                                               for e in edges):
                    edges.append(cascade_edge(source, target, calls=calls))
        edges.sort(key=lambda e: (e["source"], e["target"]))
        cascade_id = f"{kind}-" + "-".join(chain)
        reason = _reason(kind, chain, graph)
        reports.append(cascade_report(
            kind=kind, cascade_id=cascade_id,
            agents=_roles(chain, graph, kind),
            edges=edges, contained=[], detected_at=None, reason=reason))
    reports.sort(key=lambda r: (r["kind"], r["cascade_id"]))
    return reports


def _reason(kind: str, chain: list[str], graph: CallGraph) -> str:
    """The sentence an operator reads: what happened and who was in it."""
    names = " → ".join(chain)
    if kind == "contagion" and len(chain) >= 2:
        calls = graph.call_count(chain[0], chain[1])
        return f"{chain[0]} flooded {chain[1]}: {calls} calls in the window"
    return f"{names} → {chain[0]}: the agents keep each other running"


def contain(cascade: dict, engine, cfg, now: float) -> list[str]:
    """
    Contain the whole chain, in this tick.

    Every agent in the chain that the brain can act on is paused **together**.
    The chain is the unit: pausing one link of a cycle only moves the problem,
    because the other link starts it again.

    An agent that is already dead is not paused again (there is nothing to
    pause), and an agent this worker does not own is left alone — another
    worker owns it and will stop it itself. Both are in the chain and neither
    is in `contained`, and that is the honest answer.

    Returns the agents that were actually contained.
    """
    chain = [str(a.get("agent_id") or "") for a in (cascade.get("agents") or []) if a.get("agent_id")]
    if not chain:
        return []
    contained: list[str] = []
    for agent_id in chain:
        if not engine.owns(agent_id):
            continue
        breaker = engine.breakers.get(agent_id)
        if breaker is not None and not breaker.active:
            continue   # already paused or killed — nothing to stop
        reason = f"cascade {cascade.get('cascade_id') or cascade.get('kind')}: {cascade.get('reason') or ''}".strip()
        try:
            effect = breaker.on_command(CASCADE_ACTION, CASCADE_ACTOR, reason, now) if breaker else None
        except Exception:
            log.exception("could not contain %s in a cascade", agent_id)
            continue
        if effect is None:
            continue
        snapshot = None
        window = engine.windows.get(agent_id)
        if window is not None:
            try:
                snapshot = window.snapshot(now, engine.budget(agent_id))
            except Exception:
                snapshot = None
        try:
            engine._apply(agent_id, effect, snapshot)
        except Exception:
            log.exception("could not pause %s in a cascade", agent_id)
            continue
        contained.append(agent_id)

    cascade["contained"] = contained
    cascade["counts"]["contained"] = len(contained)
    rule = RULE_FOR_KIND.get(cascade.get("kind"), "cascade_loop")
    cascade_id = str(cascade.get("cascade_id") or cascade.get("kind") or "cascade")
    # The alert carries the cascade id, so the chain can be read back out of
    # the store — the alert is the record, exactly as the backtest (B5) treats
    # the alerts as the ground truth of what happened.
    message = f"cascade {cascade_id}: {cascade.get('reason') or ''}".strip()
    for agent_id in contained:
        try:
            engine.store.insert_alert(AlertRow(agent_id, "critical", rule, message))
        except Exception:
            log.exception("could not write the cascade alert for %s", agent_id)
    return contained


def cascades_from_store(store, minutes: float = 60.0, as_of: Optional[float] = None) -> dict:
    """
    The cascades in the store's own record, read back.

    The brain writes a cascade as an **alert** on every agent it contained (the
    rules `cascade_loop` / `cascade_contagion`), so the chain can be read back
    without a new table: the alerts are the record, exactly as the backtest
    (B5) treats the alerts as the ground truth of what happened.
    """
    alerts = store.recent_alerts(limit=200) or []
    cascades: list[dict] = []
    by_id: dict[str, dict] = {}
    for row in alerts:
        rule = str(row.get("rule") or "")
        if rule not in CASCADE_RULES:
            continue
        agent_id = str(row.get("agent_id") or "")
        if not agent_id:
            continue
        message = str(row.get("message") or "")
        cascade_id = _cascade_id_from_message(message)
        if cascade_id is None:
            continue
        cascade = by_id.get(cascade_id)
        if cascade is None:
            kind = "loop" if rule == "cascade_loop" else "contagion"
            cascade = cascade_report(kind=kind, cascade_id=cascade_id,
                                     agents=[], edges=[], contained=[],
                                     detected_at=row.get("created_at"), reason=message)
            by_id[cascade_id] = cascade
            cascades.append(cascade)
        cascade["contained"].append(agent_id)
        cascade["counts"]["contained"] = len(cascade["contained"])
        cascade["agents"].append(cascade_agent(agent_id, "member", message))
        cascade["counts"]["agents"] = len(cascade["agents"])
    cascades.sort(key=lambda c: str(c.get("cascade_id") or ""))
    return cascade_view(cascades=cascades, as_of=as_of)


def _cascade_id_from_message(message: str) -> Optional[str]:
    """
    The cascade id inside an alert message.

    The brain writes "cascade <id>: <reason>", so the id can be read back out
    of the alert — the same way the alert is the record of the incident.
    """
    text = str(message or "")
    if not text.startswith("cascade "):
        return None
    rest = text[len("cascade "):]
    return rest.split(":", 1)[0].strip() or None


def record_cascade(engine, cascade: dict) -> None:
    """
    Write the cascade to the store as the actions of a containment.

    Every contained agent gets a `PAUSE` action by the `brain:cascade` actor,
    so the audit log says *why* the agent was stopped — and the money saved is
    the same ROI formula the live system uses.
    """
    reason = f"cascade {cascade.get('cascade_id') or ''}: {cascade.get('reason') or ''}".strip()
    for agent_id in cascade.get("contained") or []:
        usd = 0.0
        window = engine.windows.get(agent_id)
        if window is not None:
            try:
                snap = window.snapshot(engine.last_seen or 0.0, engine.budget(agent_id))
                usd = round(snap.usd_per_min * engine.cfg.roi_horizon_minutes, 4)
            except Exception:
                usd = 0.0
        try:
            from brain import audit as brain_audit

            brain_audit.record_action(engine.store, agent_id=agent_id, action=CASCADE_ACTION,
                                      actor=CASCADE_ACTOR, reason=reason,
                                      enabled=getattr(engine.cfg, "audit_enabled", False),
                                      usd_saved=usd)
        except Exception:
            log.exception("could not write the cascade action for %s", agent_id)


__all__ = [
    "CallGraph", "MAX_CHAIN_AGENTS", "RULE_FOR_KIND", "build_call_graph",
    "cascades_from_store", "contain", "detect_cascades", "find_cycles",
    "find_contagions", "record_cascade",
]
