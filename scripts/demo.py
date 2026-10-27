"""Demo rehearsal: python scripts/demo.py [--docker] [--timeout 60].

Default (fake): simulated agents and a fresh temporary SQLite database, never the
dashboard's database.
--docker: the real sentinel against the real agent containers and the database from
.env (so the dashboard shows it too). Run `docker compose up -d --build` first.

Both send GO_ROGUE to beta at 10 seconds and print persisted flag/kill times.
--all: plays the 4 rogue types of agents/agent.py one after another in fake mode (a fresh temporary
database each time) and prints: type | flagged after | killed after | killed by | healthy survived.
Exit code 0 only if every rogue was killed and alpha/gamma survived every run.
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.store import Store

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


HEALTHY = ("alpha", "gamma")
ROGUE_TYPES = ("loop", "token_bomb", "memory_leak", "paraphrase_loop")   # = sentinel.sources.ROGUE_TYPES


def measure(store: Store, child: subprocess.Popen, timeout: float, rogue_delay: float = 10) -> dict:
    """Wait for beta's metrics, send GO_ROGUE, then return when and how beta was flagged and killed."""
    from shared.contracts import CommandRow

    started = time.time()
    clock = time.monotonic()
    rogue_at: float | None = None
    flagged_at: float | None = None
    while time.monotonic() - clock < timeout:
        if child.poll() is not None:
            raise RuntimeError(f"sentinel exited early (code {child.returncode})")
        elapsed = time.monotonic() - clock
        if rogue_at is None and elapsed >= rogue_delay:
            if not any(m['agent'] == 'beta' for m in store.recent_metrics()):
                raise RuntimeError(f"sentinel did not produce beta metrics before {rogue_delay:g}s")
            command = CommandRow('beta', 'GO_ROGUE', 'rehearsal', 'Scheduled rehearsal')
            store.insert_command(command)
            rogue_at = datetime.fromisoformat(command.created_at).timestamp() - started
        if rogue_at is not None:
            flags = [datetime.fromisoformat(a['created_at']).timestamp() - started
                     for a in store.recent_alerts()
                     if a['agent'] == 'beta' and a['severity'] in ('warning', 'critical')]
            flags = [t for t in flags if t >= rogue_at]
            if flags:
                flagged_at = min(flags) if flagged_at is None else min(flagged_at, *flags)
            kills = [a for a in store.recent_actions()
                     if a['agent'] == 'beta' and a['action'] == 'KILL']
            for kill in reversed(kills):
                killed_at = datetime.fromisoformat(kill['created_at']).timestamp() - started
                if killed_at < rogue_at:
                    continue
                if flagged_at is None:
                    raise RuntimeError("beta was killed without a recorded flag")
                return {"rogue_at": rogue_at, "flagged_at": flagged_at, "killed_at": killed_at,
                        "actor": kill["actor"]}
        time.sleep(0.1)
    raise RuntimeError(f"rehearsal timed out after {timeout:g}s without a complete timeline")


def timeline(store: Store, child: subprocess.Popen, timeout: float) -> str:
    t = measure(store, child, timeout)
    return (f"rogue at {t['rogue_at']:.1f}s → flagged at {t['flagged_at']:.1f}s → "
            f"killed at {t['killed_at']:.1f}s by {t['actor']}")


RESET_HINT = "Reset the agents for the next run:  docker compose up -d --force-recreate"


def rehearse(store: Store, command: list[str], timeout: float) -> int:
    """Run the sentinel as a child process, print the timeline, always stop the child."""
    with tempfile.TemporaryFile(mode='w+t') as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL)
        try:
            result = timeline(store, child, timeout)
        except (RuntimeError, KeyboardInterrupt) as exc:
            print(f"Rehearsal stopped: {exc or 'interrupted'}", file=sys.stderr)
            log.seek(0)
            print(log.read()[-4000:], file=sys.stderr, end='')
            return 1
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        print(result)
    return 0


