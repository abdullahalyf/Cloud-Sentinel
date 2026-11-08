"""
Start the brain: engine loop + C2 API (:8000) in one process.

    python -m brain                 # watch real containers (EXECUTOR=docker by default)
    python -m brain --fake          # no Docker: 4 simulated ShopBD agents, beta goes rogue after 20 s
    python -m brain --fake --no-auto-rogue
    python -m brain --dry-run       # never actually pause/kill, only log
    python -m brain --no-api        # engine only
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from dataclasses import replace

from brain import service
from brain.api import create_app
from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from shared.config import settings
from shared.store import get_store


def build_executor(kind: str, store, args):
    if kind == "fake":
        from shared.mocks.fake_fleet import FakeFleet

        return FakeFleet(store, auto_rogue=None if args.no_auto_rogue else "beta",
                         auto_rogue_kind=args.rogue_kind, rogue_after=args.rogue_after)
    from infra.executor import get_executor

    return get_executor(replace(settings, executor=kind))


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m brain", description="CloudSentinel brain + C2 API")
    p.add_argument("--fake", action="store_true", help="simulated agents instead of Docker")
    p.add_argument("--rogue-after", type=float, default=20.0, help="[fake] seconds until beta goes rogue")
    p.add_argument("--rogue-kind", default="paraphrase_loop", help="[fake] how beta goes rogue")
    p.add_argument("--no-auto-rogue", action="store_true", help="[fake] only go rogue via dashboard/script")
    p.add_argument("--dry-run", action="store_true", help="log actions instead of executing them")
    p.add_argument("--no-api", action="store_true", help="do not start the C2 API")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(name)-14s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "uvicorn.access", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log = logging.getLogger("brain")

    kind = "fake" if args.fake else settings.executor
    store = get_store()
    try:
        executor = build_executor(kind, store, args)
    except Exception as exc:
        log.error("Cannot start the %s executor (%s). Is Docker running? "
                  "Tip: `python -m brain --fake` works without Docker.", kind, exc)
        sys.exit(1)

    policy = Policy.load(settings.policy_file, settings.default_budget_usd)
    judge = Judge(settings)
    engine = Engine(store, executor, judge, policy, settings, dry_run=args.dry_run or settings.dry_run,
                    runtime_name=kind, policy_path=settings.policy_file)
    before_tick = None
    if kind == "fake":  # the fake fleet generates spans itself and goes through the real tool gate
        # the gate reads the LIVE policy, so a hot reload changes the decision (A5)
        executor.gate = lambda agent, tool, a, v: service.request_tool_call(
            store, engine.policy_manager.policy, agent, tool, a, v)
        before_tick = executor.step

    log.info("Mode: %s · store: %s · judge: %s", kind.upper(),
             "Supabase" if settings.use_supabase else f"SQLite ({settings.local_db_path})", judge.provider)
    if args.no_api:
        engine.run_forever(before_tick)
        return
    threading.Thread(target=engine.run_forever, args=(before_tick,), daemon=True, name="engine").start()

    import uvicorn

    log.info("C2 API on http://localhost:%d  (docs: /docs)", settings.api_port)
    uvicorn.run(create_app(store, policy, settings, kind, judge.provider,
                           policy_manager=engine.policy_manager), host=settings.api_host,
                port=settings.api_port, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBrain stopped.")
