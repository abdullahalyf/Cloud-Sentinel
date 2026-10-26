"""
Start the sentinel.

    python -m sentinel              # real mode: watch Docker containers
    python -m sentinel --fake       # no Docker needed: 3 simulated agents, "beta" goes rogue after 20s
    python -m sentinel --fake --rogue-type token_bomb   # loop | token_bomb | memory_leak | paraphrase_loop
    python -m sentinel --dry-run    # never actually kill, only log "would kill"
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sentinel.brain import Brain
from sentinel.engine import Sentinel
from sentinel.sources import ROGUE_TYPES, DockerSource, FakeSource
from shared.config import settings
from shared.store import get_store


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m sentinel", description="CloudSentinel circuit breaker")
    p.add_argument("--fake", action="store_true", help="use simulated agents instead of Docker")
    p.add_argument("--rogue-after", type=float, default=20.0, help="[fake] seconds until 'beta' goes rogue")
    p.add_argument("--rogue-type", choices=ROGUE_TYPES, default="loop",
                   help="[fake] how the rogue agent misbehaves (same as ROGUE_TYPE in agents/agent.py)")
    p.add_argument("--no-auto-rogue", action="store_true", help="[fake] only go rogue via dashboard/script")
    p.add_argument("--dry-run", action="store_true", help="log kills instead of doing them")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_file:
        Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(settings.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-16s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    log = logging.getLogger("sentinel")

    if args.fake:
        source = FakeSource(settings, auto_rogue=None if args.no_auto_rogue else "beta",
                            rogue_after=args.rogue_after, rogue_type=args.rogue_type)
        log.info("Mode: FAKE agents (no Docker), rogue type: %s", args.rogue_type)
    else:
        try:
            source = DockerSource(settings)
        except Exception as exc:
            log.error("Cannot reach Docker (%s). Is Docker Desktop running? "
                      "Tip: use `python -m sentinel --fake` to work without Docker.", exc)
            sys.exit(1)
        log.info("Mode: DOCKER (watching containers with label %s=true)", settings.monitor_label)

    log.info("Database: %s", "Supabase" if settings.use_supabase else f"local SQLite ({settings.local_db_path})")
    Sentinel(source, get_store(), Brain(settings), settings,
             dry_run=args.dry_run or settings.dry_run).run_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # Ctrl+C during startup; the loop handles its own
        pass
    print("\nSentinel stopped.")
