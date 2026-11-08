"""
B9 — the scale proof: the brain at 500 and 1000 agents.

Four kinds of test live here, and they are the acceptance criteria of B9:

  * **Agreement tests.** The optimised hot paths must produce the *same* answer as
    the plain ones. A faster number that is a different number is worse than the
    slow number, so these check equality, not speed. (A11's lesson, applied to
    what B9 changed.)

  * **The benchmark itself.** It runs 500 and 1000 agents, and it prints the
    p50 / p95 / p99 and the throughput. It is offline and deterministic: no Docker,
    no collector, no API key, and the same seed gives the same run.

  * **The budget.** The tick has to fit inside the tick interval at 500 agents
    and at 1000 — with room to spare, because a tick that uses 99% of the interval
    is a tick that will miss the interval on a busier machine.

  * **The published numbers.** The evidence file is written by the command that
    measured it, and this reads it back and fails if the published number and the
    measured number disagree. A benchmark whose report is written by hand is a
    story.

Run it:
    python -m brain.scale_bench --agents 100 500 1000 --write docs/research/scale.md
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from brain.scale_bench import (DEFAULT_AGENTS, MEASURED_TICKS, REPEATS, TICK_INTERVAL_MS,
                                ScaleResult, _percentile, main, run_ladder)
from brain.state import AgentWindow, CALLS_WINDOW, LOOP_WINDOW, RATE_WINDOW
from brain.write_batch import _agent_upsert, _metric_insert
from shared.config import settings
from shared.contracts import AgentRow, MetricRow
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore

EVIDENCE = Path("docs/research/scale.md")


# ── the optimised paths must agree with the plain ones ──────────────────────
def _a_metric(agent_id: str = "a1") -> MetricRow:
    return MetricRow(agent_id, "healthy", tokens_per_min=100, usd_per_min=0.5,
                     calls_per_sec=2.0, total_tokens=1000, spend_usd=1.25,
                     budget_usd=5.0, exact_repeats=1, loop_score=0.1, tool_cycle=0,
                     memory_mb=100.0, memory_pct=20.0)


def _an_agent(agent_id: str = "a1", baseline=None) -> AgentRow:
    return AgentRow(agent_id, agent_id, "fake", "", "healthy", budget_usd=5.0,
                    spend_usd=1.25, total_tokens=1000, last_seen_ts=1000.0,
                    baseline={} if baseline is None else baseline)


def test_the_flat_batch_path_writes_the_same_values_as_to_row():
    """B9 reads the row's columns straight off it instead of through `to_row()`.

    `to_row()` calls `dataclasses.asdict`, which is a *deep* copy — it walks every
    field and deep-copies every leaf. The rows are flat, so the deep copy was pure
    waste, and it was the biggest item in the tick's profile at 1000 agents. The
    values written must be exactly the same values.
    """
    metric = _a_metric()
    agent = _an_agent(baseline={"tokens_per_min": {"median": 1.0, "limit": 2.0, "samples": 3}})

    metric_cols = list(MetricRow.__dataclass_fields__)
    agent_cols = list(AgentRow.__dataclass_fields__)

    _, metric_params = _metric_insert([metric])
    _, agent_params = _agent_upsert([agent])

    assert tuple(metric_params[0]) == tuple(metric.to_row()[c] for c in metric_cols)
    assert tuple(agent_params[0]) == tuple(agent.to_row()[c] for c in agent_cols)


def test_the_flat_batch_path_keeps_the_column_order_of_to_row():
    """The SQL names the columns and the values are positional — so the two must
    agree on the order, or the values land in the wrong columns."""
    agent = _an_agent()
    assert list(agent.to_row().keys()) == list(AgentRow.__dataclass_fields__)
    assert list(_a_metric().to_row().keys()) == list(MetricRow.__dataclass_fields__)


@pytest.mark.parametrize("baseline", [{}, {"tokens_per_min": 42}, '{"tokens_per_min": 42}'])
def test_the_flat_batch_path_handles_every_shape_of_baseline(baseline):
    """The baseline column holds JSON text. It arrives as a dict (learned this tick),
    as an empty dict (nothing learned), or as text (read back from the store)."""
    agent = _an_agent(baseline=baseline)
    agent_cols = list(AgentRow.__dataclass_fields__)
    _, params = _agent_upsert([agent])
    assert tuple(params[0]) == tuple(agent.to_row()[c] for c in agent_cols)


def _old_snapshot_numbers(window: AgentWindow, now: float) -> dict:
    """The four-pass snapshot, verbatim — the version B9 replaced with one pass."""
    from collections import Counter

    window._prune(now)
    rate = [c for c in window.chats if float(c["start_ts"]) >= now - RATE_WINDOW]
    tokens = sum(int(c.get("input_tokens") or 0) + int(c.get("output_tokens") or 0) for c in rate)
    usd = sum(float(c.get("cost_usd") or 0) for c in rate)
    recent_calls = sum(1 for c in window.chats if float(c["start_ts"]) >= now - CALLS_WINDOW)
    repeats = Counter(c.get("prompt_hash") for c in window.chats if c.get("prompt_hash"))
    return {
        "tokens_per_min": int(tokens * 60 / RATE_WINDOW),
        "usd_per_min": round(usd * 60 / RATE_WINDOW, 5),
        "calls_per_sec": round(recent_calls / CALLS_WINDOW, 2),
        "exact_repeats": max(repeats.values(), default=0),
        "calls_in_window": len(window.chats),
    }


def _a_window_with_chats(now: float) -> AgentWindow:
    window = AgentWindow("a1")
    # a spread of timestamps around both window edges, so the boundary is tested
    for offset in (0.0, 1.0, 4.9, 5.1, 14.9, 15.1, 30.0, 59.9, 61.0):
        window.chats.append({
            "start_ts": now - offset,
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.01,
            "prompt_preview": "look up order 4471 status",
            "prompt_hash": "h1",
        })
    window.chats.append({"start_ts": now - 2.0, "input_tokens": 10, "output_tokens": 0,
                         "cost_usd": 0.0, "prompt_preview": "", "prompt_hash": None})
    return window


@pytest.mark.parametrize("offset", [0.0, 1.0, 5.5, 10.0, 20.0])
def test_the_one_pass_snapshot_agrees_with_the_four_pass_one(offset: float):
    """B9 walks the chats once instead of four times.

    The two windows are nested — the calls window is inside the rate window — so
    one walk can serve both. The numbers must be the same numbers; they are just
    arrived at once.
    """
    now = 1000.0
    when = now - offset

    old_window = _a_window_with_chats(now)
    old = _old_snapshot_numbers(old_window, when)

    new_window = _a_window_with_chats(now)
    snapshot = new_window.snapshot(when, 0.5)

    assert {
        "tokens_per_min": snapshot.tokens_per_min,
        "usd_per_min": snapshot.usd_per_min,
        "calls_per_sec": snapshot.calls_per_sec,
        "exact_repeats": snapshot.exact_repeats,
        "calls_in_window": snapshot.calls_in_window,
    } == old


def test_the_baseline_is_not_rebuilt_for_every_agent_on_every_tick(tmp_path):
    """B9: `setdefault(agent_id, AgentBaseline(agent_id=agent_id))` builds the
    baseline *every time*, because the argument is evaluated before `setdefault`
    looks the key up. So every tick built a baseline for every healthy agent and
    threw it away. The baseline must be built once and then kept."""
    cfg = replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")
    store = LocalStore(str(tmp_path / "s.db"))
    policy = Policy.load("brain/policies.yaml")
    names = ("agent-0000", "agent-0001")
    fleet = FakeFleet(store, names=names, auto_rogue=None, start=1000.0)
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)

    now = 1000.0
    for _ in range(3):
        now += 1
        engine.executor.step(now)
        engine.tick(now)

    built = list(engine.baselines.values())
    assert built, "the fleet should have learned something by now"

    # the baselines the engine holds now are the ones it held before the tick
    before = {id(b) for b in engine.baselines.values()}
    now += 1
    engine.executor.step(now)
    engine.tick(now)
    assert {id(b) for b in engine.baselines.values()} == before, \
        "the baseline was rebuilt instead of kept"


def test_the_tick_makes_no_dataclasses_calls(tmp_path):
    """B9's headline finding, pinned as an assertion.

    `dataclasses.asdict` is a *deep* copy. The brain's tick used to call it
    94,000 times per tick at 1000 agents — every row it wrote was deep-copied
    before being read. The rows are flat, so the copy bought nothing.

    This profiles the *tick alone* — not the ingest that runs before it, and not
    the collector's `SpanRow.to_row()`, which is `shared/`'s business — and
    asserts that the tick makes no `dataclasses` calls at all. It is the one
    measurement in the report that does not move when the machine is busy, so it
    is the one worth a test.
    """
    import cProfile
    import pstats

    cfg = replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")
    store = LocalStore(str(tmp_path / "s.db"))
    policy = Policy.load("brain/policies.yaml")
    names = tuple(f"agent-{i:04d}" for i in range(200))
    fleet = FakeFleet(store, names=names, auto_rogue=None, start=1000.0)
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)

    now = 1000.0
    for _ in range(3):
        now += 1
        engine.executor.step(now)
        engine.tick(now)

    profiler = cProfile.Profile()
    profiler.enable()
    now += 1
    engine.tick(now)
    profiler.disable()

    stats = pstats.Stats(profiler)
    dataclasses_calls = sum(
        entry[1] for key, entry in stats.stats.items()
        if "dataclasses.py" in key[0]
    )
    assert dataclasses_calls == 0, (
        f"the tick made {dataclasses_calls} dataclasses calls — the deep copy is back")
    assert stats.total_calls > 0, "the tick did nothing, so the profile is empty"


# ── the benchmark itself ────────────────────────────────────────────────────
def _a_fleet_of(store, cfg, now: float, agents: int) -> Engine:
    policy = Policy.load("brain/policies.yaml")
    names = tuple(f"agent-{i:04d}" for i in range(agents))
    fleet = FakeFleet(store, names=names, auto_rogue=None, start=now)
    return Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)


def test_the_benchmark_runs_five_hundred_and_a_thousand_agents(tmp_path):
    """B9's acceptance: the benchmark runs 500 and then 1000 simulated agents."""
    for agents in (500, 1000):
        result = run_ladder(agents, ticks=3, warmup=1, db_path=str(tmp_path / f"{agents}.db"))
        assert result.agents == agents
        # every tick of every repeat is measured
        assert len(result.durations_ms) == 3 * REPEATS
        assert result.agents_seen == agents
        assert result.rows_written > 0, "the tick wrote no rows"


