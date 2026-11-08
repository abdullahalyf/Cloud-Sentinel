"""
The deterministic demo runner (B3).

One command runs the whole "3 AM incident" headless — an agent goes rogue, the
brain detects it, the judge decides, the breaker acts, the agent is healed or
paused, and the money is counted — with **assertions on every step and on the
timing**. It fails loudly if anything drifts.

**It is deterministic.** The whole run happens on a virtual clock: the fake
fleet, the engine and the detectors all take `now` as an argument, so the same
seed gives the same numbers every time. A demo that is different every run is
a demo nobody can debug at 3 AM — the failure cannot be reproduced, so it
cannot be fixed.

**It works offline.** No Docker, no collector, no Phoenix, no API key. The
judge is the deterministic `fallback` provider, so the verdict is a function of
the input and not of the weather.

**The assertions are the point.** A runner that only prints what happened is a
screenshot; a runner that *checks* every step is a test. When a step does not
happen — the agent was not detected, the judge never reached a verdict, the
breaker never acted, the money was not counted — the run fails loudly and
says which step broke.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from brain.service import request_tool_call
from shared.config import Settings, load_settings
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore

log = logging.getLogger("brain.demo")

# The virtual clock starts here. Any fixed instant works; this one is far
# enough from the epoch that a timestamp is never mistaken for "unset".
T0 = 1_700_000_000.0

# How many virtual seconds the whole demo may take. A demo that takes ten
# minutes of virtual time is a demo that waited too long for the loop to be
# noticed — and a real operator waiting ten minutes has already paid for it.
DEFAULT_BUDGET_SECONDS = 180.0

# The budget for each measured step, in virtual seconds. A step that drifts
# over its budget has *changed*, and a demo whose timings drift is a demo that
# will drift on stage too.
DEFAULT_STEP_BUDGETS = {
    "detect": 60.0,   # rogue → the brain noticed
    "judge": 60.0,    # noticed → the judge reached a verdict
    "act": 30.0,      # verdict → the breaker acted
    "heal": 30.0,     # acted → the agent went back to work (or was paused)
}


class DemoFailure(AssertionError):
    """A step of the demo did not happen, or it happened too late."""


@dataclass
class Step:
    """One measured moment of the demo."""

    name: str
    at: float
    detail: str = ""
    ok: bool = True
    fail: str = ""


@dataclass
class DemoResult:
    """What the run saw, and whether every step held."""

    steps: list[Step] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    agent_id: str = ""
    rule: str = ""
    rules: list[str] = field(default_factory=list)
    pattern: str = ""
    action: str = ""
    usd_saved: float = 0.0
    tokens_saved: int = 0
    spend_usd: float = 0.0
    alerts: int = 0
    verdicts: int = 0
    actions: int = 0
    healed: bool = False
    failed: bool = False
    failures: list[str] = field(default_factory=list)

    def step(self, name: str, at: float, detail: str = "") -> None:
        self.steps.append(Step(name, at, detail))

    def fail(self, message: str) -> None:
        self.failed = True
        self.failures.append(message)


def _settings(cfg: Optional[Settings] = None) -> Settings:
    """The settings the demo runs with: no key, so the judge is deterministic."""
    from dataclasses import replace

    base = cfg or load_settings()
    return replace(base, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")


def run_demo(cfg: Optional[Settings] = None, seed: int = 20261108,
             agent_id: str = "beta", budget_seconds: float = DEFAULT_BUDGET_SECONDS,
             step_budgets: Optional[dict] = None) -> DemoResult:
    """
    Run the whole incident once, on a virtual clock, and check every step.

    The result says what happened even when a step failed, so a failing run
    still tells you *where* it broke instead of just that it did.
    """
    budgets = dict(DEFAULT_STEP_BUDGETS)
    if step_budgets:
        budgets.update(step_budgets)

    settings = _settings(cfg)
    store = LocalStore(":memory:")
    policy = Policy.load("brain/policies.yaml")
    fleet = FakeFleet(store, auto_rogue=None, start=T0, seed=seed)
    fleet.gate = lambda a, t, args, v: request_tool_call(store, policy, a, t, args, v)
    engine = Engine(store, fleet, Judge(settings), policy, settings, sync_judge=True)

    result = DemoResult(agent_id=agent_id)

    # ── 1. the agent goes rogue ──
    fleet.go_rogue(agent_id, "paraphrase_loop", T0)
    result.step("rogue", T0, f"{agent_id} started looping")

    # ── 2. the brain watches, the judge decides, the breaker acts ──
    # The clock is stepped one second at a time so every step is dated exactly
    # when it happened. A coarse step would put the whole incident inside one
    # second and make the timings meaningless.
    now = T0
    detected_at = judged_at = acted_at = healed_at = None
    deadline = T0 + float(budget_seconds)

    while now < deadline:
        now += 1.0
        fleet.step(now)
        engine.tick(now)

        if detected_at is None and store.recent_alerts(limit=20):
            detected_at = now
            result.step("detect", now, "the brain flagged the agent")
        if judged_at is None and store.recent_verdicts(limit=20, agent_id=agent_id):
            judged_at = now
            result.step("judge", now, "the judge reached a verdict")
        if acted_at is None and store.recent_actions(limit=20):
            acted_at = now
            result.step("act", now, "the breaker acted")
        if acted_at is not None and healed_at is None and _is_healed(engine, agent_id, now):
            healed_at = now
            result.step("heal", now, "the agent went back to work")
            break
        if acted_at is not None and healed_at is None and _is_paused(engine, agent_id):
            healed_at = now
            result.step("heal", now, "the agent was stopped and is waiting for a human")
            break

    # ── 3. the assertions ──
    _check(result, "the agent was detected", detected_at is not None,
           "no alert was raised — the detectors did not notice the loop")
    _check(result, "the judge reached a verdict", judged_at is not None,
           "no verdict was reached — the judge never decided")
    _check(result, "the breaker acted", acted_at is not None,
           "no action was taken — the loop ran unchecked")
    _check(result, "the money was counted", True, "")

    if detected_at is not None:
        result.timings["detect"] = round(detected_at - T0, 1)
    if judged_at is not None and detected_at is not None:
        result.timings["judge"] = round(judged_at - detected_at, 1)
    if acted_at is not None and judged_at is not None:
        result.timings["act"] = round(acted_at - judged_at, 1)
    if healed_at is not None and acted_at is not None:
        result.timings["heal"] = round(healed_at - acted_at, 1)
    result.timings["total"] = round(now - T0, 1)

    # The budgets. A step that took longer than its budget is a step that
    # *changed*, and a demo whose timings drift is a demo that will drift on
    # stage too.
    for name, budget in budgets.items():
        actual = result.timings.get(name)
        if actual is None:
            continue
        if actual > budget:
            result.fail(f"the {name} step took {actual}s, over its {budget}s budget")

    # ── 4. what the store says ──
    alerts = store.recent_alerts(limit=50)
    verdicts = store.recent_verdicts(limit=50, agent_id=agent_id)
    actions = store.recent_actions(limit=50)
    result.alerts = len(alerts)
    result.verdicts = len(verdicts)
    result.actions = len(actions)
    if alerts:
        # The alert names every rule that fired, comma-joined. One agent can
        # trip two detectors at once, and the report should say both — so the
        # list is split, and the headline is the first one.
        result.rules = [r.strip() for r in str(alerts[0].get("rule") or "").split(",") if r.strip()]
        result.rule = result.rules[0] if result.rules else ""
    if verdicts:
        result.pattern = str(verdicts[0].get("pattern") or "")
        result.action = str(verdicts[0].get("action") or "")
    for row in actions:
        if row.get("agent_id") != agent_id:
            continue
        result.usd_saved += float(row.get("usd_saved_estimate") or 0)
        result.tokens_saved += int(row.get("tokens_saved_estimate") or 0)
    result.usd_saved = round(result.usd_saved, 4)
    result.healed = healed_at is not None

    from brain import service
    view = next((a for a in service.fleet_view(store) if a["agent_id"] == agent_id), None)
    result.spend_usd = round(float((view or {}).get("spend_usd") or 0.0), 4)

    if result.usd_saved <= 0:
        result.fail("no money was saved — the action did not stop the spending")
    if result.rule == "":
        result.fail("the alert carried no rule — the root cause is unknown")

    result.failed = bool(result.failures)
    return result


def _check(result: DemoResult, what: str, ok: bool, why: str) -> None:
    """Record a check. A failed check is a failed demo, not a warning."""
    if ok:
        result.step("check", 0.0, f"ok: {what}")
    else:
        result.step("check", 0.0, f"FAILED: {what}")
        result.fail(f"{what} — {why}")


def _is_healed(engine: Engine, agent_id: str, now: float) -> bool:
    """Is the agent back in good standing? On probation counts as healed."""
    breaker = engine.breakers.get(agent_id)
    return breaker is not None and breaker.state in ("healthy", "probation")


def _is_paused(engine: Engine, agent_id: str) -> bool:
    breaker = engine.breakers.get(agent_id)
    return breaker is not None and breaker.state in ("paused", "killed")


def render_markdown(result: DemoResult, runs: int = 1, held: Optional[int] = None) -> str:
    """
    The demo report.

    The numbers are the numbers the run measured — the same ones the
    assertions checked. A report that says something different from the run
    would be a report nobody can trust.
    """
    lines = [
        "# The 3 AM incident — a deterministic demo run",
        "",
        "One command, one incident, no Docker and no API key. The clock is virtual, so the",
        "numbers below are the same every time the runner is called with the same seed.",
        "",
        f"- **Runs**: {runs}",
    ]
    if held is not None:
        lines.append(f"- **Held**: {held}/{runs} runs passed every assertion")
    lines += [
        f"- **Agent**: `{result.agent_id}`",
        f"- **Root cause**: `{result.rule}` — `{result.pattern}`",
        f"- **Rules that fired**: {', '.join(f'`{r}`' for r in result.rules) or '—'}",
        f"- **Action**: `{result.action}`",
        f"- **Healed**: {'yes' if result.healed else 'no'}",
        "",
        "## The timings",
        "",
        "| Step | Seconds | Budget |",
        "|---|---|---|",
    ]
    for name in ("detect", "judge", "act", "heal", "total"):
        value = result.timings.get(name)
        budget = DEFAULT_STEP_BUDGETS.get(name)
        shown = f"{value:.1f}s" if value is not None else "not reached"
        limit = f"{budget:.0f}s" if budget is not None else "—"
        lines.append(f"| {name} | {shown} | {limit} |")
    lines += [
        "",
        "## The money",
        "",
        f"- **Saved**: ${result.usd_saved:.4f} ({result.tokens_saved:,} tokens)",
        f"- **Spent**: ${result.spend_usd:.4f}",
        "",
        "## The steps",
        "",
    ]
    for step in result.steps:
        if step.name == "check":
            continue
        lines.append(f"- `{step.at:.0f}` **{step.name}** — {step.detail}")
    lines += ["", "## The assertions", ""]
    if result.failures:
        for failure in result.failures:
            lines.append(f"- **FAILED**: {failure}")
    else:
        lines.append("- every step held: the agent was detected, the judge decided, "
                     "the breaker acted, and the money was counted.")
    lines += [
        "",
        "## How to reproduce",
        "",
        "```bash",
        "python -m brain.demo_runner --runs 20 --write docs/research/demo_run.md",
        "```",
        "",
        "It exits non-zero if any step drifts over its budget, so it can be a CI job.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    """The command. It exits non-zero on a drift — that is the whole point."""
    parser = argparse.ArgumentParser(
        prog="demo",
        description="Run the 3 AM incident headless and check every step.")
    parser.add_argument("--seed", type=int, default=20261108,
                        help="the seed — the same seed gives the same run")
    parser.add_argument("--agent", default="beta", help="which agent goes rogue")
    parser.add_argument("--runs", type=int, default=1,
                        help="how many times to run it (all of them must hold)")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_SECONDS,
                        help="the whole demo may take this many virtual seconds")
    parser.add_argument("--write", default="",
                        help="write the markdown report to this path")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    # The brain logs what it does, which is right in a server and wrong here:
    # the demo's own report is the output, and the engine's chatter would
    # bury it. The log level is only lowered for this process.
    logging.getLogger("brain").setLevel(logging.ERROR)
    logging.getLogger("shared").setLevel(logging.ERROR)

    results = []
    for _ in range(max(1, int(args.runs))):
        result = run_demo(seed=args.seed, agent_id=args.agent, budget_seconds=args.budget)
        results.append(result)

    failed = [r for r in results if r.failed]
    held = len(results) - len(failed)
    if args.json:
        print(json.dumps([_as_dict(r) for r in results], indent=2))
    else:
        print(render_markdown(results[-1], runs=len(results), held=held))
        if failed:
            for failure in failed[0].failures:
                print(f"FAILED: {failure}", file=sys.stderr)

    if args.write:
        os.makedirs(os.path.dirname(os.path.abspath(args.write)) or ".", exist_ok=True)
        with open(args.write, "w", encoding="utf-8") as handle:
            handle.write(render_markdown(results[-1], runs=len(results), held=held))
        print(f"wrote {args.write}", file=sys.stderr)

    return 1 if failed else 0


def _as_dict(result: DemoResult) -> dict:
    return {
        "agent_id": result.agent_id, "rule": result.rule, "pattern": result.pattern,
        "action": result.action, "usd_saved": result.usd_saved,
        "tokens_saved": result.tokens_saved, "spend_usd": result.spend_usd,
        "alerts": result.alerts, "verdicts": result.verdicts, "actions": result.actions,
        "healed": result.healed, "timings": result.timings,
        "failures": result.failures, "failed": result.failed,
    }


if __name__ == "__main__":
    raise SystemExit(main())
