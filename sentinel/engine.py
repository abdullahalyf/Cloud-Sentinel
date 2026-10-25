"""
Engine: the main loop. Once per tick:

  1. run commands from the dashboard (Emergency Kill Switch, demo trigger)
  2. for each agent: read events + memory → snapshot → rules
       CRITICAL   → kill now (no AI, no waiting)
       SUSPICIOUS → ask Claude in a background thread (the loop keeps running)
  3. act on any Claude verdicts that came back
  4. write everything to the database for the dashboard
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace

from sentinel.brain import Brain, Verdict
from sentinel.collector import AgentState, Snapshot
from sentinel.detector import Finding, Level, evaluate
from sentinel.notifier import Notifier
from sentinel.sources import AgentHandle, AgentSource
from shared.config import Settings
from shared.contracts import ActionRow, AlertRow
from shared.store import Store

log = logging.getLogger("sentinel.engine")


class Sentinel:
    def __init__(self, source: AgentSource, store: Store, brain: Brain, cfg: Settings,
                 dry_run: bool = False, notifier: Notifier | None = None):
        self.source, self.store, self.brain, self.cfg = source, store, brain, cfg
        self.notifier = notifier or Notifier(cfg)
        self.dry_run = dry_run
        self.states: dict[str, AgentState] = {}
        self.pending: dict[str, Future] = {}
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="brain")
        self.brain_spent_usd = 0.0   # what Claude calls cost so far
        self.watched: set[str] = set()   # agent names seen this run
        self.kills = 0
        self.tokens_saved = 0
        self.saved_usd = 0.0         # estimated agent spend stopped by kills so far

    # ── main loop ────────────────────────────────────────────────────────────
    def run_forever(self) -> None:
        """Loop until Ctrl+C, then stop the worker threads and log a summary."""
        log.info("Sentinel running (tick %.1fs, dry_run=%s)", self.cfg.tick_seconds, self.dry_run)
        try:
            while True:
                started = time.time()
                try:
                    self.tick()
                except Exception:
                    log.exception("tick failed — continuing")  # the guard must never die
                time.sleep(max(0.0, self.cfg.tick_seconds - (time.time() - started)))
        except KeyboardInterrupt:
            log.info("Ctrl+C — stopping")
        finally:
            self.shutdown()
            log.info(self.summary())

    def shutdown(self) -> None:
        """Drop queued brain/webhook work; a call already running finishes in its thread."""
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.notifier.shutdown()
        if hasattr(self.source, "shutdown"):
            self.source.shutdown()

    def summary(self) -> str:
        return (f"Summary: watched {len(self.watched)} agent(s) ({', '.join(sorted(self.watched)) or '-'}), "
                f"{self.kills} kill(s), ~{self.tokens_saved:,} tokens saved "
                f"(≈${self.saved_usd:.2f}), brain spent ${self.brain_spent_usd:.4f}")

    def tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._process_commands()
        handles = self.source.list_agents()
        for h in handles:
            try:
                self._watch(h, now)
            except Exception:
                log.exception("failed to watch %s", h.name)
        alive = {h.id for h in handles}
        for gone in set(self.states) - alive:
            self.states.pop(gone, None)
            self.pending.pop(gone, None)

    def _watch(self, h: AgentHandle, now: float) -> None:
        st = self.states.get(h.id)
        if st is None:
            st = self.states[h.id] = AgentState(h.name, h.id, h.token_budget)
            self.watched.add(h.name)
            log.info("Now watching %s (budget %s tokens)", h.name, f"{h.token_budget:,}")
        if self.source.is_paused(h):
            self.store.insert_metric(st.snapshot(now).to_metric("paused"))
            return
        for event in self.source.read_events(h):
            st.add(event)
        st.set_memory(*self.source.read_memory(h))
        snap = st.snapshot(now)
        policy = self._policy(h)
        finding = evaluate(snap, policy, (e.prompt for e in st.calls))
        self.store.insert_metric(snap.to_metric("warned" if st.warned else "running"))

        if finding.level == Level.CRITICAL:
            self.store.insert_alert(AlertRow(h.name, "critical", ",".join(finding.rules),
                                             "; ".join(finding.reasons)))
            self.kill(h, actor="rules", reason="Hard limit: " + "; ".join(finding.reasons), snap=snap)
            return

        if self._collect_verdict(h, st, snap):
            return  # killed: don't ask the brain about a dead agent
        if finding.level == Level.SUSPICIOUS:
            self._ask_brain(h, st, snap, finding, now, policy)

    def _policy(self, h: AgentHandle) -> Settings:
        """Global settings, with this agent's label overrides (e.g. its own token limits)."""
        overrides = {k: v for k in ("soft_tokens_per_min", "hard_tokens_per_min")
                     if (v := getattr(h, k)) is not None}
        return replace(self.cfg, **overrides) if overrides else self.cfg

    # ── brain ────────────────────────────────────────────────────────────────
    def _ask_brain(self, h: AgentHandle, st: AgentState, snap: Snapshot, finding: Finding, now: float,
                   policy: Settings | None = None) -> None:
        new_evidence = not set(finding.rules) <= st.last_brain_rules  # a new rule skips the cooldown
        if h.id in self.pending or (now - st.last_brain_check < self.cfg.brain_cooldown_seconds
                                    and not new_evidence):
            return
        st.last_brain_check, st.last_brain_rules = now, frozenset(finding.rules)
        log.warning("%s looks suspicious: %s → asking the brain", h.name, "; ".join(finding.reasons))
        self.store.insert_alert(AlertRow(h.name, "warning", ",".join(finding.rules), "; ".join(finding.reasons)))
        self.pending[h.id] = self.pool.submit(self.brain.judge, snap, finding, st.recent_events(12),
                                              policy or self.cfg)

    def _collect_verdict(self, h: AgentHandle, st: AgentState, snap: Snapshot) -> bool:
        """Act on a finished brain verdict. True if the agent was killed."""
        fut = self.pending.get(h.id)
        if fut is None or not fut.done():
            return False
        self.pending.pop(h.id)
        v: Verdict = fut.result()
        log.warning("Brain verdict for %s: %s (%.0f%%, %s) — %s [%s]",
                    h.name, v.action, v.confidence * 100, v.pattern, v.reason, v.source)
        severity = {"KILL": "critical", "WARN": "warning"}.get(v.action, "info")
        self.store.insert_alert(AlertRow(
            h.name, severity, f"{v.source}_verdict",
            f"{v.action} ({v.confidence:.0%}, {v.pattern}): {v.reason}"))
        if v.tokens_in or v.tokens_out:
            self.brain_spent_usd += v.cost_usd
            self._report_cost(h.name, f"claude call {v.tokens_in:,} in + {v.tokens_out:,} out tokens "
                                      f"= ${v.cost_usd:.6f} ({self.cfg.claude_model})")
        if v.action == "KILL" and v.confidence >= self.cfg.brain_kill_confidence:
            return self.kill(h, actor=v.source, reason=v.reason, snap=snap)
        if v.action in ("WARN", "KILL") and not st.warned:
            st.warned = True
            self.store.insert_action(ActionRow(h.name, "WARN", v.source, v.reason))
        return False

    # ── actions ──────────────────────────────────────────────────────────────
    def kill(self, h: AgentHandle, actor: str, reason: str, snap: Snapshot | None = None) -> bool:
        if snap is None and h.id in self.states:
            snap = self.states[h.id].snapshot()
        if self.dry_run:
            log.warning("[DRY RUN] would kill %s — %s", h.name, reason)
            self.store.insert_alert(AlertRow(h.name, "info", "dry_run", f"Would kill ({actor}): {reason}"))
            return False
        try:
            result = self.source.kill(h)
        except Exception as exc:
            log.error("KILL FAILED for %s: %s", h.name, exc)
            self.store.insert_alert(AlertRow(h.name, "critical", "kill_failed", str(exc)))
            return False
        # rough estimate: what one more hour at the current rate would have cost
        saved = snap.tokens_per_min * 60 if snap else 0
        log.critical("☠ KILLED %s by %s — %s (%s)", h.name, actor, reason, result)
        self.store.insert_action(ActionRow(h.name, "KILL", actor, reason, saved))
        self.notifier.notify(h.name, "KILL", actor, reason)
        self.kills += 1
        self.tokens_saved += saved
        self.saved_usd += saved * self.cfg.agent_price_per_mtok / 1_000_000
        self._report_cost(h.name, f"kill saved ~{saved:,} tokens")
        if snap:
            self.store.insert_metric(snap.to_metric("killed"))
        self.states.pop(h.id, None)
        self.pending.pop(h.id, None)
        self.brain.forget(h.name)
        return True

    def _report_cost(self, agent: str, detail: str) -> None:
        """Running totals for the dashboard: latest alert with rule 'brain_cost'."""
        self.store.insert_alert(AlertRow(
            agent, "info", "brain_cost",
            f"Sentinel spent ${self.brain_spent_usd:.4f} to save ${self.saved_usd:.2f} — {detail} "
            f"[spent_usd={self.brain_spent_usd:.6f} saved_usd={self.saved_usd:.4f}]"))

    def _process_commands(self) -> None:
        commands = self.store.pending_commands()
        if not commands:
            return
        by_name = {h.name: h for h in self.source.list_agents()}
        for cmd in commands:
            h = by_name.get(cmd["agent"])
            if h is None:
                self.store.finish_command(cmd["id"], "failed", "agent not found or already dead")
                continue
            try:
                if cmd["command"] == "KILL":
                    ok = self.kill(h, actor="human", reason=cmd.get("reason") or "Emergency kill switch")
                    self.store.finish_command(cmd["id"], "done" if ok else "failed",
                                              "killed" if ok else "not killed (dry run or error)")
                elif cmd["command"] in ("PAUSE", "RESUME"):
                    if self.dry_run:
                        self.store.finish_command(cmd["id"], "failed", "not changed (dry run)")
                        continue
                    if cmd["command"] == "PAUSE":
                        result = self.source.pause(h)
                        pending = self.pending.pop(h.id, None)
                        if pending is not None:
                            pending.cancel()  # discard even a verdict already running
                        self.store.insert_action(ActionRow(
                            h.name, "PAUSE", "human", cmd.get("reason") or "Quarantine"))
                        self.notifier.notify(h.name, "PAUSE", "human", cmd.get("reason") or "Quarantine")
                    else:
                        result = self.source.resume(h)
                    self.store.finish_command(cmd["id"], "done", result)
                elif cmd["command"] == "GO_ROGUE":
                    if self.source.is_paused(h):
                        raise ValueError("agent is paused; resume before switching to rogue mode")
                    self.store.finish_command(cmd["id"], "done", self.source.go_rogue(h))
                else:
                    self.store.finish_command(cmd["id"], "failed", f"unknown command {cmd['command']}")
            except Exception as exc:
                self.store.finish_command(cmd["id"], "failed", str(exc))
