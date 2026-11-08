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
from brain.budget import Ladder, effect_for, throttle_ratio
from brain.breaker import Breaker, Effect
from brain.detectors import Finding, evaluate
from brain.heal import PatchRejected, decide as decide_heal, may_autoheal, propose as propose_heal, validate
from brain.judge import Judge, JudgeContext, Verdict
from brain.judge_spend import CAPPED_ALERT_RULE
from brain.policy import Policy
from brain.policy_reload import PolicyManager
from brain.sharding import Shard
from brain.state import AgentWindow, Snapshot
from brain import verdict_span
from brain.write_batch import WriteBatch
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
        self._capped_alerted: set[str] = set()      # agents we already told about the cap (A12)
        # B6: the cascades we already contained. The call graph still holds the
        # old edges after the agents are paused, so without this the same chain
        # would be found and written again on every tick.
        self._contained_cascades: set[str] = set()
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
        # A11: the tick's writes, held until the tick is over so they cost one commit
        # instead of two per agent.
        self.batch = WriteBatch(store)
        # A15: the emitter that puts the verdict on the agent's own OTel trace. It is
        # off unless something configured an endpoint, and it never raises into the tick.
        self.verdict_emitter = verdict_span.emitter()

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
            # The tick's own duration, every tick. The brain has to stay inside its tick
            # budget: a tick that runs longer than the interval means the loop falls
            # behind, and the fleet is observed less and less often.
            log.info("tick took %.0f ms", (time.time() - started) * 1000)
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
        # B6: the cascade. It runs **after** the per-agent watch, because a chain
        # is only a chain once every agent in it has been looked at. And it is
        # separate from the per-agent watch on purpose: the agents in a chain are
        # handled together, not one at a time.
        self._safe(self._contain_cascades, now)
        self._safe(self._expire_tool_calls, now)
        # A11: the metric and agent rows for every agent are written in one transaction.
        # The flush is last so that everything the tick observed is in the batch.
        self._safe(self.batch.flush)

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
            # B4: the degradation ladder, one per agent. It is off unless the flag says so,
            # and off means the breaker behaves exactly as it always did.
            ladder = Ladder(agent_id, enabled=self.cfg.degradation_enabled)
            self.breakers[agent_id] = Breaker(agent_id, self.cfg.probation_seconds, self.cfg.brain_kill_confidence,
                                              self.policy.on_trip, self.policy.on_hard_limit, ladder=ladder)
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
                self._emit_rule_verdict(agent_id, finding, snap, effect)
                # An agent that trips again while on probation after an auto-heal is NOT healed
                # again: the first patch did not work, so a human has to look. The breaker pauses
                # instead of killing (br.pause_on_trip) so the state survives for that human.
                if agent_id in self.last_autoheal and was_probation:
                    self._escalate(agent_id, finding)
                # B4: a rung of the degradation ladder is not a container operation — it is a
                # change to how the agent is allowed to run — so it goes through the ladder,
                # which records whether the rung took effect.
                if effect.action in ("THROTTLE", "DOWNGRADE"):
                    self._step_down(agent_id, effect, snap)
                else:
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
        self._emit_verdict(agent_id, v.action, v.source, v.confidence, v.reason, snap)
        effect = br.on_verdict(v.action, v.confidence, v.source, v.reason)
        if effect:
            # B4: the same ladder the rules walk — a judge verdict that says PAUSE steps the
            # agent down one rung first when the ladder is on.
            if effect.action in ("THROTTLE", "DOWNGRADE"):
                self._step_down(agent_id, effect, snap)
            else:
                self._apply(agent_id, effect, snap)
        if v.patch and effect and effect.action in ("PAUSE", "KILL"):
            self._heal(agent_id, br, v, verdict_id, now)
        elif v.patch and effect and effect.action == "WARN":
            # the judge was not confident enough to stop the agent, but it still has an idea:
            # file it as a proposal so a human can look at it. Nothing is changed.
            self._propose_only(agent_id, v, verdict_id)
        if v.source == "fallback" and self._capped_now():
            self._alert_capped(agent_id)

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

        When `CS_VERIFIED_HEAL` is on, the patch must also *prove* itself first: the agent's
        recent context is replayed against it in a shadow dry-run, and the patch is applied only
        if the patched agent would be healthy. A shadow can only veto — it never authorises.
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

        # B1: the shadow dry-run. It runs before the patch touches the agent, on copies only.
        # With the flag off it is not run at all and every patch waits for a human — the A3
        # behaviour, exactly.
        decision = self._shadow_decide(agent_id, patch, memory, v, verdict_id, base_version, now)
        if not decision.apply:
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

    # ── the shadow dry-run (B1) ──────────────────────────────────────────────
    def _shadow_decide(self, agent_id: str, patch, memory: dict, v: Verdict,
                       verdict_id: int, base_version: int, now: float):
        """
        Ask the shadow whether the patch works, before it touches the agent.

        The decision is a `verified_heal.HealDecision`: apply, or a human. Either way the whole
        flow — the shadow's verdict, the numbers behind it — goes onto the agent's own trace,
        so a reader can see the proof and the decision side by side.
        """
        from brain import verified_heal

        win = self.windows.get(agent_id)
        prompts = [str(c.get("prompt_preview") or "") for c in list(win.chats) if win is not None] \
            if win is not None else []
        snap = win.snapshot(now, self.budget(agent_id)) if win is not None else None

        decision = verified_heal.decide(
            patch, memory, prompts, snap, self.cfg,
            confidence=v.confidence, finding=self.last_finding.get(agent_id),
            baseline=self.baselines.get(agent_id),
        )

        if decision.shadow is not None:
            self._emit_shadow(agent_id, decision.shadow, v.confidence, decision.apply, decision.reason)

        if not decision.apply:
            # the patch waits for a human. The reason says why — the shadow's own words.
            reason = decision.reason or v.reason or "the patch did not prove itself"
            log.warning("the patch for %s waits for a human: %s", agent_id, reason)
            propose_heal(self.store, agent_id, patch, v.confidence, verdict_id, base_version, reason=reason)
        return decision

    def _emit_shadow(self, agent_id: str, shadow, confidence: float, applied: bool, reason: str) -> None:
        """Put the shadow flow on the agent's own trace, next to the behaviour that caused it.

        Best-effort by construction: a lost span is a nuisance, a lost tick is an outage.
        """
        sender = getattr(self, "verdict_emitter", None)
        if sender is None:
            return
        try:
            from brain import verified_heal

            win = self.windows.get(agent_id)
            spans = list(win.chats) + list(win.tools) if win is not None else []
            trace_id, span_id = verdict_span.trace_of(spans)
            verified_heal.emit_shadow_span(sender, agent_id=agent_id, trace_id=trace_id,
                                            parent_span_id=span_id, shadow=shadow,
                                            confidence=confidence, applied=applied, reason=reason)
        except Exception as exc:
            log.warning("could not put the shadow flow for %s on the agent's trace: %s", agent_id, exc)


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
            # The runtime can fail in two ways: it can *say* it failed, or it can throw.
            # A throw is the worse one — the Docker daemon is gone, the k8s API is down —
            # and it must not take the tick with it. A failed pause that nobody hears
            # about is the worst outcome of all: the brain believes the agent is stopped,
            # and it is running.
            try:
                res = fn(agent_id)
            except Exception as exc:
                result = f"{type(exc).__name__}: {exc}"
                log.exception("%s %s raised", e.action, agent_id)
                self.store.insert_alert(AlertRow(agent_id, "critical", "executor_failed",
                                                 f"{e.action} raised: {result}"))
            else:
                result = res.message
                if not res.ok:
                    log.error("%s %s failed: %s", e.action, agent_id, res.message)
                    self.store.insert_alert(AlertRow(agent_id, "critical", "executor_failed",
                                                     f"{e.action}: {res.message}"))
        if e.action in ("RESUME", "RESTART"):
            self._window(agent_id).reset_activity()
            self.pending.pop(agent_id, None)
            self.last_rules.pop(agent_id, None)
        log.critical("%s %s by %s — %s (%s)", e.action, agent_id, e.actor, e.reason, result)
        self.store.insert_action(ActionRow(agent_id, e.action, e.actor, e.reason, saved_usd, saved_tok))

    # ── the degradation ladder (B4) ──────────────────────────────────────────
    def _step_down(self, agent_id: str, e: Effect, snap: Optional[Snapshot]) -> None:
        """
        Walk one rung of the degradation ladder.

        The rung is written to the audit log like any other action, and then
        the ladder is told whether it **worked**. A rung that did not take
        effect does *not* advance the ladder: the agent is still running at
        full speed, and a brain that believed it had been throttled would be
        lying to the operator and to itself.
        """
        ladder = self._breaker(agent_id).ladder
        reason, detail = effect_for(e.action, e.reason)
        ok, detail = self._apply_rung(agent_id, e.action, detail)
        if ok:
            ladder.stepped(e.action)
            log.warning("%s: %s took effect — the ladder now stands at %s",
                        agent_id, e.action, ladder.next_step() or "the end")
        else:
            ladder.step_failed(e.action, detail)
            self.store.insert_alert(AlertRow(agent_id, "critical", "degradation_failed",
                                             f"{e.action} did not take effect: {detail}"))
        # The audit row is written by _apply_rung (it carries the rung's own reason).
        del reason

    def _apply_rung(self, agent_id: str, rung: str, reason: str) -> tuple[bool, str]:
        """
        Apply one rung and report whether it **worked**.

        A throttle or a downgrade is not a container operation — it is a change
        to how the agent is allowed to run. There is no Docker call for it, so
        the brain records it and the SDK/runtime honours it. In a dry run, or
        for an agent with no container, the rung counts as applied: there is
        nothing to fail.
        """
        br = self._breaker(agent_id)
        if rung == "THROTTLE":
            ratio = throttle_ratio(br.ladder.applied)
            detail = f"throttled to {ratio:.0%} of its rate"
        elif rung == "DOWNGRADE":
            detail = "moved to a cheaper model"
        else:  # pragma: no cover — the ladder only produces the two rungs here
            detail = rung

        if self.dry_run:
            ok, message = True, f"dry run: {detail}"
        else:
            ok, message = True, detail
        self.store.insert_action(ActionRow(agent_id, rung, "rules", reason))
        return ok, message

    def _alert(self, agent_id: str, f: Finding, critical: bool) -> None:
        self.store.insert_alert(AlertRow(agent_id, "critical" if critical else "warning", ",".join(f.rules), f.text))

    # ── the verdict on the agent's trace (A15) ────────────────────────────────
    def _emit_verdict(self, agent_id: str, action: str, source: str, confidence: float,
                      reason: str, snap: Snapshot) -> None:
        """Put the judge's verdict on the agent's own OpenTelemetry trace.

        The verdict lives in CloudSentinel's tables; the behaviour that caused it lives
        on the agent's trace, in Phoenix. A15 puts the two on the same trace, so the
        person looking at the agent sees *why* it was stopped next to *what it did*.

        This is best-effort by construction: the emitter swallows every failure, so a
        collector that is down cannot take the tick with it.
        """
        self._emit_span(agent_id, action, source, confidence, reason, snap)

    def _emit_rule_verdict(self, agent_id: str, f: Finding, snap: Snapshot, effect: Effect) -> None:
        """The same, for a verdict the *rules* reached without asking the judge.

        A hard limit tripping is a decision too, and it is the one an operator is most
        likely to want explained on the trace.

        The confidence is 1.0 because a rule that broke a hard limit did not *guess* —
        it measured. The judge, on the other hand, is asked how sure it is.
        """
        self._emit_span(agent_id, effect.action, effect.actor or "rules", 1.0, f.text, snap)

    def _emit_span(self, agent_id: str, action: str, source: str, confidence: float,
                   reason: str, snap: Snapshot) -> None:
        """Find the agent's trace and send the verdict onto it."""
        sender = getattr(self, "verdict_emitter", None)
        if sender is None:
            return
        try:
            win = self.windows.get(agent_id)
            spans = list(win.chats) + list(win.tools) if win is not None else []
            trace_id, span_id = verdict_span.trace_of(spans)
            verdict_span.emit(sender, agent_id=agent_id, trace_id=trace_id, parent_span_id=span_id,
                              action=action, source=source, confidence=confidence, reason=reason,
                              loop_score=snap.loop_score, exact_repeats=snap.exact_repeats)
        except Exception as exc:
            # The emitter already swallows its own failures; this is the belt to that
            # braces. A tick must not die because a verdict could not be exported.
            log.warning("could not put the verdict for %s on the agent's trace: %s", agent_id, exc)

    # ── the judge's spend cap (A12) ──────────────────────────────────────────
    def _capped_now(self) -> bool:
        """True when the LLM judge is over its hourly cap."""
        spend = getattr(self.judge, "spend", None)
        return bool(spend is not None and spend.capped())

    def _alert_capped(self, agent_id: str) -> None:
        """Tell the operator that the LLM judge is off because of the spend cap.

        The alert is written once per agent, not once per verdict: a fleet of forty
        agents asking the judge every minute would otherwise bury the dashboard under
        the same line forty times a minute.
        """
        if agent_id in self._capped_alerted:
            return
        self._capped_alerted.add(agent_id)
        spend = self.judge.spend
        message = (f"The LLM judge is over its hourly cap (${self.cfg.judge_max_usd_per_hour:.2f}); "
                   f"the deterministic judge is deciding instead. Spent ${spend.spend():.4f} in the last hour.")
        log.warning("%s — %s", agent_id, message)
        self.store.insert_alert(AlertRow(agent_id, "warning", CAPPED_ALERT_RULE, message))

    def _record(self, agent_id: str, br: Breaker, snap: Snapshot, rt: Optional[RuntimeInfo]) -> None:
        # A11: both rows go into the tick's batch instead of straight to the store, so
        # the whole tick costs one commit instead of two per agent.
        self.batch.metric(MetricRow(
            agent_id, br.state, snap.tokens_per_min, snap.usd_per_min, snap.calls_per_sec, snap.total_tokens,
            snap.spend_usd, snap.budget_usd, snap.exact_repeats, snap.loop_score, int(snap.tool_cycle),
            round(snap.memory_mb, 1), round(snap.memory_pct, 1)))
        # A4: the learned baseline goes in the same row, so one write keeps both. An empty
        # baseline means "nothing learned yet" and leaves the stored one alone.
        baseline = self.baselines.get(agent_id)
        payload = baseline.to_dict() if baseline else {}
        self.batch.agent(AgentRow(
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

    # ── the cascade (B6) ─────────────────────────────────────────────────────
    def _contain_cascades(self, now: float) -> None:
        """
        Contain the chains where the agents keep each other running.

        The brain watches every agent on its own, and that is right for one
        runaway. But a **cascade** is a different thing: the agents in the chain
        hold each other up, so stopping one of them only moves the problem. So
        the chain is the unit here — every agent in it is paused **together**, in
        this tick.

        With the flag off this does nothing at all: every agent is handled on
        its own, exactly as before.
        """
        if not self.cfg.cascade_enabled:
            return
        from brain import cascade as brain_cascade

        try:
            spans = self.store.recent_spans(minutes=self.cfg.cascade_window_minutes) or []
        except Exception:
            log.exception("could not read the spans for the cascade")
            return
        try:
            cascades = brain_cascade.detect_cascades(spans, self.cfg)
        except Exception:
            log.exception("could not detect the cascades")
            return

        for cascade in cascades:
            # A chain we have already contained is not contained again — the
            # agents are paused and the graph still holds the old edges, so
            # every tick would find the same chain and write it again.
            cascade_id = str(cascade.get("cascade_id") or "")
            if not cascade_id or cascade_id in self._contained_cascades:
                continue
            contained = brain_cascade.contain(cascade, self, self.cfg, now)
            if not contained:
                # Nothing could be stopped. The chain stays on the list, so the
                # next tick tries again — but it is not written to the store as
                # a containment, because nothing was contained.
                continue
            self._contained_cascades.add(cascade_id)
            cascade["detected_at"] = now
            brain_cascade.record_cascade(self, cascade)
            log.warning("cascade %s contained: %s", cascade_id, ", ".join(contained))

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
