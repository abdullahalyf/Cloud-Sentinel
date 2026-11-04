from eval.harness import SCENARIOS, run_scenario


def test_all_scenarios_pass():
    for sc in SCENARIOS:
        result = run_scenario(sc)
        assert result["passed"], result
