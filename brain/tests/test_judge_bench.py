from dataclasses import replace

from brain import judge_bench


def test_bench_captures_real_contexts_and_fallback_is_right(cfg):
    names = {c.name for c in judge_bench.cases(cfg)}
    assert {"paraphrase_loop", "exact_loop", "legit_burst"} <= names
    rows = judge_bench.run(replace(cfg, judge_provider="fallback"), runs=1)
    assert all(r["correct"] == r["runs"] for r in rows), rows
    assert "Accuracy" in judge_bench.markdown(rows, cfg, "fallback")
