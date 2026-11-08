"""
B12 — the evidence pack. Acceptance tests.

`docs/research/pitch-numbers.md` is a file of **claims with numbers**. A
number in a pitch deck is worth exactly as much as the command that
reproduces it, so this file checks both halves:

  * every **command** in the pack is a real command — it exists, and it
    runs;
  * every **number** in the pack is the number that command produces — not
    the number someone remembered writing down.

The second half is the one that matters. A pack whose numbers have drifted
from its code is worse than no pack, because it is *evidence* that is wrong.

**The check is a parse, not a hard-coded table.** The pack is markdown, and
the numbers live in it, so the test reads the markdown and compares it with
what the code actually says. A number that is hard-coded in the test would
just be a second copy to keep in sync — and the second copy is the one that
goes stale.

**Every number is bound to the place that claims it.** The pack states most
of its numbers twice — once in the section that argues the claim, once in
the summary table at the bottom — and a check that looks for a number
*anywhere* in the file is satisfied by the summary while the section the
reader is looking at says something else. So each number is read out of
the row, and the column, that makes the claim.

**And the file proves it can fail.** The bottom of this file corrupts the
pack twelve ways and requires the owning test to notice each one. Without
that, the checks above could pass on a pack that lies — which is exactly
what the first version of this file did, and what the drift tests are
there to prevent.

**What is deliberately not checked:** the numbers that need a human. The
Claude judge's latency and cost have never been measured, because there is
no API key. The test asserts they are **absent** from the pack rather than
asserting a value for them — a pack that quietly grew a guess is a pack that
lies.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "docs" / "research" / "pitch-numbers.md"


@pytest.fixture(scope="module")
def pack() -> str:
    """
    The evidence pack's text.

    The path can be overridden with `CS_EVIDENCE_PACK`, which is how the
    drift test at the bottom of this file points the checks at a
    deliberately corrupted copy — without writing anything into the
    repository.
    """
    path = Path(os.environ.get("CS_EVIDENCE_PACK", PACK))
    assert path.exists(), f"the evidence pack is missing: {path}"
    return path.read_text(encoding="utf-8")


# ── the pack exists and says what it is ────────────────────────────────────
def test_the_pack_exists(pack):
    """The pack is there."""
    assert pack.strip()


def test_the_pack_names_every_claim_area(pack):
    """
    The six things a pitch asks about are all in it.

    Detection, heal, money, accuracy, scale, security — the pack that
    forgets one of them is the pack that gets an unanswerable question.
    """
    for topic in ("detect", "heal", "saved", "accuracy", "scale", "security"):
        assert topic.lower() in pack.lower(), f"the pack says nothing about {topic}"


def test_every_command_in_the_pack_is_real(pack):
    """
    Every `python -m brain.…` in the pack names a module that exists.

    A reproduce command that points at a module nobody wrote is worse than
    no command — it looks like the claim was checked.
    """
    commands = set(re.findall(r"python -m (brain\.[a-z_]+)", pack))
    assert commands, "the pack has no reproduce command"
    for module in commands:
        path = REPO / (module.replace(".", "/") + ".py")
        assert path.exists(), f"{module} is quoted in the pack but does not exist"


def test_the_pack_runs_at_least_one_command(pack):
    """
    At least one reproduce command actually runs, and exits 0.

    The cheapest one is the audit verify — it needs no Docker, no keys and
    no network, so it is the one command that can be checked anywhere.
    """
    result = subprocess.run(
        [sys.executable, "-m", "brain.audit", "verify"],
        cwd=str(REPO), capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, (
        f"`python -m brain.audit verify` failed:\n{result.stderr[-2000:]}")


# ── the numbers must match the code ────────────────────────────────────────
def _cells(pack: str, row_label: str) -> list[str]:
    """
    The values in the pack's table row labelled `row_label`.

    The pack is markdown, and the numbers live in table cells, so a row is
    `| **Label** | value | ... |`. The emphasis markers are stripped from
    every cell, because the pack bolds the number it is claiming and the
    reader has to be able to see it either way — and because `**20/20
    runs**` and `20/20` have to compare equal.

    **Why a row and not the whole file.** A number that appears *somewhere*
    in the pack is not a number that is *bound* to its claim. "0.914"
    sitting in a summary table at the bottom would satisfy a plain
    `in pack` check even if the table it belongs to said 0.999 — the check
    would pass on a pack that lies in the place the reader actually looks.
    So every number is looked up in the row that names it.
    """
    cells = []
    wanted = str(row_label).lower()
    for line in pack.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        parts = [p.strip() for p in stripped.strip("|").split("|")]
        if not parts:
            continue
        label = _plain(parts[0])
        if label.lower() == wanted:
            cells.append([_plain(p) for p in parts[1:]])
    return cells


def _plain(text: str) -> str:
    """A markdown cell with its emphasis markers removed."""
    return text.replace("**", "").replace("`", "").strip()


def _row_with(pack: str, row_label: str, must_contain: str) -> str:
    """
    The one row labelled `row_label` whose text contains `must_contain`.

    Fails loudly when there is no such row, or more than one — because a
    test that picks the first match is a test that checks whatever happens
    to be first. The pack has a summary table that repeats the section
    tables, so "Determinism" is genuinely two rows; the one that makes the
    claim is told apart by what it says.
    """
    matching = [r for r in _cells(pack, row_label) if must_contain in " ".join(r)]
    assert len(matching) == 1, (
        f"expected exactly one {row_label!r} row containing {must_contain!r}, "
        f"found {len(matching)}: {matching}")
    return " ".join(matching[0])


def _every_statement_of(pack: str, pattern: str) -> list[str]:
    """
    Every line in the pack that makes the claim `pattern` describes.

    The pack says most of its numbers **twice** — once in the section that
    argues the claim, once in the summary table at the bottom. That is
    good for the reader and dangerous for the test: a check that looks at
    one of the two passes while the other one lies.

    So the rule is the strict one. **Every** statement of a claim has to
    agree with the measurement. A pack that says "115 labelled cases" in
    the section and "120 labelled cases" in the summary is a pack that
    contradicts itself, and a reader will find the contradiction before
    they find the bug that caused it.
    """
    return [line for line in pack.splitlines() if re.search(pattern, line)]


def _assert_all_statements_agree(pack: str, pattern: str, value: str,
                                 what: str) -> None:
    """
    Every statement of the claim must contain `value`.

    The claim must also be made at least once — a pack that stopped
    claiming it is not a pack that is right about it.
    """
    statements = _every_statement_of(pack, pattern)
    assert statements, f"the pack never states {what}"
    for line in statements:
        assert value in line, (
            f"the pack states {what} as something else: {line.strip()!r} — "
            f"the measurement is {value}")


def test_the_demo_run_numbers_in_the_pack_are_the_real_ones(pack):
    """
    The detect/heal/saved numbers come from the demo runner, so they are
    compared with the demo runner.

    The runner is deterministic — a virtual clock, a fixed seed — so the
    numbers are the same every time, and a mismatch means the pack has
    drifted.
    """
    result = subprocess.run(
        [sys.executable, "-m", "brain.demo_runner", "--runs", "20"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600, check=False,
    )
    assert result.returncode == 0, (
        f"the demo runner failed:\n{result.stderr[-2000:]}")
    out = result.stdout

    saved = re.search(r"Saved\*\*: \$([0-9.]+)", out)
    assert saved, "the demo runner did not print what it saved"
    money = saved.group(1)
    # Bound to the row that makes the claim, and the row's own cell — the
    # cell is "$2.2344 (648,720 tokens)", so the money is compared with
    # the number at the start of it rather than with the whole cell.
    saved_row = _row_with(pack, "Money saved", "$")
    saved_cell = _first_cell_of(pack, "Money saved")
    assert saved_cell.startswith(f"${money}"), (
        f"the pack's 'Money saved' cell says {saved_cell!r}, but the demo "
        f"runner saved ${money}")

    held = re.search(r"Held\*\*: (\d+)/(\d+)", out)
    assert held, "the demo runner did not say how many runs held"
    fraction = f"{held.group(1)}/{held.group(2)}"
    # The pack says this twice — in the section and in the summary table —
    # so the section is picked out by the wording that only it uses.
    determinism_cell = _first_cell_of(pack, "Determinism")
    assert fraction in determinism_cell, (
        f"the pack's 'Determinism' cell says {determinism_cell!r}, but the "
        f"demo runner held {fraction}")


def _first_cell_of(pack: str, row_label: str) -> str:
    """
    The first value cell of the row labelled `row_label`.

    The pack states most claims twice — in the section that argues it and
    in the summary table at the bottom — so this takes the **first** row
    with that label, which is the section's own table, and returns its
    first cell.
    """
    rows = _cells(pack, row_label)
    assert rows, f"the pack has no row labelled {row_label!r}"
    assert rows[0], f"the pack's {row_label!r} row has no value cell"
    return rows[0][0]


def test_the_security_numbers_in_the_pack_are_the_real_ones(pack):
    """
    The detector precision and recall are compared with a real run.

    The command exits non-zero if the numbers drop below the floor, so a
    pass here means the detectors are still where the pack says they are.
    """
    result = subprocess.run(
        [sys.executable, "-m", "brain.security", "measure",
         "--cases", "brain/eval_data/security.jsonl"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600, check=False,
    )
    assert result.returncode == 0, (
        f"the security measure failed:\n{result.stderr[-2000:]}")
    out = result.stdout

    cases = re.search(r"(\d+) labelled cases", out)
    assert cases, "the security measure did not print the case count"
    count = cases.group(1)
    # The count is stated in prose — in the section and again in the
    # "what this file does not claim" list — so every statement of it has
    # to agree.
    _assert_all_statements_agree(
        pack, r"labelled cases", count, "the number of labelled cases")

    for detector in re.findall(r"(\w+): precision ([0-9.]+), recall ([0-9.]+)", out):
        name, precision, recall = detector
        # The pack's security table has one row per detector, and the
        # precision and recall are named columns of it. They are read
        # **by column**, not by looking for the number somewhere in the
        # row: when precision and recall are both 1.0, a row-wide
        # substring check cannot tell a correct row from a row whose
        # precision was wrong and whose recall happened to be right.
        rows = _cells(pack, name)
        assert len(rows) == 1, (
            f"expected exactly one row for the detector {name!r}, found {len(rows)}")
        row = rows[0]
        header = _security_header(pack)
        # The header's first column is the detector's name, and `_cells`
        # drops it, so the header's index is one past the row's index.
        precision_at = header.index("precision") - 1
        recall_at = header.index("recall") - 1
        assert 0 <= precision_at < len(row), (
            f"the pack's {name} row has no precision cell: {row}")
        assert 0 <= recall_at < len(row), (
            f"the pack's {name} row has no recall cell: {row}")
        assert row[precision_at] == precision, (
            f"the pack's {name} row says a precision of {row[precision_at]}, "
            f"but the detector measured {precision}")
        assert row[recall_at] == recall, (
            f"the pack's {name} row says a recall of {row[recall_at]}, but the "
            f"detector measured {recall}")


def _security_header(pack: str) -> list[str]:
    """
    The column names of the pack's security table.

    Read from the table's own header row, so the check follows the table
    if the columns are ever reordered — and so a column that is renamed
    is a failure rather than a silently-ignored one.
    """
    for line in pack.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [_plain(c).lower() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == "detector":
            return cells
    raise AssertionError("the pack has no security table header")


def test_the_judge_numbers_in_the_pack_are_the_real_ones(pack):
    """The judge's precision, recall, F1 and accuracy are compared with a run."""
    result = subprocess.run(
        [sys.executable, "-m", "brain.judge_eval", "--judge", "fallback",
         "--runs", "1"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600, check=False,
    )
    assert result.returncode == 0, (
        f"the judge eval failed:\n{result.stderr[-2000:]}")
    out = result.stdout

    for label in ("Precision", "Recall", "F1", "Accuracy"):
        match = re.search(rf"\|\s*{label}\s*\|\s*([0-9.]+)\s*\|", out)
        assert match, f"the judge eval did not print {label}"
        value = match.group(1)
        # The judge table is a label-and-value table, so the value is the
        # row's own cell — compared exactly, so a wrong number cannot be
        # excused by another number in the same row.
        cell = _first_cell_of(pack, label)
        assert cell == value, (
            f"the pack's {label} cell says {cell!r}, but the judge measured "
            f"{value}")


def test_the_scale_numbers_in_the_pack_match_the_scale_doc(pack):
    """
    The scale table is the same table, so the pack and the doc cannot
    disagree.

    The doc is generated by the benchmark, so the pack quoting it is quoting
    the measurement rather than a copy someone typed.

    **The p95 is found by column, not by position.** The doc has several
    tables and several latency columns, so the cell is located by asking
    the header which column is called `p95`. A regex that guessed the
    column would have been a regex that silently checked nothing — the
    kind of test that passes forever because the loop it guards never
    runs.
    """
    scale = (REPO / "docs" / "research" / "scale.md").read_text(encoding="utf-8")
    measurements = _scale_p95_by_agents(scale)
    assert measurements, "the scale doc has no p95 column"

    for agents, value in sorted(measurements.items()):
        row = _row_with(pack, agents, "ms")
        assert f"{value} ms" in row, (
            f"the pack's {agents}-agent row says {row!r}, but the scale doc's "
            f"p95 is {value} ms")
        # The summary table repeats the p95 for the largest fleet — the
        # one a slide talks about — rounded to whole milliseconds,
        # because that is the precision a slide needs. It is a different
        # number, so it is checked on its own terms: the rounded value
        # has to be the rounded measurement, not a number typed by hand.
        rounded = f"{round(float(value))} ms"
        statements = _every_statement_of(
            pack, rf"\|\s*Scale at {agents} agents")
        for line in statements:
            assert rounded in line, (
                f"the pack states the p95 at {agents} agents as something "
                f"else: {line.strip()!r} — the measurement rounds to "
                f"{rounded}")


def _scale_p95_by_agents(scale_doc: str) -> dict[int, str]:
    """
    The p95 for each agent count in the scale doc's main table.

    The table is read by its header: the row that says `Agents | min |
    p50 | p95 | …` says which column is the p95, and the rows under it
    are read against that. A row of `100 | 7.9 ms | 9.9 ms | 11.0 ms |
    …` therefore gives 11.0 ms for 100 agents — and if the benchmark ever
    adds a column, this keeps reading the right one.
    """
    lines = [ln for ln in scale_doc.splitlines() if ln.strip().startswith("|")]
    header = None
    p95_at = None
    measurements: dict[int, str] = {}
    for line in lines:
        cells = [_plain(c) for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        if header is None:
            if cells[0].lower() == "agents" and "p95" in [c.lower() for c in cells]:
                header = cells
                p95_at = [c.lower() for c in cells].index("p95")
            continue
        if all(set(c) <= set("-: ") for c in cells if c):
            # The `| --- | --- |` separator under the header.
            continue
        first = cells[0]
        if not first.isdigit():
            # A new table starts — one that has no p95 column, or a
            # repeats table whose p95 is the published one.
            break
        if p95_at >= len(cells):
            break
        value = cells[p95_at].replace(" ms", "")
        measurements[int(first)] = value
    return measurements


def test_the_tool_count_in_the_pack_is_the_real_one(pack):
    """The MCP server's tool count is read from the server's own decorators."""
    source = (REPO / "brain" / "mcp_pkg" / "cloudsentinel_mcp" /
              "server.py").read_text(encoding="utf-8")
    count = source.count("@mcp.tool")
    assert count > 0, "the server has no tools"
    # The count is stated in the prose and in the table, and both have to
    # be right — a pitch that says 17 in one place and 18 in another is
    # a pitch that gets caught in the room.
    row = _row_with(pack, "Tools", str(count))
    assert f"{count}" in row, (
        f"the pack's 'Tools' row says {row!r}, but the server has {count} tools")
    cell = _first_cell_of(pack, "Tools")
    assert cell == str(count), (
        f"the pack's 'Tools' cell says {cell!r}, but the server has {count} "
        f"tools")
    _assert_all_statements_agree(
        pack, rf"\*\*{count} tools\*\*|\|\s*MCP server\s*\|", f"{count}",
        "the number of MCP tools")


# ── the check itself has to be able to fail ────────────────────────────────
#
# A test that passes on a correct pack and also passes on a wrong one is
# worth nothing — and this file nearly was that. The first version checked
# that the numbers appeared *somewhere* in the pack, which meant it was
# satisfied by the summary table while the table the reader actually
# looked at said something else. It passed on a pack that lied.
#
# So the file proves it can fail. Each mutation below breaks the pack in
# one specific way, and the test that owns that number has to notice.
# A number that nothing can break is a number nothing checks.

DRIFTS = [
    (
        "the saved money",
        lambda t: t.replace("$2.2344", "$9.9999"),
        "test_the_demo_run_numbers_in_the_pack_are_the_real_ones",
    ),
    (
        "the runs that held",
        lambda t: t.replace("**20/20 runs**", "**19/20 runs**"),
        "test_the_demo_run_numbers_in_the_pack_are_the_real_ones",
    ),
    (
        "the judge's accuracy",
        lambda t: t.replace("| **Accuracy** | 0.914 |", "| **Accuracy** | 0.999 |"),
        "test_the_judge_numbers_in_the_pack_are_the_real_ones",
    ),
    (
        "the case count",
        lambda t: t.replace("115 labelled cases", "120 labelled cases"),
        "test_the_security_numbers_in_the_pack_are_the_real_ones",
    ),
    (
        "a detector's precision",
        lambda t: t.replace(
            "| `tool_description_poisoning` | 40 | 15 | 0 | 0 | 25 | **1.0** | **1.0** |",
            "| `tool_description_poisoning` | 40 | 15 | 0 | 0 | 25 | **0.9** | **1.0** |"),
        "test_the_security_numbers_in_the_pack_are_the_real_ones",
    ),
    (
        "the p95 at 1000 agents",
        lambda t: t.replace("**129.2 ms**", "**129.9 ms**"),
        "test_the_scale_numbers_in_the_pack_match_the_scale_doc",
    ),
    (
        "the p95 in the summary table",
        lambda t: t.replace("p95 **129 ms**", "p95 **199 ms**"),
        "test_the_scale_numbers_in_the_pack_match_the_scale_doc",
    ),
    (
        "the tool count",
        lambda t: t.replace("**17 tools**", "**18 tools**").replace(
            "| Tools | **17** |", "| Tools | **18** |"),
        "test_the_tool_count_in_the_pack_is_the_real_one",
    ),
    (
        "a command that does not exist",
        lambda t: t.replace("python -m brain.backtest", "python -m brain.backtesting"),
        "test_every_command_in_the_pack_is_real",
    ),
    (
        "a Claude cost that was never measured",
        lambda t: t.replace(
            "- **No Claude judge latency or cost.** Never measured. Needs an API key.",
            "- The Claude judge costs $0.0031 per verdict."),
        "test_the_pack_does_not_quote_a_claude_judge_number",
    ),
    (
        "the disclaimer about revenue",
        lambda t: t.replace("revenue", "money"),
        "test_the_pack_says_what_it_does_not_claim",
    ),
    (
        "a section's reproduce command",
        lambda t: t.replace(
            "python -m brain.demo_runner --runs 20 --write docs/research/demo_run.md",
            "see the docs"),
        "test_every_claim_has_a_reproduce_command_near_it",
    ),
]


def _run_one_test(test_name: str) -> subprocess.CompletedProcess:
    """Run one test from this file, in a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "pytest",
         f"brain/tests/test_evidence.py::{test_name}", "-q"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600, check=False,
    )


@pytest.mark.parametrize("label,mutate,test_name", DRIFTS,
                         ids=[d[0] for d in DRIFTS])
def test_a_wrong_number_is_caught(pack, tmp_path, label, mutate, test_name):
    """
    Break the pack in one specific way; the owning test has to notice.

    This is the test that makes the other tests mean something. It writes a
    corrupted copy of the pack to a temporary file, points the check at it,
    and requires the owning test to fail.

    The pack on disk is never touched — a test that corrupts the repo to
    test itself is a test that can leave the repo broken.
    """
    corrupted = tmp_path / "pitch-numbers.md"
    corrupted.write_text(mutate(pack), encoding="utf-8")

    result = _run_test_against(corrupted, test_name)
    assert result.returncode != 0, (
        f"the pack drifted ({label}) and {test_name} did not notice — the "
        f"check is not checking")
    # The failure has to be an *assertion*, not a crash. A subprocess that
    # dies on an import error would "fail" every drift, and the drift test
    # would pass for the wrong reason — which is the same mistake as the
    # one this file exists to catch.
    assert "AssertionError" in result.stdout, (
        f"the drift ({label}) made {test_name} fail, but not with an "
        f"assertion:\n{result.stdout[-1500:]}")


def test_the_drift_harness_can_also_say_nothing_is_wrong(tmp_path, pack):
    """
    The control: an *uncorrupted* pack must make the owning test pass.

    Without this, the drift test above would also be satisfied by a
    harness that fails every run for an unrelated reason — a typo in an
    import, a missing fixture, a pytest that cannot collect the file. The
    harness has to be able to say "no drift", or it has proved nothing.
    """
    same = tmp_path / "pitch-numbers.md"
    same.write_text(pack, encoding="utf-8")

    result = _run_test_against(
        same, "test_the_judge_numbers_in_the_pack_are_the_real_ones")
    assert result.returncode == 0, (
        f"the harness failed on an uncorrupted pack, so it cannot tell "
        f"drift from an unrelated failure:\n{result.stdout[-1500:]}")


def _run_test_against(pack_path: Path, test_name: str) -> subprocess.CompletedProcess:
    """
    Run one of this file's tests against a *different* pack.

    The pack's path is a module constant, so the copy is pointed at by
    running the test with an environment variable that the fixture reads
    instead. That keeps the corrupted copy out of the repository and out
    of the way of the other tests.
    """
    env = {**os.environ, "CS_EVIDENCE_PACK": str(pack_path)}
    return subprocess.run(
        [sys.executable, "-m", "pytest",
         f"brain/tests/test_evidence.py::{test_name}", "-q"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
        check=False, env=env,
    )


# ── the pack must not claim what was never measured ────────────────────────
def test_the_pack_does_not_quote_a_claude_judge_number(pack):
    """
    There is no API key here, so the Claude judge's latency and cost have
    **never been measured**.

    The pack must therefore not quote one. A number that appears with no
    measurement behind it is the exact failure this file exists to prevent,
    and it is worse here than anywhere else — this is the file a pitch is
    read from.
    """
    # Any latency or cost the pack attributes to Claude is a lie.
    for match in re.finditer(r"Claude[^\n]{0,120}", pack):
        line = match.group(0)
        assert not re.search(r"\$[0-9]+\.[0-9]+\s*(?:per|/)\s*verdict", line), (
            f"the pack quotes a Claude cost with no measurement behind it: {line}")
        assert not re.search(r"Claude[^\n]{0,80}latency[^\n]{0,40}[0-9]+\s*ms", line), (
            f"the pack quotes a Claude latency with no measurement behind it: {line}")


def test_the_pack_says_what_it_does_not_claim(pack):
    """
    The pack has a "what this file does not claim" section.

    A pack that only lists strengths is a brochure. The list of limits is
    what makes the numbers believable — and it is the section a sceptical
    investor reads first.
    """
    assert "does not claim" in pack.lower(), (
        "the pack does not say what it does not claim")
    for limit in ("Claude", "revenue", "competitor"):
        assert limit.lower() in pack.lower(), (
            f"the pack does not disclaim {limit}")


def test_every_claim_has_a_reproduce_command_near_it(pack):
    """
    Each numbered section has a command in it.

    A number at the top of a document with one command at the bottom is a
    document where the reader cannot check which number came from where.

    Two shapes of command count. A `python -m brain.…` is a tool that prints
    the number; a `python -m pytest …` is a test that *fails if the number
    moves*, which is the stronger claim and is used where the property is an
    acceptance case (the tick latency). Both are runnable by a stranger, so
    both are a reproduce command.
    """
    sections = re.split(r"\n## ", pack)
    body = [s for s in sections if s[:2].rstrip(".").isdigit()]
    assert len(body) >= 6, f"only {len(body)} numbered sections"
    for section in body:
        title = section.splitlines()[0]
        assert ("python -m brain." in section
                or "python -m pytest" in section), (
            f"the section {title!r} has no reproduce command")
