"""
The tamper-evident audit log (CONTRACTS §6, B7).

An audit log that can be edited after the fact is not an audit log. This one is
**hash-chained**: every entry carries the hash of the entry before it, so an
edit in the middle does not just change that entry — it breaks every link after
it. Deleting an entry breaks the chain the same way. That is the whole
governance story: an operator can prove that the record of what the brain did
has not been touched after the fact.

Three ideas carry the module:

- **the chain is append-only and ordered.** `seq` is the position in the chain
  and it starts at 1. A gap in the sequence is itself a sign of tampering, so
  the verifier checks the positions as well as the hashes;
- **the hash rule lives in the contract** (`shared/contracts.py`), not here.
  The mock and the real API must compute the same hash, or a client that
  verifies one would reject the other — and a real chain the mock cannot
  reproduce is a chain nobody can test against;
- **everything that happened is in it.** A runaway paused by the rules, a
  PAUSE by a human, a `TOOL_DENY` by the policy, an `AUTO_HEAL`. The `kind`
  says which of the three it was.

The chain is only as good as its coverage, so the writer is called from **every**
place a decision or a human action is recorded — the engine's `_apply`, the
command path, the auto-heal, the tool gate, the cascade. A gap in the coverage
would be a gap in the proof, and a proof with holes in it is a decoration.

Behind `CS_AUDIT_ENABLED` (off by default): with the flag off nothing is
chained and the endpoint says so, without failing.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Optional

from shared.contracts import (AUDIT_GENESIS, AuditRow, audit_entry, audit_hash, audit_verify_result,
                              audit_view)

log = logging.getLogger("brain.audit")

# The kinds of thing that goes into the chain, and how to tell them apart.
#
# A **decision** is what the brain decided on its own. A **human** action is
# what a person did. A **policy** action is what the tool gate did — the gate
# is the policy acting, not the brain deciding and not a person clicking.
KIND_DECISION = "decision"
KIND_HUMAN = "human"
KIND_POLICY = "policy"

# The actors that mean "a person did this". Everything else is the brain, the
# rules or the policy.
HUMAN_ACTORS = ("human", "dashboard", "mcp", "operator", "cli")


def kind_for(actor: str, action: str = "") -> str:
    """
    The kind of thing an entry is, from who did it.

    The **actor** is the honest signal: the brain says what it is (`rules`,
    `brain:autoheal`, `brain:cascade`), a person says who they are (`human`,
    `dashboard`, `mcp`). The tool gate's actor is `policy`, and that is its own
    kind because a denied call is neither a brain decision nor a person's click.
    """
    who = str(actor or "").strip().lower()
    if who == "policy":
        return KIND_POLICY
    if who in HUMAN_ACTORS:
        return KIND_HUMAN
    return KIND_DECISION


# ── the chain ──────────────────────────────────────────────────────────────
def read_chain(store, limit: int = 1000) -> list[dict]:
    """The whole chain, oldest first."""
    try:
        rows = store.audit_entries(limit=limit)
    except Exception:
        log.exception("could not read the audit chain")
        return []
    return [_as_entry(row) for row in rows or []]


def _as_entry(row: dict) -> dict:
    """A stored row as the contract's entry shape."""
    return audit_entry(
        seq=int(row.get("seq") or 0),
        agent_id=str(row.get("agent_id") or ""),
        kind=str(row.get("kind") or KIND_DECISION),
        actor=str(row.get("actor") or ""),
        action=str(row.get("action") or ""),
        reason=str(row.get("reason") or ""),
        prev_hash=str(row.get("prev_hash") or AUDIT_GENESIS),
        hash=str(row.get("hash") or ""),
        created_at=row.get("created_at"),
    )


def next_seq(store) -> int:
    """The position the next entry will take.

    It is one past the **highest** sequence number that exists — not the
    number of entries. If an entry was deleted from the middle, the count and
    the highest position would differ, and using the count would silently
    reuse a position. Using the highest one leaves the gap visible, which is
    what a gap is for.
    """
    try:
        head = store.audit_head()
    except Exception:
        log.exception("could not read the head of the audit chain")
        return 1
    if not head:
        return 1
    try:
        return int(head.get("seq") or 0) + 1
    except (TypeError, ValueError):
        return 1


