"""
Judge evaluation for CI: every Claude model, real numbers, one PR.   Owner: Alif.

**The problem this solves.** `docs/research/pitch-numbers.md` has a section
that says the Claude judge's latency and cost have *never been measured*,
because no API key was available when the file was written. That is honest,
but it is also an unfinished job: the numbers are one `ANTHROPIC_API_KEY` away.

**The trap.** `brain/tests/test_evidence.py` has a test called
`test_the_pack_does_not_quote_a_claude_judge_number` that **fails the build**
if the pack quotes a Claude cost or latency. That test is right — a pack that
quotes an unmeasured number is worse than a pack with a hole in it. But it
means the pack can never grow a Claude number by hand: the moment one appears,
CI says "where did that come from?"

So the numbers have to be written by the machine that measured them. This
module is that machine:

  1. run `judge_eval` for every Claude model, `--runs 3`;
  2. write the measured numbers into the pack, between two markers;
  3. replace the "needs a human" note with the numbers that were measured;
  4. write a machine-readable JSON next to it, so a reader can check the
     markdown against the raw run.

**The honesty rule.** This module never invents a number. If the API key is
missing, or a model call fails, the run **fails** — it does not fall back to
the offline judge and quietly write "0 ms" as if it were Claude's latency.
The fallback judge's numbers are real, but they are *the fallback judge's*
numbers, and putting them under a "Claude" heading is exactly the lie the
evidence test exists to catch.

**Usage:**

    python -m brain.judge_eval_ci --runs 3                 # every Claude model
    python -m brain.judge_eval_ci --runs 3 --model claude-haiku-5-5
    python -m brain.judge_eval_ci --runs 3 --json-only     # CI's first pass
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from brain.judge_eval import DATASET, markdown, run_eval, validate_dataset, load_dataset
from shared.config import Settings, load_settings
from shared.pricing import PRICES_PER_MTOK

try:
    from shared.console import print_safe
except ImportError:  # pragma: no cover - the console helper may be missing on old checkouts
    def print_safe(text: str = "") -> None:
        try:
            print(text)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            sys.stdout.write(text.encode(enc, errors="replace").decode(enc, errors="replace"))
            sys.stdout.write("\n")

PACK = Path("docs/research/pitch-numbers.md")
JSON_OUT = Path("docs/research/judge-eval-ci.json")

# The Claude models the judge can be pointed at, cheapest first. The order is
# the order the table is printed in: a reader wants the cheap row first.
CLAUDE_MODELS = [
    "claude-haiku-5-5",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-fable-5-1",
]

# The markers the machine-written numbers live between. Everything outside
# them is hand-written and is never touched.
PACK_BEGIN = "<!-- claude-judge:start -->"
PACK_END = "<!-- claude-judge:end -->"


@dataclass
class ModelResult:
    """What one model's run produced."""

    model: str
    ok: bool = False
    error: str = ""
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    accuracy: float = 0.0
    false_positive_rate: float = 0.0
    invalid_output_rate: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    cost_per_verdict_usd: float = 0.0
    cost_total_usd: float = 0.0
    n_incidents: int = 0
    fallback_used: bool = False
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "model": self.model, "ok": self.ok, "error": self.error,
            "precision": round(self.precision, 4), "recall": round(self.recall, 4),
            "f1": round(self.f1, 4), "accuracy": round(self.accuracy, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "invalid_output_rate": round(self.invalid_output_rate, 4),
            "latency_p50_ms": self.latency_p50_ms, "latency_p95_ms": self.latency_p95_ms,
            "cost_per_verdict_usd": self.cost_per_verdict_usd,
            "cost_total_usd": self.cost_total_usd,
            "n_incidents": self.n_incidents, "fallback_used": self.fallback_used,
            "duration_s": round(self.duration_s, 2),
        }


@dataclass
class RunReport:
    """The whole CI run: every model, plus the question of whether it was real."""

    started_at: str = ""
    runs_per_incident: int = 3
    key_present: bool = False
    models: list[ModelResult] = field(default_factory=list)

    @property
    def measured(self) -> list[ModelResult]:
        """The runs that really called Claude."""
        return [m for m in self.models if m.ok and not m.fallback_used]

    @property
    def degraded(self) -> list[ModelResult]:
        """The runs that silently fell back to the offline judge."""
        return [m for m in self.models if m.ok and m.fallback_used]

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "runs_per_incident": self.runs_per_incident,
            "key_present": self.key_present,
            "models": [m.to_dict() for m in self.models],
        }


