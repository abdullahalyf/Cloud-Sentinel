"""
Judge benchmark: is the judge right, how fast is it, and what does it cost?   Owner: Alif.

1. Runs the demo scenarios on a virtual clock (same as eval/harness.py) and CAPTURES the exact
   JudgeContext the engine hands the judge the first time each agent looks suspicious.
2. Adds hand-made gray-zone cases the fake fleet can't produce (a legit burst of varied work).
3. Sends every case to the chosen judge --runs times and records action, confidence, latency,
   tokens and $ cost.

    python -m brain.judge_bench                        # fallback judge (offline): checks the plumbing
    python -m brain.judge_bench --judge claude --runs 3 --write   # real Claude → docs/research/judge-eval.md
"""
from __future__ import annotations

import argparse
import logging
import statistics
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from brain import service
from brain.detectors import Finding, Level
from brain.engine import Engine
from brain.judge import Judge, JudgeContext, Verdict, fallback_verdict
from brain.policy import Policy
from brain.state import Snapshot
from shared.config import Settings, settings
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore

START = 1_000_000.0
OUT = Path("docs/research/judge-eval.md")


@dataclass
class Case:
    name: str
    ctx: JudgeContext
    expected: tuple[str, ...]     # acceptable actions
    note: str


class _Capture:
    """Stands in for the Judge during the simulation: remembers the context, answers like the fallback."""

    def __init__(self, cfg: Settings):
        self.cfg, self.provider, self.seen = cfg, "fallback", []

    def judge(self, ctx: JudgeContext) -> Verdict:
        self.seen.append(ctx)
        return fallback_verdict(ctx, self.cfg)


def capture(kind: str, agent: str, cfg: Settings, seconds: int = 60) -> Optional[JudgeContext]:
    store = LocalStore(":memory:")
    fleet = FakeFleet(store, names=(agent, "alpha"), auto_rogue=None, start=START)
    policy = Policy.load(cfg.policy_file, cfg.default_budget_usd)
    fleet.gate = lambda a, t, args, v: service.request_tool_call(store, policy, a, t, args, v)
    cap = _Capture(cfg)
    engine = Engine(store, fleet, cap, policy, cfg, sync_judge=True)  # type: ignore[arg-type]
    now = START
    for i in range(seconds):
        now += 1.0
        if i == 10:
            fleet.go_rogue(agent, kind, now)
        fleet.step(now)
        engine.tick(now)
        hit = next((c for c in cap.seen if c.snapshot.agent_id == agent), None)
        if hit:
            return hit
    return None


def legit_burst() -> JudgeContext:
    """A busy but healthy agent: many different orders, all tool calls succeed. The right answer is not PAUSE."""
    snap = Snapshot("alpha", 14_000, 0.06, 1.2, 40_000, 0.12, 0.5, 1, 0.12, False, 0, 120, 23, 18)
    f = Finding()
    f.add(Level.SUSPICIOUS, "token_spike", "tokens/min 14,000 above soft limit")
    prompts = [{"t": i, "tokens": 700, "prompt": f"Summarise the delivery status of order {4400 + i * 7} for the customer"}
               for i in range(12)]
    tools = [{"tool": "orders_api", "status": "ok"} for _ in range(12)]
    return JudgeContext(snap, f, prompts, tools, {"shift": "evening", "queue": "priority"})


def cases(cfg: Settings) -> list[Case]:
    out: list[Case] = []
    for name, kind, agent, expected, note in [
        ("paraphrase_loop", "paraphrase_loop", "beta", ("PAUSE", "KILL"), "same intent, new words, failing tool"),
        ("exact_loop", "loop", "beta", ("PAUSE", "KILL"), "identical prompt repeated"),
        ("memory_leak", "memory_leak", "gamma", ("PAUSE", "KILL", "WARN"), "RAM climbing, prompts fine"),
    ]:
        ctx = capture(kind, agent, cfg)
        if ctx:
            out.append(Case(name, ctx, expected, note))
    out.append(Case("legit_burst", legit_burst(), ("IGNORE", "WARN"), "busy healthy agent (false-positive test)"))
    return out


