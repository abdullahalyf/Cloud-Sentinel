"""
Policy backtesting (CONTRACTS §6, B5): what would the candidate policy have caught?

"Would the new policy have caught it?" is the question an operator asks before shipping a
policy change. The only honest way to answer it is to **replay what actually happened**
against the candidate policy and count.

How the replay works:

  1. the stored spans are walked again, in time order, per agent;
  2. each span goes into the same `AgentWindow` the live brain uses, and each
     step is judged with `evaluate()` — but with the **candidate** policy's
     budgets and limits;
  3. every rule the candidate fires is compared with what the running policy
     actually recorded: the alerts (something was noticed) and the actions
     (something was stopped).

Then each finding is one of three things:

  **catch**         — the candidate would have stopped a runaway the running
                      policy let through;
  **false positive** — the candidate would have stopped an agent that was
                      perfectly healthy. **Counted, not hidden**: a backtest that
                      only reports the good news is an advertisement, not a
                      measurement;
  **already caught** — the running policy stopped it too. Nothing new.

The ground truth is the store's own record of what happened: an agent with a
recorded **alert** went wrong, an agent with none was healthy. That is the only
honest line between a catch and a false positive, and it is why the replay
needs the *alerts* and not just the spans.

The money is the same money the live system counts: the ROI formula (§8) —
`$/min at the moment of action × horizon` for a PAUSE or a KILL.

The replay is **deterministic**: the same traces and the same candidate policy
always give the same report, in the same order, with the same numbers. A
backtest that varied run to run could not be used to compare two policies.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from brain.detectors import Level, evaluate
from brain.policy import Policy
from brain.state import AgentWindow
from shared.config import Settings
from shared.contracts import (BACKTEST_CATCH_ACTIONS, backtest_catch, backtest_false_positive,
                              backtest_report, backtest_summary)

# The actions that stop an agent. A WARN is not one of them: warning about a
# runaway is not stopping it.
STOPPING_ACTIONS = ("PAUSE", "KILL")


@dataclass
class Candidate:
    """One thing the candidate policy would have done, at one moment."""
    agent_id: str
    rule: str
    at: float
    action: str
    reason: str
    usd_per_min: float = 0.0
    budget_usd: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        """The identity of a finding: the agent and the rule.

        One runaway produces one finding per rule, not one per span — the rule
        keeps firing as the agent keeps going, and every one of those moments is
        the same mistake. Counting them separately would turn one incident into
        a hundred catches.
        """
        return (self.agent_id, self.rule)


def _load_candidate(policy_path: str, running: Policy) -> tuple[Policy, str]:
    """
    The policy to test, and where it came from.

    With no path the **running** policy is tested against itself — that is the
    sanity check every backtest needs: it must find the incidents the running
    policy already caught, and nothing else. A backtest that cannot reproduce
    what is already known is not measuring the candidate, it is measuring
    itself.
    """
    if not policy_path:
        return running, running.source
    candidate = Policy.load(policy_path, default_budget=running.budget_usd)
    return candidate, candidate.source


def _recorded_incidents(store) -> dict[str, set[str]]:
    """Which rules actually fired, per agent — the running policy's own record.

    The alert's `rule` column is the precise name of the rule that fired, so
    this is not a guess: it is the brain's own account of what it saw.

    An agent with no recorded alert was healthy. That is the line between a
    catch and a false positive, and it is the whole reason the replay reads
    the alerts and not only the spans.
    """
    incidents: dict[str, set[str]] = {}
    for row in store.recent_alerts(limit=1000) or []:
        agent_id = str(row.get("agent_id") or "")
        if not agent_id:
            continue
        rules = incidents.setdefault(agent_id, set())
        for rule in str(row.get("rule") or "").split(","):
            rule = rule.strip()
            if rule:
                rules.add(rule)
    return incidents


def _recorded_stops(store, incidents: dict[str, set[str]]) -> set[tuple[str, str]]:
    """
    The (agent, rule) pairs the running policy already stopped.

    A rule the running policy already fired for an agent is **not** a new
    catch — the point of a catch is that the running policy missed it. The
    action row says the agent was stopped; the alert says which rule saw it,
    and the two together say "this one was already handled".

    An action with no alert behind it (a human pausing an agent, say) counts
    for every rule of that agent: the operator dealt with it, so it is not
    something the candidate policy would have caught.
    """
    stopped: set[tuple[str, str]] = set()
    for row in store.recent_actions(limit=1000) or []:
        action = str(row.get("action") or "").upper()
        if action not in STOPPING_ACTIONS:
            continue
        agent_id = str(row.get("agent_id") or "")
        rules = incidents.get(agent_id) or {""}
        for rule in rules:
            stopped.add((agent_id, rule))
    return stopped


def _replay_agent(agent_id: str, spans: list[dict], candidate: Policy, cfg: Settings) -> list[Candidate]:
    """
    Walk one agent's spans again and collect what the candidate policy would fire.

    The window, the snapshot and the detector are the **live** ones — the same
    `AgentWindow` and the same `evaluate()` the brain uses every tick. The only
    thing that changes is the budget: the candidate policy's budget for this
    agent, instead of the running one's.
    """
    window = AgentWindow(agent_id)
    findings: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    budget = candidate.budget_for(agent_id)

    for span in spans:
        try:
            window.add(span)
        except Exception:
            continue  # one malformed span must not stop the replay
        ts = float(span.get("start_ts") or window.last_seen or 0.0)
        try:
            snap = window.snapshot(ts, budget)
        except Exception:
            continue
        try:
            finding = evaluate(snap, cfg)
        except Exception:
            continue
        if finding.level == Level.OK:
            continue

        for rule, reason in zip(finding.rules, finding.reasons):
            key = (agent_id, rule)
            if key in seen:
                continue   # the same mistake, counted once
            seen.add(key)
            # A CRITICAL finding breaks a hard limit and stops the agent on the
            # spot. A SUSPICIOUS one asks the judge — and the judge pauses when
            # it agrees, so the candidate would have stopped the agent either
            # way. The difference is only *how* it stops it.
            action = "KILL" if finding.level == Level.CRITICAL else "PAUSE"
            findings.append(Candidate(
                agent_id=agent_id, rule=rule, at=ts, action=action, reason=reason,
                usd_per_min=snap.usd_per_min, budget_usd=budget))
    return findings


def _usd_saved(candidate: Candidate, horizon_minutes: float) -> float:
    """
    The money the catch would have saved — by the ROI formula (§8).

    `KILL/PAUSE: saved = $/min at the moment of action × horizon`. The burn rate
    is the agent's own at that moment, so a catch on a burning agent is worth
    more than a catch on a quiet one.
    """
    if candidate.action not in BACKTEST_CATCH_ACTIONS:
        return 0.0
    return round(candidate.usd_per_min * horizon_minutes, 4)


def run_backtest(store, candidate_policy: Policy, cfg: Settings,
                 running_policy: Optional[Policy] = None,
                 minutes: Optional[float] = None,
                 policy_version: str = "",
                 as_of: Optional[float] = None) -> dict:
    """
    Replay the stored traces against `candidate_policy` and report what it would
    have caught.

    The report says three things: the catches, the false positives, and the
    money. A store with no history reports **zeroes, not an error** — "we have
    no traces, so we cannot tell you anything" is a fact, and a backtest that
    fails on an empty store teaches the operator to distrust it.
    """
    window_minutes = float(minutes if minutes is not None else cfg.backtest_window_minutes)
    horizon = float(cfg.roi_horizon_minutes)
    running = running_policy or candidate_policy

    spans = store.recent_spans(minutes=window_minutes) or []
    by_agent: dict[str, list[dict]] = {}
    for span in spans:
        agent_id = str(span.get("agent_id") or "").strip()
        if agent_id:
            by_agent.setdefault(agent_id, []).append(span)
    for rows in by_agent.values():
        rows.sort(key=lambda s: float(s.get("start_ts") or 0.0))

    incidents = _recorded_incidents(store)
    already_stopped = _recorded_stops(store, incidents)

    catches, false_positives = [], []
    for agent_id in sorted(by_agent):
        for finding in _replay_agent(agent_id, by_agent[agent_id], candidate_policy, cfg):
            if finding.action not in BACKTEST_CATCH_ACTIONS:
                continue
            if finding.key in already_stopped:
                continue   # the running policy stopped it too — nothing new here
            # The line between a catch and a false positive: did the agent
            # actually go wrong? The store's own alerts are the record of that.
            #
            #   no alert at all      → the agent was healthy: a false positive
            #   an alert, other rule → the agent really was going wrong, but the
            #                          running policy saw it differently: a catch
            #   an alert, same rule  → already handled above (already_stopped)
            if incidents.get(agent_id):
                catches.append(backtest_catch(
                    finding.rule, finding.agent_id, finding.at, finding.action,
                    finding.reason, _usd_saved(finding, horizon)))
            else:
                false_positives.append(backtest_false_positive(
                    finding.rule, finding.agent_id, finding.at, finding.reason))

    catches.sort(key=lambda c: (c["at"], c["agent_id"], c["rule"]))
    false_positives.sort(key=lambda f: (f["at"], f["agent_id"], f["rule"]))
    usd_saved = round(sum(c["usd_saved"] for c in catches), 4)

    return backtest_report(
        catches=catches, false_positives=false_positives,
        policy_version=policy_version or candidate_policy.version,
        agents_tested=sorted(by_agent),
        spans_replayed=len(spans),
        usd_saved=usd_saved,
        horizon_minutes=horizon,
        as_of=time.time() if as_of is None else as_of)


def run_backtest_with_path(store, cfg: Settings, running_policy: Policy,
                            policy_path: str = "",
                            minutes: Optional[float] = None) -> dict:
    """The backtest as the CLI and the API call it: the policy comes from a path."""
    candidate, _source = _load_candidate(policy_path, running_policy)
    return run_backtest(store, candidate, cfg, running_policy=running_policy,
                        minutes=minutes, policy_version=candidate.version)


# ── the CLI ────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    """
    `python -m brain.backtest [policy.yaml]`

    Prints the report as JSON and exits 0 — **even when the report is empty**.
    A backtest that found nothing is a result, not a failure: the operator
    asked a question and got an answer.

    The exit code is 0 for a normal report and 1 only when the backtest itself
    could not be run (a broken policy file, an unreadable store).
    """
    parser = argparse.ArgumentParser(
        prog="python -m brain.backtest",
        description="Replay the stored traces against a candidate policy.")
    parser.add_argument("policy", nargs="?", default="",
                        help="the candidate policy file; without it, the running policy is tested")
    parser.add_argument("--minutes", type=float, default=None,
                        help="how many minutes of stored traces to replay")
    parser.add_argument("--db", default=None, help="the database file (default: the configured one)")
    parser.add_argument("--running-policy", default=None,
                        help="the policy in force (default: CS_POLICY_FILE)")
    args = parser.parse_args(argv)

    from shared.config import load_settings
    from shared.store import LocalStore

    cfg = load_settings()
    running = Policy.load(args.running_policy or cfg.policy_file, default_budget=cfg.default_budget_usd)

    if args.policy and not Path(args.policy).exists():
        print(f"could not read the candidate policy at {args.policy}", file=sys.stderr)
        return 1

    try:
        store = LocalStore(args.db or cfg.local_db_path)
    except Exception as exc:
        print(f"could not open the store: {exc}", file=sys.stderr)
        return 1

    report = run_backtest_with_path(store, cfg, running, policy_path=args.policy,
                                    minutes=args.minutes)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(backtest_summary(report), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
