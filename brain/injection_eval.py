"""
Measures the injection scorers against brain/eval_data/injection.jsonl (A6).

    python -m brain.injection_eval

The acceptance bar (docs/tasks/alif.md): **recall ≥ 0.85** and **benign false positives ≤ 5%**.

Recall is measured against a *deny* decision (score ≥ 0.8): an attack that only lands in the
"ask a human" band is not caught — the human sees it, but the system did not catch it. The false
positive rate is measured against any non-zero score, because a benign call that even reaches a
human is a cost the operator pays.

The report also lists the misses and the false positives by id, so a regression says exactly which
case broke.
"""
from __future__ import annotations

import json
import pathlib
from typing import Optional

from brain.injection import APPROVAL_SCORE, DENY_SCORE, score_text, score_tool_args

CORPUS = pathlib.Path(__file__).resolve().parent / "eval_data" / "injection.jsonl"
ALLOWED_HOSTS = "api.shopbd.com,localhost,127.0.0.1,example.com"


def load_cases(path: pathlib.Path = CORPUS) -> list[dict]:
    cases: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def score_case(case: dict, allowed_hosts: str = ALLOWED_HOSTS) -> float:
    if case["kind"] == "tool_args":
        return score_tool_args(case["input"]["tool"], case["input"]["args"], allowed_hosts).score
    return score_text(case["input"]).score


def evaluate(cases: Optional[list[dict]] = None, deny_threshold: float = DENY_SCORE,
             approval_threshold: float = APPROVAL_SCORE) -> dict:
    """The precision / recall of the scorers over the corpus."""
    cases = cases if cases is not None else load_cases()
    attacks = [c for c in cases if c["label"]["attack"]]
    benign = [c for c in cases if not c["label"]["attack"]]

    tp = sum(1 for c in attacks if score_case(c) >= deny_threshold)
    caught_at_all = sum(1 for c in attacks if score_case(c) >= approval_threshold)
    fp_any = sum(1 for c in benign if score_case(c) > 0.0)
    fp_deny = sum(1 for c in benign if score_case(c) >= deny_threshold)

    recall = tp / len(attacks) if attacks else 0.0
    approval_recall = caught_at_all / len(attacks) if attacks else 0.0
    fp_rate = fp_any / len(benign) if benign else 0.0
    precision = tp / (tp + fp_deny) if (tp + fp_deny) else 1.0

    return {
        "cases": len(cases),
        "attacks": len(attacks),
        "benign": len(benign),
        "true_positives": tp,
        "false_negatives": len(attacks) - tp,
        "false_positives_any": fp_any,
        "false_positives_deny": fp_deny,
        "recall": round(recall, 4),
        "recall_at_approval": round(approval_recall, 4),
        "false_positive_rate": round(fp_rate, 4),
        "precision": round(precision, 4),
        "misses": [{"id": c["id"], "score": round(score_case(c), 3), "note": c.get("note", "")}
                   for c in attacks if score_case(c) < deny_threshold],
        "false_positives": [{"id": c["id"], "score": round(score_case(c), 3), "note": c.get("note", "")}
                            for c in benign if score_case(c) > 0.0],
        "holdout": _holdout(cases, deny_threshold),
    }


def _holdout(cases: list[dict], deny_threshold: float) -> dict:
    """
    The score on the cases that were written AFTER the patterns were tuned.

    The tuned score can always be made to look good — the patterns are fitted to it. The
    hold-out is the honest number: it says whether the scorers generalise or memorise.
    """
    holdout = [c for c in cases if c["family"].startswith("holdout_")]
    if not holdout:
        return {}
    attacks = [c for c in holdout if c["label"]["attack"]]
    benign = [c for c in holdout if not c["label"]["attack"]]
    tp = sum(1 for c in attacks if score_case(c) >= deny_threshold)
    fp = sum(1 for c in benign if score_case(c) > 0.0)
    return {
        "cases": len(holdout),
        "attacks": len(attacks),
        "benign": len(benign),
        "recall": round(tp / len(attacks), 4) if attacks else 0.0,
        "false_positive_rate": round(fp / len(benign), 4) if benign else 0.0,
        "misses": [{"id": c["id"], "score": round(score_case(c), 3), "note": c.get("note", "")}
                   for c in attacks if score_case(c) < deny_threshold],
        "false_positives": [{"id": c["id"], "score": round(score_case(c), 3), "note": c.get("note", "")}
                            for c in benign if score_case(c) > 0.0],
    }


def main() -> None:
    report = evaluate()
    print(f"corpus: {report['cases']} cases ({report['attacks']} attacks, {report['benign']} benign)")
    print(f"recall (deny >= {DENY_SCORE}):   {report['recall']:.3f}   "
          f"({report['true_positives']}/{report['attacks']})")
    print(f"recall (approval >= {APPROVAL_SCORE}): {report['recall_at_approval']:.3f}")
    print(f"false positive rate:      {report['false_positive_rate']:.3f}   "
          f"({report['false_positives_any']}/{report['benign']})")
    print(f"precision (vs denies):    {report['precision']:.3f}")
    holdout = report.get("holdout") or {}
    if holdout:
        print(f"\nhold-out (written after tuning): {holdout['cases']} cases")
        print(f"  recall:            {holdout['recall']:.3f}")
        print(f"  false positives:   {holdout['false_positive_rate']:.3f}")
    if report["misses"]:
        print(f"\nmisses ({len(report['misses'])}):")
        for m in report["misses"]:
            print(f"  {m['id']}  score {m['score']:.2f}  {m['note']}")
    if report["false_positives"]:
        print(f"\nfalse positives ({len(report['false_positives'])}):")
        for m in report["false_positives"]:
            print(f"  {m['id']}  score {m['score']:.2f}  {m['note']}")


if __name__ == "__main__":
    main()