def head_hash(store) -> str:
    """The hash of the last entry — or the genesis hash when the chain is empty."""
    try:
        head = store.audit_head()
    except Exception:
        log.exception("could not read the head of the audit chain")
        return AUDIT_GENESIS
    if not head:
        return AUDIT_GENESIS
    return str(head.get("hash") or AUDIT_GENESIS)


def append(store, agent_id: str = "", actor: str = "", action: str = "", reason: str = "",
           kind: str = "", seq: Optional[int] = None, now: Optional[float] = None) -> Optional[dict]:
    """
    Append one link to the chain.

    Returns the entry that was written, or `None` when nothing was written.
    A chain that cannot be written must not take the tick with it — the
    decision it was recording has already happened, and losing the record of
    a pause because the record could not be written would be a bug in the
    brain, not in the agent.

    The caller may pass the `seq` and `prev_hash` it already knows, so that a
    caller writing several links in a row does not read the head back each
    time. When it does not, they are read here.
    """
    entry_kind = kind or kind_for(actor, action)
    position = int(seq) if seq is not None else next_seq(store)
    prev = head_hash(store) if seq is None else _prev_for(store, position)
    entry = audit_entry(seq=position, agent_id=agent_id, kind=entry_kind, actor=actor,
                        action=action, reason=reason, prev_hash=prev,
                        created_at=now if now is not None else None)
    entry["hash"] = audit_hash(entry)
    try:
        store.insert_audit(AuditRow(
            seq=entry["seq"], agent_id=entry["agent_id"], kind=entry["kind"],
            actor=entry["actor"], action=entry["action"], reason=entry["reason"],
            prev_hash=entry["prev_hash"], hash=entry["hash"]))
    except Exception:
        log.exception("could not append to the audit chain")
        return None
    return entry


def _prev_for(store, position: int) -> str:
    """The hash the entry at `position` must link to."""
    try:
        rows = store.audit_entries(limit=1, after_seq=max(0, position - 1))
    except Exception:
        log.exception("could not read the audit chain")
        return AUDIT_GENESIS
    if not rows:
        return AUDIT_GENESIS
    return str(rows[0].get("hash") or AUDIT_GENESIS)


# ── the one place every decision goes through ──────────────────────────────
def record_action(store, agent_id: str = "", action: str = "", actor: str = "", reason: str = "",
                  kind: str = "", enabled: bool = False, usd_saved: float = 0.0,
                  tokens_saved: int = 0) -> Optional[dict]:
    """
    Write the action to the audit log **and** to the chain.

    Every decision and every human action in the system already goes through
    `store.insert_action` — the brain's `_apply`, the command path, the
    auto-heal, the tool gate, the cascade. So this is the one place the chain
    has to be written from, and putting it here is what makes the chain
    *complete* rather than "the decisions somebody remembered to chain".

    The money saved is **not** part of the hash. The chain says *what happened*;
    the ROI estimate is a number that is recomputed on every read of the
    dashboard, and a chain that broke every time the estimate moved would be a
    chain that could never be verified.

    With the flag off, only the action is written: the behaviour is exactly
    what it was before the chain existed.
    """
    from shared.contracts import ActionRow

    try:
        store.insert_action(ActionRow(agent_id, action, actor, reason, usd_saved, tokens_saved))
    except Exception:
        log.exception("could not write the action %s for %s", action, agent_id)
        return None
    if not enabled:
        return None
    return append(store, agent_id=agent_id, actor=actor, action=action, reason=reason, kind=kind)