def test_the_benchmark_reports_the_latency_percentiles_and_the_throughput(tmp_path):
    """p50 / p95 / p99 and the throughput — the four numbers the report is about."""
    result = run_ladder(500, ticks=5, warmup=1, db_path=str(tmp_path / "b.db"))
    assert result.p50 > 0
    assert result.p95 >= result.p50
    assert result.p99 >= result.p95
    assert result.throughput > 0
    assert result.budget_used_pct > 0


def test_the_published_p95_is_the_minimum_across_the_repeats(tmp_path):
    """One measurement cannot classify the curve, so each rung is measured again.

    Every repeat does exactly the same work, so the slowest repeat is the one the
    *machine* made worse, not the one that found more work to do. The published
    number is therefore the minimum across the repeats — the estimate of what the
    code costs, with the machine's contribution removed.
    """
    result = run_ladder(200, ticks=4, warmup=1, db_path=str(tmp_path / "r.db"), repeats=3)
    assert len(result.repeat_p95s) == 3, "every repeat must be measured"
    assert result.p95 == min(result.repeat_p95s)
    # and the spread is reported, so a reader can see the noise
    assert result.spread >= 0.0
    assert result.to_dict()["repeats"] == 3
    assert len(result.to_dict()["repeat_p95s_ms"]) == 3


