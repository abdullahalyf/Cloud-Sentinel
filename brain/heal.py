"""
Auto-heal: the judge proposes a patch, a confident one is applied, the rest waits for a human.   Owner: Alif.

A malfunctioning agent usually has one bad belief in its memory ("the orders API returned 500 —
retry until success") and one bad tool policy (calling `issue_refund` in a loop). Fixing the belief
is cheaper than restarting the agent, and much cheaper than letting it burn money while stuck.

So the judge's structured output may carry a `patch`:

    {"memory": [{"op": "set"|"remove", "key": str, "value": any}]}
    {"tool_policy": {"tool": str, "action": "deny"|"approval"}}

This module decides whether a patch is SAFE and then either applies it or files it as a proposal
for a human. The safety rules are deliberately strict — a heal that breaks an agent is worse than
no heal at all, because the agent comes back believing it is fixed:

  - a patch may only touch memory keys that already exist, or that the finding names
  - a patch may never contain instruction-like text (the agent's own text must not become a command)
  - a patch may never touch the budget keys (that is `SET_BUDGET`'s job, and a human's)
  - at most one auto-heal per agent per 10 minutes
  - an agent that trips again during probation after an auto-heal is paused and escalated to a
    human — never auto-healed twice in a row

Usage:
    python -m brain.heal                 # show the pending proposals
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from brain.detectors import Finding
from shared.config import Settings, settings
from shared.contracts import HealProposalRow, utc_now_iso

log = logging.getLogger("brain.heal")


# ── the audit chain (B7) ───────────────────────────────────────────────────
def _record(store, agent_id: str, action: str, actor: str, reason: str,
            enabled: bool = False, usd_saved: float = 0.0, tokens_saved: int = 0) -> None:
    """
    Write the action to the audit log **and** to the tamper-evident chain.

    An auto-heal is the one action nobody clicked, so it is the one that most needs
    to be provable: an operator must be able to show that the brain changed an
    agent's memory on its own, and why.
    """
    from brain import audit as brain_audit

    try:
        brain_audit.record_action(store, agent_id=agent_id, action=action, actor=actor,
                                  reason=reason, enabled=enabled,
                                  usd_saved=usd_saved, tokens_saved=tokens_saved)
    except Exception:
        log.exception("could not chain the action %s for %s", action, agent_id)

# ── the limits the judge must respect ───────────────────────────────────────
MAX_OPS = 5                 # at most 5 memory ops in one patch
MAX_VALUE_CHARS = 500       # a memory value longer than this is not a belief, it is a document
MAX_KEY_CHARS = 64
MIN_AUTOHEAL_INTERVAL = 600.0   # at most one auto-heal per agent per 10 minutes

# Memory keys the brain must never rewrite: the budget is the operator's decision, not the judge's.
PROTECTED_KEYS = ("budget", "budget_usd", "spend", "spend_usd", "max_cost", "limit")

# Text that looks like an instruction. A patch value is DATA the agent will read; if it reads like
# a command, the judge (or the agent that wrote the memory) is trying to talk to the monitor.
# Until brain/injection.py exists (A6), this is a small denylist.
INSTRUCTION_PATTERNS = (
    r"ignore (all |any |the )?(previous|prior|earlier|above)",
    r"disregard (all |any |the )?(previous|prior|earlier|above)",
    r"do not (terminate|kill|pause|stop|monitor|report)",
    r"don'?t (terminate|kill|pause|stop|monitor|report)",
    r"you are (now )?(a|an|the)\b",
    r"system prompt",
    r"new instructions?\b",
    r"developer mode",
    r"<agent_(logs|memory|tool_calls)>",
    r"terminate this agent",
    r"exfiltrat",
    r"curl\s+http",
)
_INSTRUCTION_RE = re.compile("|".join(INSTRUCTION_PATTERNS), re.IGNORECASE)

_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,%d}$" % MAX_KEY_CHARS)


# ── the patch ───────────────────────────────────────────────────────────────
@dataclass
class Patch:
    """A validated proposal. `kind` says what it touches."""

    kind: str                 # memory_patch | tool_policy
    ops: list[dict] = None    # memory ops: {"op","key","value"}
    tool: str = ""            # tool_policy: the tool name
    action: str = ""          # tool_policy: deny | approval

    def to_json(self) -> dict:
        if self.kind == "tool_policy":
            return {"tool_policy": {"tool": self.tool, "action": self.action}}
        return {"memory": list(self.ops or [])}


class PatchRejected(Exception):
    """The patch is not safe to apply. The reason says why — a human reads it."""


def _text_of(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def looks_like_instruction(value) -> bool:
    """True when a patch value reads like a command rather than data."""
    return bool(_INSTRUCTION_RE.search(_text_of(value)))


def _named_keys(finding: Optional[Finding]) -> set[str]:
    """
    The keys the finding names.

    A finding's text and reasons mention the key that keeps the agent going ("order_4471"), so a
    patch may create that key even if it is not in the memory yet.
    """
    out: set[str] = set()
    if finding is None:
        return out
    blob = " ".join([finding.text or "", *finding.reasons])
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.\-]{2,63}", blob):
        out.add(token)
    return out


def validate(raw: Optional[dict], memory: Optional[dict], finding: Optional[Finding] = None) -> Patch:
    """
    Turn the judge's raw `patch` into a safe Patch, or raise PatchRejected with the reason.

    The rules (see the module docstring):
      - only `memory` or `tool_policy`
      - memory: top-level keys only, at most 5 ops, values ≤ 500 characters
      - a key must exist in the memory or be named by the finding
      - a value must not look like an instruction
      - the budget keys are never touched
    """
    if not isinstance(raw, dict) or not raw:
        raise PatchRejected("no patch in the verdict")
    if "tool_policy" in raw:
        return _validate_tool_policy(raw["tool_policy"])
    if "memory" in raw:
        return _validate_memory(raw["memory"], memory or {}, finding)
    raise PatchRejected("the patch touches neither memory nor tool_policy")


def _validate_tool_policy(spec) -> Patch:
    if not isinstance(spec, dict):
        raise PatchRejected("tool_policy must be an object")
    tool = str(spec.get("tool") or "").strip()
    action = str(spec.get("action") or "").strip().lower()
    if not tool:
        raise PatchRejected("tool_policy needs a tool name")
    if len(tool) > MAX_KEY_CHARS:
        raise PatchRejected("the tool name is too long")
    if action not in ("deny", "approval"):
        raise PatchRejected("tool_policy.action must be deny or approval")
    return Patch("tool_policy", tool=tool, action=action)


def _validate_memory(ops, memory: dict, finding: Optional[Finding]) -> Patch:
    if not isinstance(ops, list):
        raise PatchRejected("memory must be a list of ops")
    if not ops:
        raise PatchRejected("the memory patch has no ops")
    if len(ops) > MAX_OPS:
        raise PatchRejected(f"a patch may touch at most {MAX_OPS} memory keys")
    named = _named_keys(finding)
    clean: list[dict] = []
    for op in ops:
        if not isinstance(op, dict):
            raise PatchRejected("each memory op must be an object")
        action = str(op.get("op") or "set").strip().lower()
        if action not in ("set", "remove"):
            raise PatchRejected("a memory op must be set or remove")
        key = str(op.get("key") or "").strip()
        if not key:
            raise PatchRejected("a memory op needs a key")
        if len(key) > MAX_KEY_CHARS or not _KEY_RE.match(key):
            raise PatchRejected(f"the memory key {key!r} is not a valid key")
        if key.lower() in PROTECTED_KEYS:
            raise PatchRejected(f"the brain never rewrites {key!r} — that is SET_BUDGET's job")
        if key not in memory and key not in named:
            raise PatchRejected(f"the patch touches {key!r}, which is not in the agent's memory "
                                "and the finding does not name it")
        if action == "set":
            value = op.get("value")
            if len(_text_of(value)) > MAX_VALUE_CHARS:
                raise PatchRejected(f"the value for {key!r} is longer than {MAX_VALUE_CHARS} characters")
            if looks_like_instruction(value):
                raise PatchRejected(f"the value for {key!r} reads like an instruction, not a belief")
            clean.append({"op": "set", "key": key, "value": value})
        else:
            clean.append({"op": "remove", "key": key})
    return Patch("memory_patch", ops=clean)


def apply_to_memory(memory: Optional[dict], patch: Patch) -> dict:
    """The new memory content, after the patch. Never mutates the input."""
    out = dict(memory or {})
    for op in patch.ops or []:
        if op["op"] == "remove":
            out.pop(op["key"], None)
        else:
            out[op["key"]] = op["value"]
    return out


# ── the guard rails around applying ─────────────────────────────────────────
def may_autoheal(cfg: Settings, agent_id: str, last_autoheal: dict[str, float], now: float) -> bool:
    """
    May this agent be auto-healed right now?

    Two rules: auto-heal is switched on, and this agent has not been auto-healed in the last
    10 minutes (a second heal in a row usually means the first one did not work).
    """
    if not cfg.autoheal:
        return False
    last = last_autoheal.get(agent_id)
    return last is None or (now - last) >= MIN_AUTOHEAL_INTERVAL


def is_stale(base_version: int, current_version: int) -> bool:
    """
    True when the agent's memory moved on since the judge looked at it.

    The patch was written against version N. If the memory is now at N+1, applying it would
    overwrite whatever changed — so the proposal expires and a human decides.
    """
    return int(base_version or 0) < int(current_version or 0)


# ── the flow the engine calls ───────────────────────────────────────────────
def propose(store, agent_id: str, patch: Patch, confidence: float, verdict_id: int,
            base_version: int, reason: str) -> int:
    """File a patch as a pending proposal for a human."""
    pid = store.insert_heal_proposal(HealProposalRow(
        agent_id, patch.kind, patch.to_json(), confidence, "pending", verdict_id, base_version, reason))
    log.warning("heal proposal %s for %s: %s (%s, confidence %.2f)", pid, agent_id, patch.kind,
                reason or "no reason", confidence)
    return pid


def decide(store, proposal_id: int, decision: str, decided_by: str, reason: str = "",
           audit_enabled: bool = False) -> dict:
    """
    Apply or reject a pending proposal.

    Applying writes the patch into the agent's memory (as `brain:autoheal` or the human's actor),
    marks the proposal `applied` and records an AUTO_HEAL action. A proposal whose base version is
    stale becomes `expired` instead — a human decides what to do with the newer memory.
    """
    decision = (decision or "").strip().lower()
    if decision not in ("apply", "reject"):
        raise ValueError("decision must be apply or reject")
    proposal = store.get_heal_proposal(proposal_id)
    if proposal is None:
        raise LookupError(f"heal proposal {proposal_id} not found")
    if proposal["status"] != "pending":
        raise ValueError(f"heal proposal {proposal_id} already decided: {proposal['status']}")
    agent_id = proposal["agent_id"]
    memory = store.get_memory(agent_id) or {}
    current_version = int(memory.get("version") or 0)
    if is_stale(proposal["base_version"], current_version):
        store.decide_heal_proposal(proposal_id, "expired", decided_by,
                                   reason or f"the memory moved on (v{current_version} > v{proposal['base_version']})")
        log.warning("heal proposal %s for %s expired — the memory moved on", proposal_id, agent_id)
        return store.get_heal_proposal(proposal_id)

    if decision == "reject":
        # a rejected patch changes nothing: the agent stays paused, the memory stays as it was
        store.decide_heal_proposal(proposal_id, "rejected", decided_by, reason or "rejected")
        log.warning("heal proposal %s for %s rejected by %s", proposal_id, agent_id, decided_by)
        return store.get_heal_proposal(proposal_id)

    patch_data = proposal.get("patch") or {}
    if proposal["kind"] == "memory_patch":
        patch = Patch("memory_patch", ops=list(patch_data.get("memory") or []))
        content = apply_to_memory(memory.get("content") or {}, patch)
        store.write_memory(agent_id, content, decided_by, reason or f"heal applied: {proposal['reason']}",
                           base_version=None)
    else:
        # a tool_policy patch changes the policy file, not the memory — the engine applies it
        patch = Patch("tool_policy", tool=str((patch_data.get("tool_policy") or {}).get("tool") or ""),
                      action=str((patch_data.get("tool_policy") or {}).get("action") or ""))
    store.decide_heal_proposal(proposal_id, "applied", decided_by, reason or "applied")
    _record(store, agent_id, "AUTO_HEAL", decided_by,
            reason or f"heal applied: {proposal['reason']}", enabled=audit_enabled)
    log.warning("heal proposal %s applied to %s by %s", proposal_id, agent_id, decided_by)
    return store.get_heal_proposal(proposal_id)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m brain.heal")
    p.add_argument("--agent", default=None, help="only this agent")
    p.add_argument("--status", default="pending", help="pending|applied|rejected|expired")
    args = p.parse_args()
    logging.basicConfig(level=logging.ERROR)

    from shared.store import get_store

    store = get_store()
    rows = store.list_heal_proposals(status=args.status, agent_id=args.agent, limit=100)
    print(f"{len(rows)} heal proposal(s) with status {args.status}")
    for r in rows:
        print(f"  #{r['id']} {r['agent_id']} {r['kind']} confidence {r['confidence']:.2f} — {r['reason']}")
        print(f"      {json.dumps(r.get('patch') or {}, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
