"""A10: nightly integration check. Fake step results only, no subprocesses."""
from brain import nightly
from brain.nightly import StepResult


def test_owner_mapping_by_path():
    assert nightly.owner_for("brain/tests/test_api.py::test_x") == "Alif"
    assert nightly.owner_for("telemetry/tests/test_adapter_crewai.py::t") == "Fojle"
    assert nightly.owner_for("dashboard/web/src/App.tsx") == "Tamjid"
    assert nightly.owner_for("eval/tests/test_roi.py") == "Orin"
    assert nightly.owner_for("infra/tests/test_executor.py") == "Taseen"
    assert nightly.owner_for(".github/workflows/ci.yml") == "Taseen"
    assert nightly.owner_for("shared/tests/test_contracts.py") == "Alif + Taseen (contract)"
    assert nightly.owner_for("something/else.py") == "Taseen"  # integration default


def test_failed_tests_are_parsed_from_pytest_output():
    out = ("....F\nFAILED telemetry/tests/test_adapter_crewai.py::test_crew - assert 0 == 1\n"
           "ERROR brain/tests/test_api.py::test_health - ImportError\n1 failed, 3 passed")
    assert nightly.failed_tests(out) == ["telemetry/tests/test_adapter_crewai.py::test_crew",
                                         "brain/tests/test_api.py::test_health"]


def test_exit_code_5_counts_as_pass_only_when_allowed():
    assert nightly.status_for(5, allow_no_tests=True) == "pass"
    assert nightly.status_for(5, allow_no_tests=False) == "fail"
    assert nightly.status_for(0, allow_no_tests=False) == "pass"
    assert nightly.status_for(1, allow_no_tests=True) == "fail"


def test_tail_keeps_the_last_30_lines():
    text = "\n".join(f"line {i}" for i in range(100))
    tail = nightly.tail(text)
    assert tail.splitlines() == [f"line {i}" for i in range(70, 100)]


def _results() -> list[StepResult]:
    return [
        StepResult("pytest", "fail", 3.2, "boom\nFAILED telemetry/tests/test_x.py::t",
                   ["telemetry/tests/test_x.py::t"]),
        StepResult("eval harness", "pass", 1.0, ""),
        StepResult("compose config", "skip", 0.0, "docker not installed"),
    ]


def test_report_lists_every_step_and_owners_of_failures():
    md = nightly.render_report(_results(), when="2026-11-05 01:00")
    assert md.startswith("# Nightly report · 2026-11-05 01:00")
    assert "**Result: ❌ 1 failed**" in md
    for name in ("pytest", "eval harness", "compose config"):
        assert f"| {name} |" in md
    assert "| `telemetry/tests/test_x.py::t` | Fojle |" in md
    assert "boom" in md  # the error tail is included


def test_report_all_green_and_exit_code():
    ok = [StepResult("pytest", "pass", 1.0, ""), StepResult("npm test", "skip", 0.0, "no node")]
    assert "**Result: ✅ all green**" in nightly.render_report(ok, when="x")
    assert nightly.exit_code(ok) == 0
    assert nightly.exit_code(_results()) == 1


def test_failing_step_without_test_names_maps_to_the_step_owner():
    r = [StepResult("eval harness", "fail", 1.0, "1/2 scenarios passed")]
    assert "| eval harness | Orin |" in nightly.render_report(r, when="x")