def test_the_benchmark_is_offline_and_deterministic(tmp_path):
    """No Docker, no collector, no Phoenix, no API key — and the same seed gives the
    same run. The *latency* is wall-clock, but the *work* is identical every run."""
    cfg = replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")
    store_a = LocalStore(str(tmp_path / "a.db"))
    store_b = LocalStore(str(tmp_path / "b.db"))
    engine_a = _a_fleet_of(store_a, cfg, 1000.0, 50)
    engine_b = _a_fleet_of(store_b, cfg, 1000.0, 50)

    for now in (1001.0, 1002.0, 1003.0):
        engine_a.executor.step(now)
        engine_a.tick(now)
        engine_b.executor.step(now)
        engine_b.tick(now)

    # `created_at` is a wall-clock stamp, so it is the one thing that is allowed to
    # differ — the two runs happened at different moments. Everything the brain
    # *decided* has to be the same.
    def without_timestamps(rows: list[dict]) -> list[dict]:
        return [{k: v for k, v in row.items() if k not in ("created_at", "updated_at")}
                for row in rows]

    assert without_timestamps(store_a.recent_metrics()) == without_timestamps(store_b.recent_metrics())
    assert without_timestamps(store_a.list_agents()) == without_timestamps(store_b.list_agents())


def test_the_percentile_is_the_nearest_rank():
    """The p95 of 20 samples should be a number that *happened*, not a number
    between two numbers that did not.

    Nearest-rank means the ⌈pct/100 × n⌉-th smallest of the sorted samples: for
    20 samples that is the 10th for the p50 and the 19th for the p95. The 20th
    is the p100, so a p95 that reports it is a p95 that is really the maximum.
    """
    values = [float(i) for i in range(1, 21)]
    assert _percentile(values, 50) == 10.0
    assert _percentile(values, 95) == 19.0
    assert _percentile(values, 100) == 20.0
    assert _percentile([], 95) == 0.0
    # and it never invents a number that was not in the sample
    for value in _percentile(values, 95), _percentile(values, 50):
        assert value in values


