"""
Start the brain: engine loop + C2 API (:8000) in one process.

    python -m brain                 # watch real containers (EXECUTOR=docker by default)
    python -m brain --fake          # no Docker: 4 simulated ShopBD agents, beta goes rogue after 20 s
    python -m brain --fake --no-auto-rogue
    python -m brain --dry-run       # never actually pause/kill, only log
    python -m brain --no-api        # engine only
    python -m brain --worker        # A8: one shard of the fleet, no API — run N of these
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
from brain.sharding import Shard, worker_id_from_env
from shared.config import settings
from shared.store import get_store


def build_executor(kind: str, store, args):
    if kind == "fake":
        from shared.mocks.fake_fleet import FakeFleet

        return FakeFleet(store, auto_rogue=None if args.no_auto_rogue else "beta",
                         auto_rogue_kind=args.rogue_kind, rogue_after=args.rogue_after)
    from infra.executor import get_executor

    return get_executor(replace(settings, executor=kind))


def tighten_the_write_timeout(store, seconds: float = 0.05) -> None:
    """Make a locked database fail fast instead of stalling the tick.

    The store's default busy timeout is generous (5 s) because a second brain worker
    may be mid-write and the loser should wait rather than fail. But the brain's tick
    has a 1 s budget, and it writes two rows per agent: four agents is eight writes,
    so a 5 s timeout per write is a brain that goes silent for a minute.

    So the brain shortens the timeout on *its own* connection. The value is chosen so
    that even the worst case — every write in the tick blocked — stays inside the tick
    budget: 50 ms × the writes of one tick is a fraction of a second, and the tick
    never misses its interval. A collision now costs one skipped write — logged, and
    the next tick writes it again — instead of seconds of silence. The store's own
    default is unchanged for everything else.
    """
    conn = getattr(store, "_conn", None)
    if conn is None:
        return   # not a SQLite store (Supabase) — nothing to tighten
    try:
        conn.execute(f"pragma busy_timeout={int(seconds * 1000)}")
    except Exception as exc:
        log.warning("could not tighten the busy timeout: %s", exc)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m brain", description="CloudSentinel brain + C2 API")
    p.add_argument("--fake", action="store_true", help="simulated agents instead of Docker")
    p.add_argument("--rogue-after", type=float, default=20.0, help="[fake] seconds until beta goes rogue")
    p.add_argument("--rogue-kind", default="paraphrase_loop", help="[fake] how beta goes rogue")
    p.add_argument("--no-auto-rogue", action="store_true", help="[fake] only go rogue via dashboard/script")
    p.add_argument("--dry-run", action="store_true", help="log actions instead of executing them")
    p.add_argument("--no-api", action="store_true", help="do not start the C2 API")
    p.add_argument("--worker", action="store_true",
                   help="A8: run as a shard of the fleet (no API). Start N of them to spread the work.")
    p.add_argument("--worker-id", default="", help="A8: this worker's id (default: the hostname and pid)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(name)-14s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "uvicorn.access", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log = logging.getLogger("brain")

    kind = "fake" if args.fake else settings.executor
    store = get_store()
    tighten_the_write_timeout(store)
    try:
        executor = build_executor(kind, store, args)
    except Exception as exc:
        log.error("Cannot start the %s executor (%s). Is Docker running? "
                  "Tip: `python -m brain --fake` works without Docker.", kind, exc)
        sys.exit(1)

    policy = Policy.load(settings.policy_file, settings.default_budget_usd)
    judge = Judge(settings)

    # A8: a worker is a shard of the fleet. The shard is what gives the engine its
    # "these agents are mine" rule, so it is built here and handed to the engine.
    shard = None
    if args.worker:
        shard = Shard(store, worker_id=worker_id_from_env(args.worker_id),
                      heartbeat_seconds=settings.worker_heartbeat_seconds,
                      stale_seconds=settings.worker_stale_seconds)

    engine = Engine(store, executor, judge, policy, settings, dry_run=args.dry_run or settings.dry_run,
                    runtime_name=kind, policy_path=settings.policy_file, shard=shard)
    # A6: the injection gate. One gate for the whole process — the fake fleet's tool calls and
    # the API's tool calls must be judged the same way.
    gate = service.InjectionGate(
        deny_threshold=settings.injection_deny_threshold,
        approval_threshold=settings.injection_approval_threshold,
        allowed_hosts=settings.injection_allowed_hosts,
        enabled=settings.injection_enabled)
    before_tick = None
    if kind == "fake":  # the fake fleet generates spans itself and goes through the real tool gate
        # the gate reads the LIVE policy, so a hot reload changes the decision (A5)
        executor.gate = lambda agent, tool, a, v: service.request_tool_call(
            store, engine.policy_manager.policy, agent, tool, a, v, gate)
        before_tick = executor.step

    log.info("Mode: %s · store: %s · judge: %s", kind.upper(),
             "Supabase" if settings.use_supabase else f"SQLite ({settings.local_db_path})", judge.provider)
    if shard is not None:
        log.info("Worker %s · heartbeat every %.1fs · a worker is stale after %.1fs",
                 shard.worker_id, shard.heartbeat_seconds, shard.stale_seconds)

    if args.no_api or args.worker:
        # A worker never serves the API: the API belongs to the brain process, and two
        # APIs on one port would just fight. The workers only watch and act.
        try:
            engine.run_forever(before_tick)
        finally:
            if shard is not None:
                shard.shutdown()
        return
    threading.Thread(target=engine.run_forever, args=(before_tick,), daemon=True, name="engine").start()

    import uvicorn

    log.info("C2 API on http://localhost:%d  (docs: /docs)", settings.api_port)
    uvicorn.run(create_app(store, policy, settings, kind, judge.provider,
                           policy_manager=engine.policy_manager, injection_gate=gate),
                host=settings.api_host, port=settings.api_port, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBrain stopped.")
