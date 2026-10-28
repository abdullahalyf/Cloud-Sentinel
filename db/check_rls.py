"""
db/check_rls.py - prove that db/security.sql really protects the database.   Owner: Fojle.

It tries things with the DASHBOARD key (publishable / anon) that it must and must not be able
to do, then asks the secret key (service_role, from .env) what really happened.
Every row it creates is named "rls-check-xxxx" and is removed again. Real data is never touched.

  PowerShell:   $env:DASHBOARD_KEY="sb_publishable_..."
                python db/check_rls.py

Where to find the publishable key: Supabase -> Project Settings -> API Keys ->
"Publishable and secret API keys". (If your supabase library refuses the new key format,
use the legacy "anon" key from the "Legacy" tab instead.)
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # so "from shared..." works when run as: python db/check_rls.py
os.chdir(ROOT)                  # so .env resolves from the repo root

from shared.config import settings  # noqa: E402
from shared.contracts import utc_now_iso  # noqa: E402

TABLES = ("agent_metrics", "alerts", "actions", "commands")
results: list[bool] = []


def report(ok: bool, text: str) -> None:
    results.append(ok)
    print(("  OK    " if ok else "  FAIL  ") + text)


def try_it(action) -> str | None:
    """Run something. None = it worked. Text = the database refused (that is fine for 'blocked' tests)."""
    try:
        action()
        return None
    except Exception as exc:  # noqa: BLE001 - any refusal counts
        return str(exc)[:70]


def sample(table: str, agent: str, **extra) -> dict:
    now = utc_now_iso()
    row = {
        "agent_metrics": dict(agent=agent, container_id="rls-check", created_at=now),
        "alerts": dict(agent=agent, severity="info", rule="rls_check", message="rls check", created_at=now),
        "actions": dict(agent=agent, action="WARN", actor="human", reason="rls check", created_at=now),
        "commands": dict(agent=agent, command="KILL", requested_by="rls-check", reason="canary",
                         status="pending", result="", created_at=now),
    }[table]
    row.update(extra)
    return row


def count(admin, table: str, agent: str) -> int:
    """How many rows with this agent name exist? Asked with the secret key, so it is the truth."""
    return len(admin.table(table).select("id").eq("agent", agent).execute().data or [])


def main() -> int:
    url, admin_key = settings.supabase_url, settings.supabase_key
    dash_key = os.getenv("DASHBOARD_KEY", "").strip()
    if not (url and admin_key):
        print("No Supabase in .env (SUPABASE_URL / SUPABASE_KEY). Nothing to check.")
        return 2
    if not dash_key:
        print(__doc__)
        return 2
    if dash_key == admin_key:
        print("DASHBOARD_KEY is the same key as SUPABASE_KEY. Use the PUBLISHABLE key here.")
        return 2

    from supabase import create_client

    admin = create_client(url, admin_key)
    try:
        dash = create_client(url, dash_key)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not use that dashboard key: {exc}\nTry the legacy 'anon' key instead.")
        return 2

    tag = "rls-check-" + uuid.uuid4().hex[:8]
    print(f"RLS check ({tag}). Test rows are removed at the end.\n")
    try:
        print("The secret key (sentinel) must still write everywhere:")
        for t in TABLES:
            err = try_it(lambda t=t: admin.table(t).insert(sample(t, tag + "-canary")).execute())
            report(err is None, f"secret key can write {t}" + (f"   [{err}]" if err else ""))
        if not all(results):
            print("\nThe secret key cannot write. SUPABASE_KEY in .env must be the service_role / secret key.")
            return 1

        print("\nThe dashboard key may read, and send new commands:")
        for t in TABLES:
            err = try_it(lambda t=t: dash.table(t).select("id").limit(1).execute())
            report(err is None, f"dashboard key can read {t}" + (f"   [{err}]" if err else ""))
        try_it(lambda: dash.table("commands").insert(sample("commands", tag + "-ok")).execute())
        report(count(admin, "commands", tag + "-ok") == 1, "dashboard key can send a new KILL command")
        if not all(results):
            print("\nThe dashboard key does not work (see FAIL above), so the 'must NOT' checks would prove nothing.")
            print("Try the legacy 'anon' key: Project Settings -> API Keys -> Legacy tab -> anon.")
            return 1

        print("\nThe dashboard key must NOT be able to write anything else:")
        fakes = [
            ("a command that is already 'done'", "commands", dict(status="done")),
            ("a made-up command type", "commands", dict(command="DROP_ALL")),
            ("fake agent_metrics", "agent_metrics", {}),
            ("a fake alert", "alerts", {}),
            ("a fake action", "actions", {}),
        ]
        for label, t, extra in fakes:
            try_it(lambda t=t, extra=extra: dash.table(t).insert(sample(t, tag + "-bad", **extra)).execute())
            report(count(admin, t, tag + "-bad") == 0, f"dashboard key can NOT insert {label}")
            admin.table(t).delete().eq("agent", tag + "-bad").execute()  # clean up if it got through
        for t in TABLES:
            try_it(lambda t=t: dash.table(t).update({"agent": tag + "-hacked"}).eq("agent", tag + "-canary").execute())
            try_it(lambda t=t: dash.table(t).delete().eq("agent", tag + "-canary").execute())
            safe = count(admin, t, tag + "-canary") == 1 and count(admin, t, tag + "-hacked") == 0
            report(safe, f"dashboard key can NOT update or delete {t}")
        return 0
    finally:
        failed = [  # remove only our own test rows
            t for t in TABLES
            if try_it(lambda t=t: admin.table(t).delete().like("agent", tag + "%").execute())
        ]
        if failed:
            print(f"\nCould not remove test rows from: {', '.join(failed)} (agent names start with {tag})")
        else:
            print("\nTest rows removed.")


if __name__ == "__main__":
    code = main()
    if results:
        passed = sum(results)
        print(f"{passed}/{len(results)} checks passed.")
        if passed == len(results):
            print("RLS works: the dashboard key is read-only (plus new KILL commands).")
            code = 0
        else:
            print("Some checks FAILED. Run db/security.sql again, then this check.")
            code = 1
    sys.exit(code)