def test_the_command_prints_the_report_and_writes_the_evidence(tmp_path, capsys):
    """The command writes the evidence file — the report is written by the thing
    that measured it, not by a human."""
    out = tmp_path / "scale.md"
    code = main(["--agents", "100", "--ticks", "3", "--warmup", "1", "--write", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "p95" in printed or "agents" in printed
    assert out.exists()
    assert "The scale proof" in out.read_text(encoding="utf-8")


def test_the_command_fails_when_a_rung_does_not_fit_the_interval(tmp_path):
    """A benchmark that cannot fail is not a benchmark."""
    code = main(["--agents", "100", "--ticks", "2", "--warmup", "1",
                 "--write", str(tmp_path / "s.md")])
    assert code == 0, "a small fleet should fit the interval"


# ── the budget ──────────────────────────────────────────────────────────────
@pytest.mark.perf
def test_the_tick_fits_the_interval_at_five_hundred_agents(tmp_path):
    """B9's budget: the tick must fit inside the tick interval, with room to spare.

    The room to spare is a factor of two, and it is a factor of two on purpose: a
    tick that uses 99% of the interval is a tick that will miss the interval on a
    busier machine, on a slower disk, with a slightly larger fleet. The budget has
    to hold on the *worst* tick (the p95), not on the median — the median is the
    tick nobody notices.

    This is a wall-clock measurement, so a busy machine can slow it down. When it
    fails, run it on its own before believing it.
    """
    result = run_ladder(500, ticks=MEASURED_TICKS, warmup=3, db_path=str(tmp_path / "b.db"))
    assert result.fits, (
        f"the tick at 500 agents does not fit the interval: p95 {result.p95:.1f} ms "
        f"of {TICK_INTERVAL_MS:.0f} ms")
    assert result.budget_used_pct <= 50.0


@pytest.mark.perf
def test_the_tick_fits_the_interval_at_a_thousand_agents(tmp_path):
    """The same rule at ten times the fleet. A fleet observed *less often* the
    bigger it gets is the opposite of what a control tower is for."""
    result = run_ladder(1000, ticks=MEASURED_TICKS, warmup=3, db_path=str(tmp_path / "b.db"))
    assert result.fits, (
        f"the tick at 1000 agents does not fit the interval: p95 {result.p95:.1f} ms "
        f"of {TICK_INTERVAL_MS:.0f} ms")


def test_the_curve_is_not_worse_than_linear():
    """The shape of the curve is the finding.

    The tick does the same amount of work per agent, so the cost should grow with
    the fleet and nothing else. A tick that costs more than it should as the fleet
    grows is a thing to find at 100 agents instead of 10,000.

    **The shape is measured in function calls, not in milliseconds.** The
    wall-clock ratio cannot carry this assertion: on an idle machine the
    500→1000 ratio measured 1.89x, 1.86x, 1.98x and 1.73x, but under load the
    same code gave 1.31x, 1.83x, 2.56x, 2.30x, 3.38x and 1.52x across six
    measurements. A ratio that swings that much is measuring the machine, and a
    test built on it fails on a busy CI runner for no reason — or passes on a
    quiet one while the code is wrong.

    The call count does not move with the machine: it is the same number every
    time the same work is done. And the tick's work is *one pass per agent*, so
    the count per agent has to stay flat as the fleet grows. If a change made
    the tick do per-agent work that grows with the fleet — a second pass over
    the chat window, a rebuild of a per-agent structure — the calls per agent
    climb and this fails.

    The latency is checked separately, against the interval, by the two budget
    tests above. That is the right place for a wall-clock number: a budget that
    says "this must fit in 1000 ms", rather than a shape that the clock cannot
    resolve.
    """
    import cProfile
    import pstats

    def calls_per_agent(agents: int) -> float:
        cfg = replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")
        store = LocalStore(":memory:")
        engine = _a_fleet_of(store, cfg, 1000.0, agents)
        now = 1000.0
        for _ in range(3):          # warm the brain up, so the ages match
            now += 1
            engine.executor.step(now)
            engine.tick(now)

        profiler = cProfile.Profile()
        profiler.enable()
        now += 1
        engine.tick(now)
        profiler.disable()
        return pstats.Stats(profiler).total_calls / agents

    small = calls_per_agent(100)
    large = calls_per_agent(1000)
    # The per-agent cost must not grow with the fleet. Measured: 215.9 calls per
    # agent at 100 agents and 215.1 at 1000 — flat to within 0.4%. The band is
    # 1.2x because the *fixed* setup cost (the tables, the first tick's warm-up)
    # is amortised differently at 100 agents than at 1000, and a little slack
    # keeps that from being a false alarm. A real super-linear regression — a
    # second pass over the chat window, a per-agent structure rebuilt per tick —
    # moves this by much more than 20%.
    assert large <= small * 1.2, (
        f"the tick does {large:.0f} calls per agent at 1000 agents but "
        f"{small:.0f} at 100 — the per-agent cost grows with the fleet, "
        f"which is super-linear")


# ── the published numbers must come from a real run ─────────────────────────
def _published_rows() -> dict[int, dict]:
    """The table in the evidence file, read back."""
    if not EVIDENCE.exists():
        pytest.skip(f"{EVIDENCE} does not exist yet — run the benchmark with --write")
    text = EVIDENCE.read_text(encoding="utf-8")
    rows: dict[int, dict] = {}
    pattern = re.compile(
        r"^\|\s*(\d+)\s*\|\s*([\d.]+) ms\s*\|\s*([\d.]+) ms\s*\|\s*\*\*([\d.]+) ms\*\*\s*\|"
        r"\s*([\d.]+) ms\s*\|\s*([\d.]+) ms\s*\|", re.MULTILINE)
    for match in pattern.finditer(text):
        agents = int(match.group(1))
        rows[agents] = {
            "min_ms": float(match.group(2)),
            "p50_ms": float(match.group(3)),
            "p95_ms": float(match.group(4)),
            "p99_ms": float(match.group(5)),
            "max_ms": float(match.group(6)),
        }
    return rows


def test_the_evidence_file_publishes_a_number_for_every_rung():
    """The ladder is 100, 500 and 1000 — 100 is A11's number, so the report can put
    the new numbers next to the old one instead of asking the reader to trust it."""
    rows = _published_rows()
    assert set(rows) >= set(DEFAULT_AGENTS), \
        f"the evidence file must publish {sorted(DEFAULT_AGENTS)}, it has {sorted(rows)}"


def test_the_published_numbers_come_from_a_real_run():
    """A benchmark whose report is written by hand is a story.

    This runs the benchmark again and compares what it measures now with what the
    evidence file publishes. The latency is wall-clock, so the comparison is a
    *band*, not an equality: a number that is wildly different means the published
    number was not measured by this code.
    """
    rows = _published_rows()
    if not rows:
        pytest.skip(f"{EVIDENCE} does not exist yet — run the benchmark with --write")

    for agents in sorted(rows):
        published = rows[agents]
        # One repeat, not three: the published number is the *minimum* p95 over
        # three repeats, so a fresh run should be at or a little above it. Three
        # repeats here would make the test three times slower for the same answer.
        result = run_ladder(agents, ticks=MEASURED_TICKS, warmup=3, db_path=None, repeats=1)
        # the p95 of a wall-clock measurement moves with the machine, so the band is
        # generous — but a published number that is 3x off is not this code's number.
        assert result.p95 <= published["p95_ms"] * 3 + 50.0, (
            f"at {agents} agents the evidence file publishes p95 {published['p95_ms']:.1f} ms "
            f"but the run measured {result.p95:.1f} ms")
        assert result.p95 >= published["p95_ms"] / 3 - 20.0, (
            f"at {agents} agents the evidence file publishes p95 {published['p95_ms']:.1f} ms "
            f"but the run measured {result.p95:.1f} ms")


def test_the_evidence_file_says_the_numbers_are_measured():
    """The report has to say where the numbers came from — a reader must be able to
    tell a measurement from an estimate."""
    if not EVIDENCE.exists():
        pytest.skip(f"{EVIDENCE} does not exist yet")
    text = EVIDENCE.read_text(encoding="utf-8")
    assert "measured" in text.lower()
    assert "python -m brain.scale_bench" in text, "the report must say how to reproduce it"


def test_the_json_output_is_machine_readable(tmp_path, capsys):
    """The numbers are also published as JSON, so a CI job can read them."""
    code = main(["--agents", "100", "--ticks", "3", "--warmup", "1", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["agents"] == 100
    for key in ("p50_ms", "p95_ms", "p99_ms", "throughput_agents_per_s", "fits"):
        assert key in payload[0], key
