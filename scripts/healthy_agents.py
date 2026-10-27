"""
Do healthy agents survive?  Runs 3 well-behaved agents (scripts/healthy_agent.py) against the sentinel
for a few minutes, in REAL time, with the offline fallback brain. Exit code 0 = nobody was killed or flagged.

    python scripts/healthy_agents.py              # 180 seconds
    python scripts/healthy_agents.py --seconds 60

  a  names  one template, different customer names, no numbers
  b  year   every prompt contains "2026"
  c  jobs   "Process job <n>", new job number each call, 2 calls/s
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.verify_agents import SubprocessSource  # noqa: E402
from sentinel.brain import Brain  # noqa: E402
from sentinel.engine import Sentinel  # noqa: E402
from shared.config import settings  # noqa: E402
from shared.store import LocalStore  # noqa: E402

SCENARIOS = {"a_names": "names", "b_year": "year", "c_jobs": "jobs"}


def run(seconds: float = 180.0) -> dict:
    """→ {'survived': {scenario: bool}, 'alerts': {scenario: [rules]}}"""
    cfg = replace(settings, anthropic_api_key="", gemini_api_key="", webhook_url="", log_file="")
    specs = {n: {"SCRIPT": "scripts/healthy_agent.py", "STYLE": style, "CALLS_PER_SEC": "2"}
             for n, style in SCENARIOS.items()}
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalStore(str(Path(tmp) / "healthy.db"))
        source = SubprocessSource(cfg, specs)
        sentinel = Sentinel(source, store, Brain(cfg), cfg)
        try:
            end = time.time() + seconds
            while time.time() < end:
                sentinel.tick()
                time.sleep(0.25)
            alerts = store.recent_alerts(500)
            survived = {n: source.procs[n].poll() is None for n in specs}
            flagged = {n: sorted({a["rule"] for a in alerts if a["agent"] == n and a["rule"] != "brain_cost"})
                       for n in specs}
        finally:
            sentinel.shutdown()
            source.shutdown()
    return {"survived": survived, "alerts": flagged}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seconds", type=float, default=180.0)
    args = p.parse_args()
    result = run(args.seconds)
    for name in SCENARIOS:
        print(f"{name:<8} survived: {'yes' if result['survived'][name] else 'NO':<4} "
              f"alerts: {', '.join(result['alerts'][name]) or 'none'}")
    ok = all(result["survived"].values()) and not any(result["alerts"].values())
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
