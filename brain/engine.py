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

from brain.baseline import AgentBaseline
from brain.breaker import Breaker, Effect
from brain.detectors import Finding, evaluate
from brain.heal import PatchRejected, decide as decide_heal, may_autoheal, propose as propose_heal, validate
from brain.judge import Judge, JudgeContext, Verdict
from brain.policy import Policy
from brain.policy_reload import PolicyManager
from brain.sharding import Shard
from brain.state import AgentWindow, Snapshot
from shared.config import Settings
from shared.contracts import (ActionRow, AgentRow, AlertRow, Executor, MetricRow, RuntimeInfo, VerdictRow,
                              load_json, utc_now_iso)

log = logging.getLogger("brain.engine")


class Engine:
    def __init__(self, store, executor: Executor, judge: Judge, policy: Policy, cfg: Settings,
                 dry_run: bool = False, sync_judge: bool = False, runtime_name: str = "fake",
                 policy_path: str = "", shard: Optional[Shard] = None):
        self.store, self.executor, self.judge, self.policy, self.cfg = store, executor, judge, policy, cfg
        self.dry_run, self.sync_judge, self.runtime_name = dry_run, sync_judge, runtime_name
        self.windows: dict[str, AgentWindow] = {}
        self.breakers: dict[str, Breaker] = {}
        self.budgets: dict[str, float] = {}
        self.last_judged: dict[str, float] = {}
        self.last_rules: dict[str, set] = {}   # rules the judge saw last time, per agent
        self.pending: dict[str, Future] = {}
        self.last_autoheal: dict[str, float] = {}   # agent → when we last auto-healed it
        self.last_finding: dict[str, Finding] = {}  # agent → the finding the judge last saw
        self.cursor = 0
        self.runtime_ids: Optional[set] = None
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="judge")
        # A5: the policy manager watches the policy file and swaps the policy in when it changes.
        self.policy_manager = PolicyManager(policy, policy_path or cfg.policy_file, store=store,
                                            default_budget=cfg.default_budget_usd)
        self.policy = self.policy_manager.policy
        # A4: per-agent baselines. Loaded from the store, so a restart keeps them.
        self.baselines: dict[str, AgentBaseline] = {}
        self.first_seen: dict[str, float] = {}   # agent → when we first saw it (the warmup clock)
        self._load_baselines()
        # A8: this worker's share of the fleet. Without a shard the engine owns everything
        # (the single-process default), so nothing else changes for the ordinary case.
        self.shard = shard
        self.owned: Optional[set[str]] = None   # None = "everything" (no shard)

    def owns(self, agent_id: str) -> bool:
        """Does this worker act on this agent?

        With no shard, yes — the engine watches the whole fleet. With a shard, only the
        agents this worker owns. Two workers acting on one agent would pause it twice and
        count every metric twice.
        """
        if self.owned is None:
            return True
        return agent_id in self.owned

    def _load_baselines(self) -> None:
        """Restore what the store kept: a brain restart must not forget what an agent is like."""
        try:
            rows = self.store.list_agents()
        except Exception:
            log.exception("could not read the agents table — starting without baselines")
            return
        for row in rows or []:
            agent_id = str(row.get("agent_id") or "")
            if not agent_id:
                continue
            baseline = AgentBaseline.from_json(agent_id, row.get("baseline"))
            if baseline.metrics:
                self.baselines[agent_id] = baseline
                log.info("restored the baseline of %s", agent_id)

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
        self._safe(self._reload_policy, now)
        self._safe(self._run_commands, now)
        self._safe(self._ingest)
        listed = self._safe(self.executor.list_agents)
        runtime = {r.agent_id: r for r in (listed or [])}
        self.runtime_ids = set(runtime) if listed is not None else None   # None = runtime unknown this tick
        self._safe(self._reshard, now)
        for agent_id in sorted(set(self.windows) | set(runtime)):
            if not self.owns(agent_id):
                continue   # somebody else's agent — do not touch it
            self._safe(self._watch, agent_id, runtime.get(agent_id), now)
        self._safe(self._expire_tool_calls, now)

    def _reshard(self, now: float) -> None:
        """
        Work out which agents are ours (A8).

        The heartbeat comes first: the other workers can only see us if we say we are alive,
        and a worker that just started has to be seen before it can own anything.
        """
        if self.shard is None:
            return
        if self.shard.needs_heartbeat(now):
            self.shard.heartbeat(now)
        agent_ids = set(self.windows) | set(self.runtime_ids or set())
        self.owned = self.shard.owned_agents(agent_ids, now)

    def _reload_policy(self, now: float) -> None:
        """
        Pick up a changed policy file (A5).

        The check is the file's mtime — cheap enough to do every tick. A valid file is swapped
        in atomically; an invalid one is rejected and the last good policy stays in force.
        """
        if not self.cfg.policy_reload_enabled:
            return
        if now - self.policy_manager.last_checked < self.cfg.policy_reload_interval_seconds:
            return
        self.policy_manager.last_checked = now
        result = self.policy_manager.check(now)
        if result.loaded:
            self.policy = self.policy_manager.policy
            # the breakers read on_trip / on_hard_limit when they act, so a changed policy
            # applies to the very next trip — not only to agents seen after the reload
            for br in self.breakers.values():
                br.on_trip = self.policy.on_trip
                br.on_hard_limit = self.policy.on_hard_limit

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
            was_probation = br.state == "probation"
            # A4: the agent's own normal, once it has one. During the warmup there is none,
            # and the fixed soft limits apply.
            baseline = self._baseline_for(agent_id, now)
            finding = evaluate(snap, self.cfg, strict=was_probation, baseline=baseline)
            effect, ask = br.on_finding(finding, now)
            if effect:
                self._alert(agent_id, finding, critical=True)
                # An agent that trips again while on probation after an auto-heal is NOT healed
                # again: the first patch did not work, so a human has to look. The breaker pauses
                # instead of killing (br.pause_on_trip) so the state survives for that human.
                if agent_id in self.last_autoheal and was_probation:
                    self._escalate(agent_id, finding)
                self._apply(agent_id, effect, snap)
            elif ask:
                self._ask_judge(agent_id, win, snap, finding, now)
        self._learn(agent_id, br, snap, now)
        self._record(agent_id, br, snap, rt)

    # ── baselines (A4) ───────────────────────────────────────────────────────
    def _baseline_for(self, agent_id: str, now: float) -> Optional[AgentBaseline]:
        """The agent's baseline, or None while it is still warming up."""
        if not self.cfg.baseline_enabled:
            return None
        self.first_seen.setdefault(agent_id, now)
        if now - self.first_seen[agent_id] < self.cfg.baseline_warmup_seconds:
            return None
        return self.baselines.get(agent_id)

    def _learn(self, agent_id: str, br: Breaker, snap: Snapshot, now: float) -> None:
        """
        Learn what "normal" means for this agent — from its HEALTHY windows only.

        A suspicious, paused, probation or killed agent is not normal, so learning from it
        would teach the brain that a runaway is the new normal. The learned limits are kept
        in the store (agents.baseline) so a restart does not forget them.
        """
        if not self.cfg.baseline_enabled or br.state != "healthy":
            return
        baseline = self.baselines.setdefault(agent_id, AgentBaseline(agent_id=agent_id))
        baseline.observe(now, {"tokens_per_min": snap.tokens_per_min, "usd_per_min": snap.usd_per_min,
                               "calls_per_sec": snap.calls_per_sec})
        baseline.recompute(self.cfg)

    def _escalate(self, agent_id: str, finding: Finding) -> None:
        """An agent that tripped again after an auto-heal needs a human: file a proposal."""
        memory_row = self.store.get_memory(agent_id) or {}
        memory = memory_row.get("content") or {}
        try:
            patch = validate({"memory": [{"op": "set", "key": key, "value": "needs a human - "
                                          "the auto-heal did not work"} for key in memory][:5]},
                             memory, finding)
        except PatchRejected as exc:
            log.warning("could not build an escalation patch for %s: %s", agent_id, exc)
            return
        propose_heal(self.store, agent_id, patch, 0.0, 0, int(memory_row.get("version") or 0),
                     reason="the agent tripped again after an auto-heal — a human must look at it")

    def _ask_judge(self, agent_id: str, win: AgentWindow, snap: Snapshot, finding: Finding, now: float) -> None:
        if agent_id in self.pending:
            return
        # new evidence (a rule the judge hasn't seen yet, e.g. loop_semantic after a token_spike WARN) skips the cooldown
        new_evidence = bool(set(finding.rules) - self.last_rules.get(agent_id, set()))
        if not new_evidence and now - self.last_judged.get(agent_id, -1e9) < self.cfg.brain_cooldown_seconds:
            return
        self.last_judged[agent_id], self.last_rules[agent_id] = now, set(finding.rules)
        self.last_finding[agent_id] = finding
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
        verdict_id = self.store.insert_verdict(VerdictRow(agent_id, v.source, v.action, v.confidence, v.pattern,
                                                          v.reason, v.suggested_fix, v.latency_ms))
        effect = br.on_verdict(v.action, v.confidence, v.source, v.reason)
        if effect:
            self._apply(agent_id, effect, snap)
        if v.patch and effect and effect.action in ("PAUSE", "KILL"):
            self._heal(agent_id, br, v, verdict_id, now)
        elif v.patch and effect and effect.action == "WARN":
            # the judge was not confident enough to stop the agent, but it still has an idea:
            # file it as a proposal so a human can look at it. Nothing is changed.
            self._propose_only(agent_id, v, verdict_id)

    # ── auto-heal ────────────────────────────────────────────────────────────
    def _propose_only(self, agent_id: str, v: Verdict, verdict_id: int) -> None:
        """File the judge's patch as a proposal without changing anything."""
        memory_row = self.store.get_memory(agent_id) or {}
        memory = memory_row.get("content") or {}
        finding = self.last_finding.get(agent_id)
        try:
            patch = validate(v.patch, memory, finding)
        except PatchRejected as exc:
            log.warning("the judge proposed an unsafe patch for %s: %s", agent_id, exc)
            return
        propose_heal(self.store, agent_id, patch, v.confidence, verdict_id,
                     int(memory_row.get("version") or 0),
                     reason=v.reason or "the judge is not confident enough to apply this without a human")

    def _heal(self, agent_id: str, br: Breaker, v: Verdict, verdict_id: int, now: float) -> None:
        """
        A paused agent may carry a patch that fixes it: the belief that keeps it looping, or the
        tool that keeps failing.

        A confident, valid patch is applied right away and the agent goes back to work on probation.
        Anything less — a low confidence, an invalid patch, a recent auto-heal — becomes a proposal
        for a human. The agent stays paused either way: a human (or the next auto-heal) resumes it.
        """
        memory_row = self.store.get_memory(agent_id) or {}
        memory = memory_row.get("content") or {}
        finding = self.last_finding.get(agent_id)
        try:
            patch = validate(v.patch, memory, finding)
        except PatchRejected as exc:
            log.warning("the judge proposed an unsafe patch for %s: %s", agent_id, exc)
            return

        base_version = int(memory_row.get("version") or 0)
        if not may_autoheal(self.cfg, agent_id, self.last_autoheal, now):
            # either auto-heal is off, or we healed this agent very recently: ask a human instead
            propose_heal(self.store, agent_id, patch, v.confidence, verdict_id, base_version,
                         reason=v.reason or "auto-heal needs a human")
            return
        if v.confidence < self.cfg.autoheal_min_confidence:
            propose_heal(self.store, agent_id, patch, v.confidence, verdict_id, base_version,
                         reason=v.reason or "not confident enough to apply without a human")
            return

        # confident and valid: apply it
        try:
            from brain.heal import apply_to_memory

            content = apply_to_memory(memory, patch)
            # base_version = the version we read: if the memory moved on while the judge was
            # thinking, the write is refused and the patch becomes a proposal instead.
            self.store.write_memory(agent_id, content, "brain:autoheal",
                                    reason=f"auto-heal: {v.reason or 'patch applied'}", base_version=base_version)
        except Exception as exc:
            log.error("could not apply the auto-heal for %s: %s", agent_id, exc)
            propose_heal(self.store, agent_id, patch, v.confidence, verdict_id, base_version,
                         reason=f"the patch could not be written: {exc}")
            return
        self.last_autoheal[agent_id] = now
        self.store.insert_action(ActionRow(agent_id, "AUTO_HEAL", "brain:autoheal",
                                           f"auto-heal: {v.reason or 'patch applied'}"))
        # a second trip from now on pauses instead of killing — the patch gets one chance
        br.pause_on_trip = True
        log.warning("auto-healed %s: %s", agent_id, patch.to_json())
        # the agent is paused and healthy again: put it back to work on probation
        resume = br.on_command("RESUME", "brain:autoheal", f"auto-heal: {v.reason or 'patch applied'}", now)
        if resume:
            self._apply(agent_id, resume, None)

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
        no_container = self.runtime_ids is not None and agent_id not in self.runtime_ids
        if no_container and not self.dry_run:
            # e.g. a LangGraph/CrewAI process or any external OTel agent: the SDK enforces the state
            # (tool gate denies everything, wait_if_paused() blocks between nodes / LLM calls)
            result = "no container: enforced by the SDK (tool gate + pause check)"
        elif not self.dry_run:
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
            self.last_rules.pop(agent_id, None)
        log.critical("%s %s by %s — %s (%s)", e.action, agent_id, e.actor, e.reason, result)
        self.store.insert_action(ActionRow(agent_id, e.action, e.actor, e.reason, saved_usd, saved_tok))

    def _alert(self, agent_id: str, f: Finding, critical: bool) -> None:
        self.store.insert_alert(AlertRow(agent_id, "critical" if critical else "warning", ",".join(f.rules), f.text))

    def _record(self, agent_id: str, br: Breaker, snap: Snapshot, rt: Optional[RuntimeInfo]) -> None:
        self.store.insert_metric(MetricRow(
            agent_id, br.state, snap.tokens_per_min, snap.usd_per_min, snap.calls_per_sec, snap.total_tokens,
            snap.spend_usd, snap.budget_usd, snap.exact_repeats, snap.loop_score, int(snap.tool_cycle),
            round(snap.memory_mb, 1), round(snap.memory_pct, 1)))
        # A4: the learned baseline goes in the same row, so one write keeps both. An empty
        # baseline means "nothing learned yet" and leaves the stored one alone.
        baseline = self.baselines.get(agent_id)
        payload = baseline.to_dict() if baseline else {}
        self.store.upsert_agent(AgentRow(
            agent_id, agent_id, rt.runtime if rt else self.runtime_name, rt.runtime_id if rt else "", br.state,
            snap.budget_usd, snap.spend_usd, snap.total_tokens, self.windows[agent_id].last_seen,
            baseline=payload, updated_at=utc_now_iso()))

    # ── commands ─────────────────────────────────────────────────────────────
    def _run_commands(self, now: float) -> None:
        for cmd in self.store.pending_commands():
            # A8: only the worker that owns the agent runs its commands. If two workers ran
            # the same command, the agent would be paused twice and the action counted twice.
            if not self.owns(str(cmd.get("agent_id") or "")):
                continue
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
