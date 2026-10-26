"""The brain eval (scripts/eval_brain.py) in offline fallback mode."""
import importlib.util
from dataclasses import replace
from pathlib import Path

from sentinel.brain import Brain
from shared.config import load_settings

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eval_brain", ROOT / "scripts" / "eval_brain.py")
eval_brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_brain)

offline = replace(load_settings(), anthropic_api_key="")


def test_there_are_eight_scenarios_with_valid_expectations():
    scenarios = eval_brain.load_scenarios()
    assert len(scenarios) == 8
    assert {s["expected"] for s in scenarios} <= {"KILL", "keep"}


def test_fallback_scores_at_least_7_of_8():
    rows = eval_brain.evaluate_all(Brain(offline), offline)
    assert sum(r["correct"] for r in rows) >= 7, eval_brain.table(rows)
    assert all("fallback" in r["verdict"] for r in rows)   # every scenario reaches the brain


def test_table_has_the_slide_columns(capsys):
    assert eval_brain.main(["--offline"]) == 0
    out = capsys.readouterr().out
    header = next(line for line in out.splitlines() if line.startswith("scenario"))
    assert [c.strip() for c in header.split("|")] == ["scenario", "expected", "verdict", "correct"]
    assert "score: " in out


def test_every_scenario_is_judged_three_times_and_keepers_are_never_killed():
    assert eval_brain.ROUNDS == 3
    brain = Brain(offline)
    for sc in eval_brain.load_scenarios():
        outcome, text = eval_brain.run_scenario(sc, brain, offline)
        if sc["expected"] == "keep":
            assert outcome == "keep" and "KILL" not in text, (sc["name"], text)
            assert text.count("→") == 2, text   # three rounds, none of them a kill
