"""
Judge evaluation on labeled incidents: precision, recall, F1, latency and cost.   Owner: Alif.

A1 asks for a dataset of real JudgeContexts with a human label, and a scorer that says how
good the judge is. The dataset lives in `brain/eval_data/incidents.jsonl` (one JSON object per
line) and is built from three sources:

  1. captured from the running brain (FakeFleet on a virtual clock) — the same JudgeContext the
     engine really hands the judge
  2. the judge_bench gray-zone cases
  3. hand-written hard cases (legit bursts, Bangla/English mixed loops, injection in an email)

Usage:
    python -m brain.judge_eval --judge fallback            # offline, deterministic
    python -m brain.judge_eval --judge claude --runs 3 --write
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from brain.detectors import Finding, Level
from brain.judge import Judge, JudgeContext, fallback_verdict
from brain.state import Snapshot
from shared.config import Settings, settings
from shared.contracts import JUDGE_ACTIONS

try:
    from shared.console import print_safe
except ImportError:  # shared.console may not exist on an older checkout
    def print_safe(text: str = "") -> None:
        try:
            print(text)
        except UnicodeEncodeError:
            import sys
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            sys.stdout.write(text.encode(enc, errors="replace").decode(enc, errors="replace"))
            sys.stdout.write("\n")

log = logging.getLogger("brain.judge_eval")

DATASET = Path("brain/eval_data/incidents.jsonl")
OUT = Path("docs/research/judge-eval.md")

# Actions that mean "the breaker must stop this agent". A verdict below the
# confidence threshold still counts as an intervention decision, but only PAUSE/KILL
# are "we should have stopped it".
STOP_ACTIONS = ("PAUSE", "KILL")


# ── the dataset ─────────────────────────────────────────────────────────────
@dataclass
class Incident:
    """One labeled JudgeContext."""

    id: str
    family: str
    snapshot: dict
    finding: dict
    prompts: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    memory: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    label: dict = field(default_factory=dict)
    note: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id, "family": self.family, "snapshot": self.snapshot, "finding": self.finding,
            "prompts": self.prompts, "tools": self.tools, "memory": self.memory, "history": self.history,
            "label": self.label, "note": self.note,
        }

    @staticmethod
    def from_json(data: dict) -> "Incident":
        return Incident(
            id=str(data["id"]), family=str(data["family"]), snapshot=dict(data.get("snapshot") or {}),
            finding=dict(data.get("finding") or {}), prompts=list(data.get("prompts") or []),
            tools=list(data.get("tools") or []), memory=dict(data.get("memory") or {}),
            history=list(data.get("history") or []), label=dict(data.get("label") or {}),
            note=str(data.get("note") or ""),
        )

    def to_context(self) -> JudgeContext:
        """Rebuild the JudgeContext the engine would have handed the judge."""
        snap_fields = {f for f in Snapshot.__dataclass_fields__}
        snap = Snapshot(**{k: v for k, v in self.snapshot.items() if k in snap_fields})
        f = Finding()
        for level, rule, reason in self.finding.get("items", []):
            f.add(Level(int(level)), str(rule), str(reason))
        for rule in self.finding.get("rules", []):
            if rule not in f.rules:
                f.add(Level(int(self.finding.get("level", 1))), str(rule), str(self.finding.get("text", rule)))
        return JudgeContext(snap, f, self.prompts, self.tools, self.memory, self.history)


def load_dataset(path: Path = DATASET) -> list[Incident]:
    rows: list[Incident] = []
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(Incident.from_json(json.loads(line)))
        except Exception as exc:
            raise ValueError(f"{path}:{lineno}: bad incident line ({exc})") from exc
    return rows


def negative_families(rows: list[Incident]) -> set[str]:
    return {r.family for r in rows if not r.label.get("intervene")}


def validate_dataset(rows: list[Incident]) -> list[str]:
    """Return a list of problems. Empty list = the dataset is good."""
    errors: list[str] = []
    if len(rows) < 60:
        errors.append(f"only {len(rows)} incidents, need at least 60")
    negatives = [r for r in rows if not r.label.get("intervene")]
    if len(negatives) < 25:
        errors.append(f"only {len(negatives)} negatives, need at least 25")

    seen: set[str] = set()
    for r in rows:
        if not r.id:
            errors.append("an incident has no id")
        elif r.id in seen:
            errors.append(f"duplicate id {r.id}")
        else:
            seen.add(r.id)
        if not r.family:
            errors.append(f"{r.id}: no family")
        if not isinstance(r.label.get("intervene"), bool):
            errors.append(f"{r.id}: label.intervene must be a bool")
        ok = r.label.get("ok_actions")
        if not isinstance(ok, list) or not ok:
            errors.append(f"{r.id}: label.ok_actions must be a non-empty list")
        else:
            for a in ok:
                if a not in JUDGE_ACTIONS:
                    errors.append(f"{r.id}: ok_actions has an unknown action {a!r}")
        if not r.snapshot.get("agent_id"):
            errors.append(f"{r.id}: snapshot has no agent_id")
        if not r.finding.get("rules"):
            errors.append(f"{r.id}: finding has no rules")
        if not r.prompts:
            errors.append(f"{r.id}: no prompts")
        for p in r.prompts:
            if "prompt" not in p:
                errors.append(f"{r.id}: a prompt row has no 'prompt' key")
                break
    return errors


# ── the metrics ─────────────────────────────────────────────────────────────
def _is_stop(action: str) -> bool:
    return action in STOP_ACTIONS


def metrics_from_rows(rows: list[dict]) -> dict:
    """
    `rows` items: {"id", "family", "intervene" (bool), "action" (str)}.

    A row is a **true positive** when the label says intervene and the judge returned
    PAUSE/KILL. A **false positive** is a negative incident that got PAUSE/KILL.
    """
    tp = fp = fn = tn = 0
    invalid = 0
    for r in rows:
        action = str(r.get("action") or "")
        if action not in JUDGE_ACTIONS:
            invalid += 1
        stop = _is_stop(action)
        if r["intervene"]:
            if stop:
                tp += 1
            else:
                fn += 1
        else:
            if stop:
                fp += 1
            else:
                tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    negatives = fp + tn
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        # full precision here: the numbers are rounded for display, not for the maths
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fp / negatives if negatives else 0.0,
        "invalid_output_rate": invalid / len(rows) if rows else 0.0,
        "accuracy": (tp + tn) / len(rows) if rows else 0.0,
    }


def confusion_matrix(rows: list[dict]) -> dict:
    """{family: {action: count}} — one row per incident."""
    cm: dict[str, dict[str, int]] = {}
    for r in rows:
        cm.setdefault(r["family"], {})
        action = str(r.get("action") or "INVALID")
        cm[r["family"]][action] = cm[r["family"]].get(action, 0) + 1
    return cm


def false_positive_rate_by_family(rows: list[dict]) -> dict:
    """For each negative family: how often did the judge wrongly stop the agent?"""
    out: dict[str, dict] = {}
    for r in rows:
        if r["intervene"]:
            continue
        fam = out.setdefault(r["family"], {"negatives": 0, "false_positives": 0})
        fam["negatives"] += 1
        if _is_stop(str(r.get("action") or "")):
            fam["false_positives"] += 1
    for fam, d in out.items():
        d["rate"] = d["false_positives"] / d["negatives"] if d["negatives"] else 0.0
    return out


# ── running the judge over the dataset ──────────────────────────────────────
def run_eval(cfg: Settings, path: Path = DATASET, judge: str = "fallback", runs: int = 1,
             only: Optional[str] = None) -> dict:
    """Run every incident through the judge and score the result."""
    rows = load_dataset(path)
    if only:
        rows = [r for r in rows if only in r.family]
    judge_cfg = cfg
    if judge != cfg.judge_provider:
        from dataclasses import replace

        judge_cfg = replace(cfg, judge_provider=judge)
    j = Judge(judge_cfg)
    out_rows: list[dict] = []
    latencies: list[float] = []
    costs: list[float] = []
    for inc in rows:
        ctx = inc.to_context()
        verdicts = []
        for _ in range(max(1, runs)):
            v = j.judge(ctx)
            verdicts.append(v)
        last = verdicts[-1]
        latencies.extend(v.latency_ms for v in verdicts)
        costs.extend(v.cost_usd for v in verdicts)
        out_rows.append({
            "id": inc.id, "family": inc.family, "note": inc.note,
            "intervene": bool(inc.label.get("intervene")),
            "ok_actions": list(inc.label.get("ok_actions") or []),
            "action": last.action, "confidence": last.confidence, "pattern": last.pattern,
            "source": last.source, "reason": last.reason, "suggested_fix": last.suggested_fix,
            "latency_ms": last.latency_ms, "cost_usd": last.cost_usd,
            "actions_seen": sorted({v.action for v in verdicts}),
        })
    metrics = metrics_from_rows(out_rows)
    p50 = round(statistics.median(latencies), 1) if latencies else 0.0
    p95 = round(sorted(latencies)[min(len(latencies) - 1, int(0.95 * len(latencies)))], 1) if latencies else 0.0
    metrics.update({
        "n_incidents": len(out_rows),
        "judge": j.provider,
        "model": judge_cfg.claude_model if j.provider == "claude" else j.provider,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "cost_per_verdict_usd": round(statistics.mean(costs), 8) if costs else 0.0,
        "cost_total_usd": round(sum(costs), 8),
        "confusion": confusion_matrix(out_rows),
        "false_positive_rate_by_family": false_positive_rate_by_family(out_rows),
        "rows": out_rows,
    })
    return metrics


# ── markdown ────────────────────────────────────────────────────────────────
def markdown(out: dict) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    m = out
    lines = [
        f"Run: {stamp} · judge `{m['judge']}` · model `{m['model']}` · incidents **{m['n_incidents']}**",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Precision | {m['precision']:.3f} |",
        f"| Recall | {m['recall']:.3f} |",
        f"| F1 | {m['f1']:.3f} |",
        f"| Accuracy | {m['accuracy']:.3f} |",
        f"| False-positive rate | {m['false_positive_rate']:.3f} |",
        f"| Invalid-output rate | {m['invalid_output_rate']:.3f} |",
        f"| Latency p50 | {m['latency_p50_ms']:.0f} ms |",
        f"| Latency p95 | {m['latency_p95_ms']:.0f} ms |",
        f"| $ per verdict | {m['cost_per_verdict_usd']:.6f} |",
        "",
        "### Confusion matrix (family → action)",
        "",
    ]
    actions = list(JUDGE_ACTIONS) + ["INVALID"]
    lines.append("| family | " + " | ".join(actions) + " |")
    lines.append("|---" * (len(actions) + 1) + "|")
    for family, counts in sorted(m["confusion"].items()):
        lines.append(f"| {family} | " + " | ".join(str(counts.get(a, 0)) for a in actions) + " |")

    lines += ["", "### False-positive rate per negative family", "", "| family | negatives | false positives | rate |", "|---|---|---|---|"]
    for family, d in sorted(m["false_positive_rate_by_family"].items()):
        lines.append(f"| {family} | {d['negatives']} | {d['false_positives']} | {d['rate']:.3f} |")

    lines += ["", "### Misjudged incidents", ""]
    wrong = [r for r in m["rows"]
             if (r["intervene"] and r["action"] not in STOP_ACTIONS)
             or (not r["intervene"] and r["action"] in STOP_ACTIONS)]
    if not wrong:
        lines.append("None — every incident was judged correctly.")
    else:
        lines += ["| id | family | expected | got | reason |", "|---|---|---|---|---|"]
        for r in wrong:
            expected = "PAUSE/KILL" if r["intervene"] else "/".join(r["ok_actions"])
            lines.append(f"| {r['id']} | {r['family']} | {expected} | {r['action']} {r['confidence']:.2f} | {r['reason']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m brain.judge_eval")
    p.add_argument("--judge", default="fallback", help="fallback (default) | auto | claude | gemini")
    p.add_argument("--runs", type=int, default=1, help="calls per incident (use 3+ for Claude)")
    p.add_argument("--dataset", default=str(DATASET), help="path to the incidents file")
    p.add_argument("--family", default=None, help="only run incidents whose family contains this text")
    p.add_argument("--write", action="store_true", help=f"replace the results block in {OUT}")
    args = p.parse_args()
    logging.basicConfig(level=logging.ERROR)
    path = Path(args.dataset)

    rows = load_dataset(path)
    errors = validate_dataset(rows)
    if errors:
        print(f"WARNING: the dataset has {len(errors)} problem(s):")
        for e in errors:
            print(f"   - {e}")

    out = run_eval(settings, path, judge=args.judge, runs=max(1, args.runs), only=args.family)
    table = markdown(out)
    _print(table)
    if args.write:
        text = OUT.read_text(encoding="utf-8")
        begin, end = "<!-- eval:start -->", "<!-- eval:end -->"
        if begin not in text or end not in text:
            print(f"WARNING: {OUT} has no eval markers; nothing written.")
        else:
            head, _, rest = text.partition(begin)
            _, _, tail = rest.partition(end)
            OUT.write_text(f"{head}{begin}\n{table}{end}{tail}", encoding="utf-8")
            print(f"written to {OUT}")


def _print(text: str) -> None:
    """Print on Windows too: the default cp1252 console cannot encode every character we use."""
    print_safe(text)


if __name__ == "__main__":
    main()