def run(cfg: Settings, runs: int) -> list[dict]:
    judge = Judge(cfg)
    rows = []
    for case in cases(cfg):
        verdicts = []
        for _ in range(runs):
            verdicts.append(judge.judge(case.ctx))
            time.sleep(0.2 if judge.provider == "claude" else 0)
        actions = [v.action for v in verdicts]
        rows.append({
            "case": case.name, "note": case.note, "expected": "/".join(case.expected),
            "got": ", ".join(f"{v.action} {v.confidence:.2f}" for v in verdicts),
            "source": ",".join(sorted({v.source for v in verdicts})),
            "correct": sum(a in case.expected for a in actions), "runs": runs,
            "p50_ms": round(statistics.median(v.latency_ms for v in verdicts)),
            "max_ms": round(max(v.latency_ms for v in verdicts)),
            "in_tok": round(statistics.mean(v.input_tokens for v in verdicts)),
            "out_tok": round(statistics.mean(v.output_tokens for v in verdicts)),
            "usd": sum(v.cost_usd for v in verdicts) / runs,
            "reason": verdicts[-1].reason, "fix": verdicts[-1].suggested_fix,
        })
    return rows


def markdown(rows: list[dict], cfg: Settings, provider: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    model = cfg.claude_model if provider == "claude" else provider
    lines = [f"Run: {stamp} · judge `{provider}` · model `{model}` · threshold to act "
             f"`BRAIN_KILL_CONFIDENCE={cfg.brain_kill_confidence}`", "",
             "| Case | What it is | Expected | Got (action conf) | Correct | p50 ms | max ms | in tok | out tok | $ / call |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['case']} | {r['note']} | {r['expected']} | {r['got']} | {r['correct']}/{r['runs']} | "
                     f"{r['p50_ms']} | {r['max_ms']} | {r['in_tok']} | {r['out_tok']} | {r['usd']:.6f} |")
    total = sum(r["correct"] for r in rows), sum(r["runs"] for r in rows)
    avg_usd = statistics.mean(r["usd"] for r in rows) if rows else 0
    lines += ["", f"**Accuracy {total[0]}/{total[1]}** · average cost per judge call **${avg_usd:.6f}** "
              f"(≈ ${avg_usd * 1000:.3f} per 1,000 calls)", "", "Last reason per case:", ""]
    lines += [f"- **{r['case']}**: {r['reason']}" + (f" Fix: _{r['fix']}_" if r["fix"] else "") for r in rows]
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m brain.judge_bench")
    p.add_argument("--judge", default="fallback", help="fallback (default) | auto | claude | gemini")
    p.add_argument("--runs", type=int, default=1, help="calls per case (use 3+ for Claude)")
    p.add_argument("--write", action="store_true", help=f"replace the results block in {OUT}")
    args = p.parse_args()
    logging.basicConfig(level=logging.ERROR)
    cfg = replace(settings, judge_provider=args.judge)
    provider = Judge(cfg).provider
    if args.judge in ("claude", "auto") and provider != "claude":
        print("⚠️  ANTHROPIC_API_KEY is not set in this shell: falling back. Put it in .env and retry.")
    table = markdown(run(cfg, max(1, args.runs)), cfg, provider)
    print(table)
    if args.write:
        text = OUT.read_text(encoding="utf-8")
        begin, end = "<!-- bench:start -->", "<!-- bench:end -->"
        head, _, rest = text.partition(begin)
        _, _, tail = rest.partition(end)
        OUT.write_text(f"{head}{begin}\n{table}{end}{tail}", encoding="utf-8")
        print(f"written to {OUT}")


if __name__ == "__main__":
    main()
