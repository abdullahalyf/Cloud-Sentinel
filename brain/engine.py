"""
Engine: the main loop (ARCHITECTURE §3). Once per tick:

  1. run pending commands (pause / resume / kill / restart / budgets / demo triggers)
  2. read new spans from the store → per-agent windows
  3. read runtime status + memory from the executor
  4. per agent: snapshot → detectors → breaker → (judge in background) → executor + database
  5. expire tool calls nobody decided on

The engine must NEVER die: every step is wrapped, errors are logged, the loop continues.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional

from brain.breaker import Breaker, Effect
from brain.detectors import Finding, evaluate
from brain.judge import Judge, JudgeContext, Verdict
from brain.policy import Policy
from brain.state import AgentWindow, Snapshot
from shared.config import Settings
from shared.contracts import (ActionRow, AgentRow, AlertRow, Executor, MetricRow, RuntimeInfo, VerdictRow,
                              load_json, utc_now_iso)

log = logging.getLogger("brain.engine")


class Engine:
    def __init__(self, store, executor: Executor, judge: Judge, policy: Policy, cfg: Settings,
                 dry_run: bool = False, sync_judge: bool = False, runtime_name: str = "fake"):
        self.store, self.executor, self.judge, self.policy, self.cfg = store, executor, judge, policy, cfg
        self.dry_run, self.sync_judge, self.runtime_name = dry_run, sync_judge, runtime_name
        self.windows: dict[str, AgentWindow] = {}
        self.breakers: dict[str, Breaker] = {}
        self.budgets: dict[str, float] = {}
        self.last_judged: dict[str, float] = {}
        self.pending: dict[str, Future] = {}
        self.cursor = 0
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="judge")

    # ── main loop ────────────────────────────────────────────────────────────
    def run_forever(self, before_tick=None) -> None:
        log.info("Engine running (tick %.1fs, dry_run=%s, judge=%s)", self.cfg.tick_seconds, self.dry_run,
                 self.judge.provider)
        while True:
            started = time.time()
            try:
                if before_tick:
                    before_tick(started)
                self.tick(started)
            except Exception:
                log.exception("tick failed — continuing")
            time.sleep(max(0.0, self.cfg.tick_seconds - (time.time() - started)))

    def tick(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self._safe(self._run_commands, now)
        self._safe(self._ingest)
        runtime = {r.agent_id: r for r in (self._safe(self.executor.list_agents) or [])}
        for agent_id in sorted(set(self.windows) | set(runtime)):
            self._safe(self._watch, agent_id, runtime.get(agent_id), now)
        self._safe(self._expire_tool_calls, now)

    @staticmethod
    def _safe(fn, *args):
        try:
            return fn(*args)
        except Exception:
            log.exception("%s failed", getattr(fn, "__name__", fn))
            return None

    # ── helpers ──────────────────────────────────────────────────────────────
    def _ingest(self) -> None:
        while True:
            spans = self.store.spans_after(self.cursor)
            if not spans:
                return
            for s in spans:
                self.cursor = max(self.cursor, int(s["id"]))
                agent_id = str(s.get("agent_id") or "").strip()
                if not agent_id:
                    log.warning("skipping span %s without agent_id", s.get("id"))
                    continue
                try:
                    self._window(agent_id).add(s)
                except Exception:  # one malformed span must never block the others
                    log.exception("skipping malformed span %s from %s", s.get("id"), agent_id)
            if len(spans) < 2000:
                return

    def _window(self, agent_id: str) -> AgentWindow:
        if agent_id not in self.windows:
            self.windows[agent_id] = AgentWindow(agent_id)
        return self.windows[agent_id]

    def _breaker(self, agent_id: str) -> Breaker:
        if agent_id not in self.breakers:
            self.breakers[agent_id] = Breaker(agent_id, self.cfg.probation_seconds, self.cfg.brain_kill_confidence,
                                              self.policy.on_trip, self.policy.on_hard_limit)
            log.info("Now watching %s (budget $%.2f)", agent_id, self.budget(agent_id))
        return self.breakers[agent_id]

    def budget(self, agent_id: str) -> float:
        return self.budgets.get(agent_id, self.policy.budget_for(agent_id))

    # ── per agent ────────────────────────────────────────────────────────────
    def _watch(self, agent_id: str, rt: Optional[RuntimeInfo], now: float) -> None:
        win, br = self._window(agent_id), self._breaker(agent_id)
        if rt:
            win.set_memory(rt.memory_mb, rt.memory_pct)
            br.on_runtime_status(rt.status)
        snap = win.snapshot(now, self.budget(agent_id))
        self._collect_verdict(agent_id, br, snap, now)
        if br.active:
            finding = evaluate(snap, self.cfg, strict=br.state == "probation")
            effect, ask = br.on_finding(finding, now)
            if effect:
                self._alert(agent_id, finding, critical=True)
                self._apply(agent_id, effect, snap)
            elif ask:
                self._ask_judge(agent_id, win, snap, finding, now)
        self._record(agent_id, br, snap, rt)

    def _ask_judge(self, agent_id: str, win: AgentWindow, snap: Snapshot, finding: Finding, now: float) -> None:
        if agent_id in self.pending or now - self.last_judged.get(agent_id, -1e9) < self.cfg.brain_cooldown_seconds:
            return
        self.last_judged[agent_id] = now
        log.warning("%s suspicious: %s → asking the judge", agent_id, finding.text)
        self._alert(agent_id, finding, critical=False)
        memory = (self.store.get_memory(agent_id) or {}).get("content", {})
        ctx = JudgeContext(snap, finding, win.recent_prompts(), win.recent_tools(), memory,
                           self.store.recent_verdicts(limit=3, agent_id=agent_id))
        if self.sync_judge:
            fut: Future = Future()
            fut.set_result(self.judge.judge(ctx))
            self.pending[agent_id] = fut
        else:
            self.pending[agent_id] = self.pool.submit(self.judge.judge, ctx)

    def _collect_verdict(self, agent_id: str, br: Breaker, snap: Snapshot, now: float) -> None:
        fut = self.pending.get(agent_id)
        if fut is None or not fut.done():
            return
        self.pending.pop(agent_id)
        try:
            v: Verdict = fut.result()
        except Exception as exc:  # Judge.judge already falls back; this is the last safety net
            log.error("judge crashed for %s: %s", agent_id, exc)
            return
        log.warning("Verdict %s: %s (%.0f%%, %s) — %s [%s]", agent_id, v.action, v.confidence * 100, v.pattern,
                    v.reason, v.source)
        self.store.insert_verdict(VerdictRow(agent_id, v.source, v.action, v.confidence, v.pattern, v.reason,
                                             v.suggested_fix, v.latency_ms))
        effect = br.on_verdict(v.action, v.confidence, v.source, v.reason)
        if effect:
            self._apply(agent_id, effect, snap)

    # ── actions ──────────────────────────────────────────────────────────────
    def _apply(self, agent_id: str, e: Effect, snap: Optional[Snapshot]) -> None:
        """Execute an Effect on the runtime and write the audit row."""
        saved_usd = saved_tok = 0.0
        if e.action in ("PAUSE", "KILL") and snap:
            saved_usd = round(snap.usd_per_min * self.cfg.roi_horizon_minutes, 4)
            saved_tok = int(snap.tokens_per_min * self.cfg.roi_horizon_minutes)
        if e.action == "WARN":
            self.store.insert_action(ActionRow(agent_id, "WARN", e.actor, e.reason))
            return
        result = "dry run"
        if not self.dry_run:
            fn = {"PAUSE": self.executor.pause, "KILL": self.executor.kill, "RESUME": self.executor.resume,
                  "RESTART": self.executor.restart}[e.action]
            res = fn(agent_id)
            result = res.message
            if not res.ok:
                log.error("%s %s failed: %s", e.action, agent_id, res.message)
                self.store.insert_alert(AlertRow(agent_id, "critical", "executor_failed", f"{e.action}: {res.message}"))
        if e.action in ("RESUME", "RESTART"):
            self._window(agent_id).reset_activity()
            self.pending.pop(agent_id, None)
        log.critical("%s %s by %s — %s (%s)", e.action, agent_id, e.actor, e.reason, result)
        self.store.insert_action(ActionRow(agent_id, e.action, e.actor, e.reason, saved_usd, saved_tok))

    def _alert(self, agent_id: str, f: Finding, critical: bool) -> None:
        self.store.insert_alert(AlertRow(agent_id, "critical" if critical else "warning", ",".join(f.rules), f.text))

    def _record(self, agent_id: str, br: Breaker, snap: Snapshot, rt: Optional[RuntimeInfo]) -> None:
        self.store.insert_metric(MetricRow(
            agent_id, br.state, snap.tokens_per_min, snap.usd_per_min, snap.calls_per_sec, snap.total_tokens,
            snap.spend_usd, snap.budget_usd, snap.exact_repeats, snap.loop_score, int(snap.tool_cycle),
            round(snap.memory_mb, 1), round(snap.memory_pct, 1)))
        self.store.upsert_agent(AgentRow(
            agent_id, agent_id, rt.runtime if rt else self.runtime_name, rt.runtime_id if rt else "", br.state,
            snap.budget_usd, snap.spend_usd, snap.total_tokens, self.windows[agent_id].last_seen, utc_now_iso()))

    # ── commands ─────────────────────────────────────────────────────────────
    def _run_commands(self, now: float) -> None:
        for cmd in self.store.pending_commands():
            try:
                status, result = self._run_command(cmd, now)
            except Exception as exc:
                status, result = "failed", str(exc)
            self.store.finish_command(cmd["id"], status, result)

    def _run_command(self, cmd: dict, now: float) -> tuple[str, str]:
        agent_id, command = cmd["agent_id"], cmd["command"]
        params = load_json(cmd.get("params"))
        actor = "mcp" if cmd.get("requested_by") == "mcp" else "human"
        if command == "GO_ROGUE":
            res = self.executor.go_rogue(agent_id, params.get("kind", "paraphrase_loop"))
            return ("done" if res.ok else "failed"), res.message
        if command == "SET_BUDGET":
            self.budgets[agent_id] = float(params["budget_usd"])
            self.store.insert_action(ActionRow(agent_id, "SET_BUDGET", actor,
                                               cmd.get("reason") or f"budget set to ${self.budgets[agent_id]:.2f}"))
            return "done", f"budget ${self.budgets[agent_id]:.2f}"
        if not self._known(agent_id):
            # a typo must not create a ghost agent on the dashboard
            return "failed", f"unknown agent {agent_id}"
        br = self._breaker(agent_id)
        snap = self._window(agent_id).snapshot(now, self.budget(agent_id))
        effect = br.on_command(command, actor, cmd.get("reason") or "", now)
        if effect is None:
            return "failed", f"cannot {command} an agent that is {br.state}"
        self._apply(agent_id, effect, snap)
        return "done", f"{agent_id} is now {br.state}"

    def _known(self, agent_id: str) -> bool:
        """An agent exists if we saw its spans, the runtime lists it, or the store has a row for it."""
        if agent_id in self.windows or agent_id in self.breakers:
            return True
        if any(r.agent_id == agent_id for r in (self._safe(self.executor.list_agents) or [])):
            return True
        return self.store.get_agent(agent_id) is not None

    def _expire_tool_calls(self, now: float) -> None:
        from datetime import datetime

        for call in self.store.list_tool_calls(status="pending", limit=100):
            try:
                created = datetime.fromisoformat(call["created_at"]).timestamp()
            except (TypeError, ValueError):
                continue
            if time.time() - created > self.cfg.tool_approval_timeout_seconds:
                self.store.decide_tool_call(call["id"], "timeout", {}, "timeout", "no human decision in time")
                self.store.insert_action(ActionRow(call["agent_id"], "TOOL_DENY", "policy",
                                                   f"{call['tool_name']}: approval timed out",
                                                   float(call.get("value_usd") or 0)))


__all__ = ["Engine", "json"]