# ── the verification ───────────────────────────────────────────────────────
def verify(entries: list[dict]) -> dict:
    """
    Check the chain and say **which** entry broke it.

    Three things can be wrong, and they are different problems:

    - a **broken link** — an entry's `prev_hash` is not the hash of the entry
      before it. Either the content was edited, or an entry was deleted;
    - a **broken hash** — an entry's own `hash` does not match its content.
      The content was edited;
    - a **gap** — the sequence numbers do not run 1, 2, 3…. An entry was
      deleted.

    "Your log is broken" without a position is not an answer an operator can
    act on, so `broken_at` names the entry.
    """
    entries = list(entries or [])
    if not entries:
        # An empty chain verifies. Nothing has happened yet — that is a fact.
        return audit_verify_result(ok=True, entries=0, head_hash=AUDIT_GENESIS,
                                   broken_at=None, reason="the chain is empty")

    prev = AUDIT_GENESIS
    expected_seq = 1
    for entry in entries:
        seq = int(entry.get("seq") or 0)
        if seq != expected_seq:
            return audit_verify_result(
                ok=False, entries=len(entries), head_hash=str(entry.get("hash") or ""),
                broken_at=seq or expected_seq,
                reason=f"entry {seq} is out of sequence — the chain jumps from {expected_seq - 1} to {seq}")
        if str(entry.get("prev_hash") or "") != prev:
            return audit_verify_result(
                ok=False, entries=len(entries), head_hash=str(entry.get("hash") or ""),
                broken_at=seq,
                reason=f"entry {seq} does not link to the entry before it — "
                       f"it says {entry.get('prev_hash')!r}, the previous entry is {prev!r}")
        recomputed = audit_hash(entry)
        if str(entry.get("hash") or "") != recomputed:
            return audit_verify_result(
                ok=False, entries=len(entries), head_hash=str(entry.get("hash") or ""),
                broken_at=seq,
                reason=f"entry {seq} has been changed — its hash is {entry.get('hash')!r}, "
                       f"but its content hashes to {recomputed!r}")
        prev = str(entry.get("hash") or "")
        expected_seq += 1

    return audit_verify_result(ok=True, entries=len(entries), head_hash=prev,
                               broken_at=None, reason="the chain is intact")


def chain_view(store, limit: int = 200, enabled: bool = True,
               as_of: Optional[float] = None) -> dict:
    """
    The chain and what the verification says about it.

    The verification runs on the chain that is actually served — not on a
    separate copy — so the endpoint can never say "valid" about a chain the
    reader cannot check.
    """
    entries = read_chain(store, limit=limit)
    result = verify(entries)
    return audit_view(entries=entries, head_hash=result.get("head_hash") or "",
                      valid=bool(result.get("ok")), broken_at=result.get("broken_at"),
                      enabled=enabled, as_of=as_of)


# ── the CLI ────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    """
    `python -m brain.audit verify` — prove the chain has not been edited.

    Exits **non-zero** on a broken chain, so it can be a CI job or a cron
    check. The exit code is the point of the command: a verify command that
    always exits 0 is a command nobody can trust.
    """
    parser = argparse.ArgumentParser(
        prog="python -m brain.audit",
        description="Verify the tamper-evident audit chain.")
    parser.add_argument("command", nargs="?", default="verify",
                        choices=["verify", "show"], help="verify the chain, or show it")
    parser.add_argument("--db", default=None, help="the database file (default: the configured one)")
    parser.add_argument("--limit", type=int, default=1000, help="how many entries to read")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    from shared.config import load_settings
    from shared.store import LocalStore

    cfg = load_settings()
    try:
        store = LocalStore(args.db or cfg.local_db_path)
    except Exception as exc:
        print(f"could not open the store: {exc}", file=sys.stderr)
        return 1

    if args.command == "show":
        entries = read_chain(store, limit=args.limit)
        for entry in entries:
            print(f"{entry['seq']:>6}  {entry['kind']:<8} {entry['action']:<14} "
                  f"{entry['actor']:<16} {entry['agent_id']:<10} {entry['hash'][:12]}")
        print(f"{len(entries)} entries", file=sys.stderr)
        return 0

    result = verify(read_chain(store, limit=args.limit))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["ok"]:
            print(f"the audit chain is intact: {result['entries']} entries, "
                  f"head {result['head_hash']}")
        else:
            print(f"the audit chain is BROKEN at entry {result['broken_at']}: {result['reason']}",
                  file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
