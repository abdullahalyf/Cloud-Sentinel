"""Demo rehearsal: python scripts/demo.py [--docker] [--timeout 60].

Default (fake): simulated agents and a fresh temporary SQLite database, never the
dashboard's database.
--docker: the real sentinel against the real agent containers and the database from
.env (so the dashboard shows it too). Run `docker compose up -d --build` first.

Both send GO_ROGUE to beta at 10 seconds and print persisted flag/kill times.
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


def timeline(store: Store, child: subprocess.Popen, timeout: float) -> str:
    from shared.contracts import CommandRow

    started = time.time()
    clock = time.monotonic()
    rogue_at: float | None = None
    flagged_at: float | None = None
    while time.monotonic() - clock < timeout:
        if child.poll() is not None:
            raise RuntimeError(f"sentinel exited early (code {child.returncode})")
        elapsed = time.monotonic() - clock
        if rogue_at is None and elapsed >= 10:
            if not any(m['agent'] == 'beta' for m in store.recent_metrics()):
                raise RuntimeError("sentinel did not produce beta metrics before 10s")
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
                return (f"rogue at {rogue_at:.1f}s → flagged at {flagged_at:.1f}s → "
                        f"killed at {killed_at:.1f}s by {kill['actor']}")
        time.sleep(0.1)
    raise RuntimeError(f"rehearsal timed out after {timeout:g}s without a complete timeline")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=60, help='total rehearsal deadline in seconds')
    parser.add_argument('--docker', action='store_true',
                        help='real sentinel + real agent containers + the .env database')
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be a finite positive number')

    if args.docker:
        from shared.store import get_store

        code = rehearse(get_store(), [sys.executable, '-m', 'sentinel'], args.timeout)
        print(RESET_HINT)
        return code

    with tempfile.TemporaryDirectory(prefix='cloudsentinel-demo-') as directory:
        # Set overrides before importing settings; .env must not enable remote services.
        os.environ.update(ANTHROPIC_API_KEY='', SUPABASE_URL='', SUPABASE_KEY='',
                          LOCAL_DB_PATH=str(Path(directory) / 'rehearsal.db'), DRY_RUN='false')
        from shared.store import get_store

        return rehearse(get_store(), [sys.executable, '-m', 'sentinel', '--fake', '--no-auto-rogue'],
                        args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())