# ── running one model ──────────────────────────────────────────────────────
def run_model(model: str, runs: int = 3, dataset: Path = DATASET,
              cfg: Optional[Settings] = None) -> ModelResult:
    """
    Run the judge over the dataset with one Claude model.

    The model is a *setting*, so this is a settings swap, not a code path.
    If the provider cannot be reached the judge falls back to the offline
    scorer — and this function **notices**, because a fallback result has
    `judge == "fallback"`, and a fallback result reported as Claude is a lie.
    """
    result = ModelResult(model=model)
    started = time.time()
    base = cfg or load_settings()
    from dataclasses import replace

    model_cfg = replace(base, judge_provider="claude", claude_model=model)
    try:
        out = run_eval(model_cfg, dataset, judge="claude", runs=runs)
    except Exception as exc:  # a provider error must not look like a measurement
        result.error = f"{type(exc).__name__}: {exc}"
        result.duration_s = time.time() - started
        return result

    result.ok = True
    result.fallback_used = (out.get("judge") != "claude")
    result.precision = out.get("precision", 0.0)
    result.recall = out.get("recall", 0.0)
    result.f1 = out.get("f1", 0.0)
    result.accuracy = out.get("accuracy", 0.0)
    result.false_positive_rate = out.get("false_positive_rate", 0.0)
    result.invalid_output_rate = out.get("invalid_output_rate", 0.0)
    result.latency_p50_ms = out.get("latency_p50_ms", 0.0)
    result.latency_p95_ms = out.get("latency_p95_ms", 0.0)
    result.cost_per_verdict_usd = out.get("cost_per_verdict_usd", 0.0)
    result.cost_total_usd = out.get("cost_total_usd", 0.0)
    result.n_incidents = out.get("n_incidents", 0)
    result.duration_s = time.time() - started
    return result


def run_all(models: Optional[list[str]] = None, runs: int = 3,
            dataset: Path = DATASET, cfg: Optional[Settings] = None) -> RunReport:
    """Run every Claude model, in order, and report what happened."""
    from datetime import datetime, timezone

    report = RunReport(
        started_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        runs_per_incident=runs,
        key_present=bool((cfg or load_settings()).anthropic_api_key),
    )
    for model in (models or CLAUDE_MODELS):
        report.models.append(run_model(model, runs=runs, dataset=dataset, cfg=cfg))
    return report


