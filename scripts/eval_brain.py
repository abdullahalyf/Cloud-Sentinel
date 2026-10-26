"""
How good is the brain?  Runs it on 8 recorded scenarios and prints a table.

    python scripts/eval_brain.py              # the configured LLM (BRAIN_PROVIDER) if its key is set, else fallback
    python scripts/eval_brain.py --offline    # always the fallback rules (no network, no cost)

Scenarios live in tests/fixtures/brain_scenarios/*.json. "expected" is KILL or keep
(keep = WARN or IGNORE: the agent stays alive). A scenario the hard rules already kill
counts as KILL by "rules"; the brain is never asked about it.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import deque
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.brain import HISTORY_SIZE, Brain, Verdict  # noqa: E402
from sentinel.collector import AgentState  # noqa: E402
from sentinel.detector import Level, evaluate  # noqa: E402
from shared.config import Settings, settings  # noqa: E402
from shared.contracts import AgentEvent  # noqa: E402

SCENARIOS = ROOT / "tests" / "fixtures" / "brain_scenarios"


def load_scenarios(folder: Path = SCENARIOS) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]


def run_scenario(sc: dict, brain: Brain, cfg: Settings) -> tuple[str, str]:
    """→ (outcome 'KILL'/'keep', what decided it, e.g. 'KILL 85% (fallback)')."""
    now = time.time()
    st = AgentState("eval-" + sc["name"], "eval", sc["token_budget"])
    for dt, tokens_in, tokens_out, prompt in sc["events"]:
        st.add(AgentEvent(st.agent, "llm_call", now + dt, tokens_in=tokens_in, tokens_out=tokens_out,
                          model="sim", prompt=prompt))
    st.set_memory(sc["memory_mb"], sc["memory_pct"])
    snap = st.snapshot(now)
    finding = evaluate(snap, cfg, [e.prompt for e in st.calls])
    if finding.level == Level.CRITICAL:
        return "KILL", "KILL (rules: " + ",".join(finding.rules) + ")"
    if finding.level == Level.OK:
        return "keep", "not flagged"
    brain.history[st.agent] = deque(((now - ago, Verdict(action, conf, pattern, reason, "fallback"))
                                     for ago, action, conf, pattern, reason in sc.get("past", [])),
                                    maxlen=HISTORY_SIZE)
    v = brain.judge(snap, finding, st.recent_events(12))
    killed = v.action == "KILL" and v.confidence >= cfg.brain_kill_confidence
    return ("KILL" if killed else "keep"), f"{v.action} {v.confidence:.0%} ({v.source})"


def evaluate_all(brain: Brain, cfg: Settings, scenarios: list[dict] | None = None) -> list[dict]:
    rows = []
    for sc in scenarios if scenarios is not None else load_scenarios():
        outcome, verdict = run_scenario(sc, brain, cfg)
        rows.append({"scenario": sc["name"], "expected": sc["expected"], "verdict": verdict,
                     "outcome": outcome, "correct": outcome == sc["expected"]})
    return rows


def table(rows: list[dict]) -> str:
    head = ("scenario", "expected", "verdict", "correct")
    cells = [[r["scenario"], r["expected"], r["verdict"], "✅" if r["correct"] else "❌"] for r in rows]
    widths = [max(len(head[i]), *(len(c[i]) for c in cells)) for i in range(4)]
    line = lambda c: " | ".join(str(x).ljust(w) for x, w in zip(c, widths))  # noqa: E731
    score = sum(r["correct"] for r in rows)
    return "\n".join([line(head), "-+-".join("-" * w for w in widths), *map(line, cells),
                      f"\nscore: {score}/{len(rows)}"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--offline", action="store_true", help="use the fallback rules even if a key is set")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)  # keep the table clean
    cfg = replace(settings, anthropic_api_key="", gemini_api_key="") if args.offline else settings
    brain = Brain(cfg)
    print(f"Brain: {cfg.brain_name}\n")
    print(table(evaluate_all(brain, cfg)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