def healthy_survived(store: Store) -> bool:
    """alpha and gamma were never killed and are still reporting fresh metrics."""
    if any(a["agent"] in HEALTHY and a["action"] == "KILL" for a in store.recent_actions()):
        return False
    latest: dict[str, float] = {}
    for m in store.recent_metrics():
        latest[m["agent"]] = max(latest.get(m["agent"], 0), datetime.fromisoformat(m["created_at"]).timestamp())
    return all(time.time() - latest.get(name, 0) < 5 for name in HEALTHY)


def run_one_type(rogue_type: str, timeout: float) -> dict:
    """Fake sentinel + a fresh database; beta goes rogue the way `rogue_type` says."""
    from shared.store import LocalStore

    with tempfile.TemporaryDirectory(prefix='cloudsentinel-demo-', ignore_cleanup_errors=True) as directory:
        env = {**os.environ, 'ANTHROPIC_API_KEY': '', 'GEMINI_API_KEY': '', 'SUPABASE_URL': '', 'SUPABASE_KEY': '',
               'LOCAL_DB_PATH': str(Path(directory) / 'rehearsal.db'), 'DRY_RUN': 'false', 'LOG_FILE': '',
               'WEBHOOK_URL': ''}
        store = LocalStore(env['LOCAL_DB_PATH'])
        with tempfile.TemporaryFile(mode='w+t') as log:
            child = subprocess.Popen([sys.executable, '-m', 'sentinel', '--fake', '--no-auto-rogue',
                                      '--rogue-type', rogue_type], cwd=ROOT, env=env, stdout=log,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            try:
                result = measure(store, child, timeout, rogue_delay=4)
                time.sleep(2)                     # the healthy agents must keep going after the kill
                result["healthy"] = healthy_survived(store)
            finally:
                if hasattr(store, "conn") and store.conn:
                    try:
                        store.conn.close()
                    except Exception:
                        pass
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        return result


def run_all(timeout: float) -> int:
    rows, failed = [], False
    for rogue_type in ROGUE_TYPES:
        try:
            t = run_one_type(rogue_type, timeout)
            rows.append((rogue_type, f"{t['flagged_at'] - t['rogue_at']:.1f}s", f"{t['killed_at'] - t['rogue_at']:.1f}s",
                         t["actor"], "yes" if t["healthy"] else "NO"))
            failed |= not t["healthy"]
        except RuntimeError as exc:
            rows.append((rogue_type, "-", "-", f"FAILED: {exc}", "-"))
            failed = True
    header = ("ROGUE_TYPE", "flagged after", "killed after", "killed by", "healthy survived")
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for line in [header, ("-" * w for w in widths), *rows]:
        print(" | ".join(str(c).ljust(w) for c, w in zip(line, widths)))
    print("\nFAIL" if failed else "\nPASS")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=60, help='total rehearsal deadline in seconds')
    parser.add_argument('--docker', action='store_true',
                        help='real sentinel + real agent containers + the .env database')
    parser.add_argument('--all', action='store_true',
                        help='play all 4 rogue types one after another in fake mode and print a table')
    args = parser.parse_args(argv)
    if args.all and args.docker:
        parser.error('--all runs in fake mode; it cannot be combined with --docker')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be a finite positive number')

    if args.all:
        return run_all(min(args.timeout, 40))

    if args.docker:
        from shared.store import get_store

        code = rehearse(get_store(), [sys.executable, '-m', 'sentinel'], args.timeout)
        print(RESET_HINT)
        return code

    with tempfile.TemporaryDirectory(prefix='cloudsentinel-demo-', ignore_cleanup_errors=True) as directory:
        # Set overrides before importing settings; .env must not enable remote services.
        os.environ.update(ANTHROPIC_API_KEY='', SUPABASE_URL='', SUPABASE_KEY='',
                          LOCAL_DB_PATH=str(Path(directory) / 'rehearsal.db'), DRY_RUN='false',
                          LOG_FILE='', WEBHOOK_URL='')
        from shared.store import get_store

        store = get_store()
        try:
            return rehearse(store, [sys.executable, '-m', 'sentinel', '--fake', '--no-auto-rogue'],
                            args.timeout)
        finally:
            if hasattr(store, "conn") and store.conn:
                try:
                    store.conn.close()
                except Exception:
                    pass


if __name__ == '__main__':
    raise SystemExit(main())