# ── the machine-written block ───────────────────────────────────────────────
def block_markdown(report: RunReport) -> str:
    """The table that replaces the 'needs a human' note in the pack."""
    lines = [
        PACK_BEGIN,
        "",
        "**Measured on the real Claude API** (CI, "
        f"{report.started_at}, {report.runs_per_incident} runs per incident, "
        "every incident in the labelled set):",
        "",
        "| Model | Precision | Recall | F1 | Accuracy | Latency p50 / p95 | $ per verdict | Verdicts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in report.measured:
        lines.append(
            f"| `{m.model}` | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} | "
            f"{m.accuracy:.3f} | {m.latency_p50_ms:.0f} ms / {m.latency_p95_ms:.0f} ms | "
            f"{m.cost_per_verdict_usd:.6f} | {m.n_incidents * report.runs_per_incident} |"
        )
    if not report.measured:
        lines.append("| _no model was measured_ | | | | | | | |")
    lines += [
        "",
        "**Reproduce:**",
        "",
        "```bash",
        "python -m brain.judge_eval_ci --runs %d" % report.runs_per_incident,
        "```",
        "",
        "The raw run — every metric, per model, with the error column — is in",
        "[`judge-eval-ci.json`](judge-eval-ci.json).",
        PACK_END,
    ]
    return "\n".join(lines) + "\n"


def _replace_between(text: str, begin: str, end: str, new_block: str) -> str:
    """Replace the text between two markers. Raises if the markers are missing."""
    if begin not in text or end not in text:
        raise ValueError(f"the pack has no {begin} / {end} markers")
    head, _, rest = text.partition(begin)
    _, _, tail = rest.partition(end)
    # `tail` already starts with the newline that followed the end marker, so the
    # block must not carry one of its own — otherwise every CI run adds a blank
    # line and the file churns forever.
    return f"{head}{new_block.rstrip(chr(10))}{tail}"


def update_pack(pack_path: Path, report: RunReport) -> bool:
    """
    Write the measured numbers into the evidence pack.

    Returns True if the file changed. Raises if the pack has no markers — a
    silent no-op here would let CI go green without writing anything.
    """
    path = Path(pack_path)
    text = path.read_text(encoding="utf-8")
    new_block = block_markdown(report)
    # The markers live inside the section, so the block is the *whole* marker
    # span: write the new block with the markers already in it.
    updated = _replace_between(text, PACK_BEGIN, PACK_END, new_block)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def update_disclaimer(pack_path: Path, report: RunReport) -> bool:
    """
    Replace the 'no Claude number was ever measured' disclaimer once there is one.

    The disclaimer is not decoration: `test_the_pack_says_what_it_does_not_claim`
    requires the words "Claude", "revenue" and "competitor" to be present, and
    `test_the_pack_does_not_quote_a_claude_judge_number` requires that no line
    pairs "Claude" with a cost or a latency **that was not measured**. So the
    disclaimer has to change from "never measured" to "measured on <date>, here
    is the number" — not disappear, because the other two limits stay.
    """
    path = Path(pack_path)
    text = path.read_text(encoding="utf-8")
    old = "- **No Claude judge latency or cost.** Never measured. Needs an API key."
    if old not in text:
        return False
    if not report.measured:
        return False
    cheapest = min(report.measured, key=lambda m: m.cost_per_verdict_usd)
    new = (
        f"- **The Claude judge numbers are measured, not projected** — CI ran every "
        f"Claude model over the labelled set ({report.runs_per_incident} runs per "
        f"incident). The cheapest judge, `{cheapest.model}`, costs "
        f"${cheapest.cost_per_verdict_usd:.6f} per verdict. The full table is in "
        f"[section 4](#4-the-judge--accuracy-offline-and-on-the-real-api)."
    )
    updated = text.replace(old, new)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


# ── the entry point ─────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(prog="python -m brain.judge_eval_ci")
    p.add_argument("--runs", type=int, default=3, help="calls per incident per model")
    p.add_argument("--model", action="append", default=None,
                   help="a Claude model to run (repeatable); default: all of them")
    p.add_argument("--dataset", default=str(DATASET))
    p.add_argument("--pack", default=str(PACK), help="the evidence pack to update")
    p.add_argument("--json-out", default=str(JSON_OUT))
    p.add_argument("--json-only", action="store_true",
                   help="write the JSON and exit without touching the pack")
    p.add_argument("--allow-missing-key", action="store_true",
                   help="exit 0 even when no key is present (for a dry run)")
    args = p.parse_args()

    cfg = load_settings()
    models = args.model or CLAUDE_MODELS
    runs = max(1, args.runs)

    errors = validate_dataset(load_dataset(Path(args.dataset)))
    if errors:
        print(f"ERROR: the dataset has {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"   - {e}", file=sys.stderr)
        return 2

    if not cfg.anthropic_api_key and not args.allow_missing_key:
        print("ERROR: no ANTHROPIC_API_KEY in the environment.", file=sys.stderr)
        print("       The Claude judge's latency and cost cannot be measured without one,", file=sys.stderr)
        print("       and the offline judge's numbers must never be filed under Claude.", file=sys.stderr)
        return 3

    print(f"Running the judge over {len(models)} Claude model(s), {runs} runs per incident...")
    report = run_all(models, runs=runs, dataset=Path(args.dataset), cfg=cfg)

    for m in report.models:
        if m.ok and not m.fallback_used:
            print(f"  {m.model}: P={m.precision:.3f} R={m.recall:.3f} F1={m.f1:.3f} "
                  f"acc={m.accuracy:.3f} p50={m.latency_p50_ms:.0f}ms "
                  f"p95={m.latency_p95_ms:.0f}ms ${m.cost_per_verdict_usd:.6f}/verdict")
        elif m.ok:
            print(f"  {m.model}: DEGRADED — the provider was not reached and the run "
                  f"fell back to the offline judge. Not written to the pack.")
        else:
            print(f"  {m.model}: FAILED — {m.error}")

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"written to {out_path}")

    if args.json_only:
        return 0

    if not report.measured:
        print("ERROR: no model was measured, so the pack was not touched.", file=sys.stderr)
        return 4

    changed = update_pack(Path(args.pack), report)
    changed = update_disclaimer(Path(args.pack), report) or changed
    print("the pack was updated." if changed else "the pack was already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
