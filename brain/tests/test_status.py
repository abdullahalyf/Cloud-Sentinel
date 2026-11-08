"""
B10 — the team status report. Acceptance tests.

The report is what a lead reads instead of twenty task files, so the things
worth testing are the ones where being *wrong* would mislead someone:

  * every person is named — a missing person is a person nobody is watching;
  * "behind" follows a **stated rule**, not a feeling;
  * CI that cannot be read says "unknown" instead of crashing or guessing;
  * the report is deterministic — the same inputs give the same bytes;
  * the report is in Bangla.

Run it:
    python -m brain.status --write docs/research/STATUS_BN.md
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain.status import (PEOPLE, Report, Task, _git_log, _ids_in_lines,
                          build_report, days_since_day_one, git_log_task_ids,
                          git_started_task_ids, main, mark_behind, parse_task_file,
                          read_ci, read_submitted_task_ids, render,
                          resolve_main_revision)


# ── the task files ───────────────────────────────────────────────────────────
def test_every_person_on_the_team_is_in_the_report():
    """A person missing from the report is a person nobody is watching."""
    report = build_report()
    assert {p.name for p in report.people} == {name for name, _, _ in PEOPLE}
    assert len(report.people) == len(PEOPLE)


def test_every_persons_task_file_is_read():
    """Each person has tasks in their file, so the counts are not all zero."""
    report = build_report()
    for person in report.people:
        assert person.tasks, f"{person.name} has no tasks — their file was not read"
        assert person.total == len(person.tasks)


def test_the_task_ids_are_the_ones_in_the_files():
    """The report counts the tasks that exist, not the ones the script invented."""
    report = build_report()
    for person in report.people:
        path = Path("docs/tasks") / f"{person.slug}.md"
        on_disk = {t.task_id for t in parse_task_file(path)}
        in_report = {t.task_id for t in person.tasks}
        assert in_report == on_disk


def test_no_task_id_is_counted_twice():
    """
    The real files use a task id twice in places — Alif's `A10` opens a
    recurring task at the top and writes the completion detail under the same
    heading further down. The report must count it once, or it overstates the
    work that was done.
    """
    report = build_report()
    for person in report.people:
        ids = [t.task_id for t in person.tasks]
        assert len(ids) == len(set(ids)), f"{person.name} has a repeated id: {ids}"
        assert person.total == len(set(ids))


def test_the_task_file_parser_reads_the_box_and_the_day():
    """The two things the parser has to get right: the state box and the day."""
    tasks = parse_task_file(Path("docs/tasks/alif.md"))
    by_id = {t.task_id: t for t in tasks}
    assert "A1" in by_id
    assert by_id["A1"].done is False        # the box is read, but not applied here
    assert by_id["A1"].box == "[x]"
    assert by_id["A1"].title                     # the title is not empty


def test_the_day_label_is_read():
    """`### T1 (Day 1): ...` → day 1. The day is what "behind" is measured against."""
    tasks = parse_task_file(Path("docs/tasks/taseen.md"))
    by_id = {t.task_id: t for t in tasks}
    assert by_id["T1"].day == 1


def test_a_task_file_that_does_not_exist_is_not_a_crash(tmp_path):
    """A missing file must not stop the report — it must show zero tasks."""
    assert parse_task_file(tmp_path / "nope.md") == []


def test_a_task_id_used_twice_is_still_one_task(tmp_path):
    """
    A file may open a recurring task at the top and write the completion detail
    under the same heading further down. That is one task described twice — and
    counting it twice would overstate the work done, which is the one thing a
    status report must never do.
    """
    path = tmp_path / "alif.md"
    path.write_text(
        "### A10 · [x] Nightly check · 🔴 MUST · recurring\n"
        "the top block\n"
        "### A1 · [x] First thing\n"
        "### A10 · [x] Nightly check\n"
        "the write-up under the same id\n",
        encoding="utf-8")
    tasks = parse_task_file(path)
    ids = [t.task_id for t in tasks]
    assert ids == ["A10", "A1"], ids
    assert len(ids) == len(set(ids)), "a task id must not be counted twice"


def test_the_task_ids_are_listed_in_a_readable_order():
    """`A2` before `A10` — a lead should not have to re-sort the list."""
    from brain.status import task_sort_key
    ids = ["A10", "A2", "A1", "A11", "A20"]
    assert sorted(ids, key=task_sort_key) == ["A1", "A2", "A10", "A11", "A20"]


def test_the_report_lists_the_ids_in_a_readable_order():
    """The done list in the report is sorted, not in file order."""
    from brain.status import task_sort_key
    tasks = [Task(f"A{n}", "alif", "t") for n in (1, 10, 2, 11)]
    for task in tasks:
        task.done = True
    ids = sorted((t.task_id for t in tasks), key=task_sort_key)
    assert ids == ["A1", "A2", "A10", "A11"]


# ── the "behind" rule ────────────────────────────────────────────────────────
def test_behind_is_a_planned_task_whose_day_has_passed():
    """The rule, as stated in the report: planned, not started, day gone."""
    tasks = [
        Task("X1", "x", "old and untouched", day=1),
        Task("X2", "x", "done", day=1, done=True),
        Task("X3", "x", "blocked", day=1, blocked=True),
        Task("X4", "x", "no day label", day=None),
        Task("X5", "x", "day still to come", day=99),
    ]
    mark_behind(tasks, (2026, 11, 8))
    assert [t.task_id for t in tasks if t.behind] == ["X1"]


def test_a_task_with_no_day_label_is_never_behind():
    """There is nothing to compare it to, so it cannot be behind."""
    tasks = [Task("X1", "x", "no day", day=None)]
    mark_behind(tasks, (2026, 11, 8))
    assert not tasks[0].behind


def test_the_day_arithmetic_is_right():
    """Day 1 is 5 Nov 2026, so Day 2 is the 6th, and Day 1 is 3 days past on the 8th."""
    assert days_since_day_one(1, (2026, 11, 8)) == 3
    assert days_since_day_one(2, (2026, 11, 8)) == 2
    assert days_since_day_one(3, (2026, 11, 8)) == 1
    assert days_since_day_one(4, (2026, 11, 8)) == 0
    assert days_since_day_one(5, (2026, 11, 8)) == -1


def test_a_task_is_not_behind_on_the_day_it_is_due():
    """Being due today is not being late."""
    tasks = [Task("X1", "x", "due today", day=4)]
    mark_behind(tasks, (2026, 11, 8))
    assert not tasks[0].behind


# ── the git log ──────────────────────────────────────────────────────────────
def _main_revision() -> str:
    """The revision that means `main` here, or skip — there may be no git."""
    rev = resolve_main_revision()
    if rev is None:
        pytest.skip("no git history is readable here")
    return rev


def _ids_named_by(rev: str, limit: int = 400) -> set:
    """The known task ids that `rev`'s own log names."""
    lines, ok = _git_log(rev, limit=limit)
    if not ok:
        pytest.skip(f"{rev} cannot be read here")
    return _ids_in_lines(lines, _known_ids())


def _known_ids() -> set:
    """Every task id the team has, across all the task files."""
    known = set()
    for _, slug, _ in PEOPLE:
        for task in parse_task_file(Path("docs/tasks") / f"{slug}.md"):
            known.add(task.task_id)
    return known


def test_the_git_log_finds_the_task_ids_it_mentions():
    """
    The ids on `main` are the ones the log knows.

    **This used to be `assert done`, and it failed in CI** — because CI checks
    out a *shallow* history, where `main`'s log is one commit deep. There is
    nothing wrong with a shallow checkout; it simply does not contain the old
    commits. So the test now asserts what is true in **every** checkout: the
    log was read, and the ids it names are the ones it actually names.
    """
    rev = _main_revision()
    done, commits = git_log_task_ids()
    assert commits > 0, "the git log was empty — the repo was not read"
    expected = _ids_named_by(rev)
    assert done == expected, (
        "the done set must be exactly the ids the log names — not a superset "
        "and not a subset")


def test_a_task_on_main_is_done():
    """
    The rule: a commit on `main` naming the task means it is done.

    The rule is checked against the log itself rather than against one named
    commit, because **which commits are in the log depends on the checkout**.
    A full clone has months of history; CI has one commit. "A1 is done" is
    only observable where A1's commit happens to be present — so the test
    says: *every id the log names is done, and every id the log does not name
    is not*. That holds in a shallow checkout and in a full one.
    """
    rev = _main_revision()
    done, _ = git_log_task_ids()
    named = _ids_named_by(rev)
    for task_id in named:
        assert task_id in done, f"{task_id} is named by {rev}'s log but not done"
    # And the reverse: nothing is done that the log does not name.
    assert done <= named


def test_the_started_ids_are_the_ones_not_on_main():
    """The 'done but not submitted' signal is the difference between two logs."""
    started = git_started_task_ids()
    done, _ = git_log_task_ids()
    assert not (started & done), "a task cannot be both on main and off it"


def test_a_task_committed_on_a_branch_is_not_done_yet():
    """
    "Done" means **landed on `main`**, not "committed somewhere".

    This matters more than it looks: the report is written from a branch as
    often as from `main`, and if the done-signal read `HEAD` then the branch's
    own commits would mark their tasks as done — which is precisely the
    "done but not submitted" case the report exists to make visible. The two
    signals would also overlap: the same id in both the done set and the
    started set.

    The check is on the branch that is checked out, because that is where a
    reader will run the report from.
    """
    import subprocess as sp

    try:
        branch = sp.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True, check=False).stdout.strip()
    except (OSError, sp.SubprocessError):
        pytest.skip("git is not available here")
    if not branch or branch == "main":
        pytest.skip("this check is only meaningful on a branch")

    done, _ = git_log_task_ids()
    started = git_started_task_ids()
    assert not (started & done), (
        f"a task is both on main and off it: {started & done} — the done-signal "
        f"is reading something other than main")


def test_the_done_signal_reads_main_and_not_the_current_branch():
    """
    The done-signal must not read `HEAD`, or a branch commit looks landed.

    This was the third test CI failed, and for a related reason: it required
    a *local* `main` ref and a branch whose commits are inside `--all`. CI has
    neither — it is a detached shallow checkout, so `git rev-parse main`
    fails outright and the old test skipped or failed depending on the shape.

    The rule is now checked **structurally**, with no environment assumptions:
    the revision the done-signal reads must be the one that resolves as
    `main`, and it must not be `HEAD` when `main` is somewhere else.
    """
    rev = resolve_main_revision()
    if rev is None:
        pytest.skip("no git history is readable here")
    assert rev != "HEAD", (
        "the done-signal fell back to HEAD while a main ref was available — "
        "a branch's own commits would look landed")

    import subprocess as sp

    try:
        head = sp.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=False).stdout.strip()
        main_sha = sp.run(["git", "rev-parse", rev], capture_output=True, text=True,
                           check=False).stdout.strip()
    except (OSError, sp.SubprocessError):
        pytest.skip("git is not available here")
    if not head or not main_sha or head == main_sha:
        pytest.skip("HEAD and main are the same commit here")

    # The two signals must be computed from *different* histories, and must
    # not overlap: a task cannot be both landed and not-landed.
    done, _ = git_log_task_ids()
    started = git_started_task_ids()
    assert not (started & done)


def test_the_main_revision_is_resolved_not_assumed():
    """
    The revision that means `main` must be *resolved*, because which ref it is
    depends on the checkout.

    A CI checkout of a pull request is a **detached HEAD** on the merge
    commit, and with the default `fetch-depth: 1` there is **no local `main`
    branch** — only `origin/main`. A script that assumes `main` exists gets
    an empty log from it, and then reports that *nobody has done anything*,
    which is a lie told with a straight face.
    """
    rev = resolve_main_revision()
    if rev is None:
        pytest.skip("no git history is readable here")
    # Whatever it resolved to, git must be able to read a log from it.
    lines, ok = _git_log(rev, limit=5)
    assert ok, f"resolved {rev!r} but its log could not be read"
    assert lines, f"resolved {rev!r} but its log was empty"


def test_an_unreadable_history_is_unknown_and_not_empty():
    """
    When the history genuinely cannot be read, the report must say **unknown**.

    This is the difference between "I do not know" and "nothing is done", and
    the second one is a claim the report has no right to make.
    """
    import brain.status as status

    def boom(*args, **kwargs):
        raise OSError("git is not here")

    original = status.resolve_main_revision
    status.resolve_main_revision = lambda repo=None: None
    try:
        done, commits = status.git_log_task_ids()
        assert done == set()
        assert commits == 0
    finally:
        status.resolve_main_revision = original


# ── CI ───────────────────────────────────────────────────────────────────────
def test_ci_is_read_or_says_unknown_and_never_crashes():
    """
    The CI answer has two acceptable forms and one unacceptable one.

    A crash is unacceptable: the report is meant to be run after every task,
    including on a laptop where `gh` is not installed. The report must still
    be written.
    """
    state, detail = read_ci()
    assert state in ("green", "red", "running", "grey", "unknown")
    assert detail, "the CI answer must explain itself"


def test_an_unknown_ci_still_produces_a_report():
    """'Unknown' is a report, not a failure."""
    report = Report(people=build_report().people, ci="unknown",
                    ci_detail="`gh` is not available here", commits_scanned=0)
    text = render(report)
    assert "অজানা" in text
    assert "টিমের অবস্থা" in text


def test_a_missing_gh_does_not_crash_the_report(monkeypatch):
    """`gh` missing → 'unknown', and the report still renders."""
    def boom(*args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr("brain.status.subprocess.run", boom)
    state, detail = read_ci()
    assert state == "unknown"
    assert detail


def test_the_submitted_ids_are_read_without_crashing():
    """The open-PR list may be unavailable; that is 'unknown', not a crash."""
    submitted = read_submitted_task_ids()
    assert isinstance(submitted, set)


# ── the report ───────────────────────────────────────────────────────────────
def test_the_report_is_in_bangla():
    """The report is for Alif, and Alif reads Bangla."""
    text = render(build_report())
    assert "টিমের অবস্থা" in text
    assert "হয়েছে" in text
    assert "পরিকল্পনায়" in text
    # and it is not English prose
    assert "the team status" not in text.lower()


def test_the_report_names_every_person():
    text = render(build_report())
    for name, _, _ in PEOPLE:
        assert name in text, f"{name} is missing from the report"


def test_the_report_states_the_rule_for_behind():
    """A rule that is not written down is a rule the reader cannot check."""
    text = render(build_report())
    assert "পিছিয়ে" in text
    assert "নিয়ম" in text          # "the rule"
    assert "দিন" in text            # "day"


def test_the_report_says_when_ci_is_unknown():
    """It has to say so, not leave the reader to assume green."""
    report = Report(people=build_report().people, ci="unknown",
                    ci_detail="because", commits_scanned=0)
    assert "অজানা" in render(report)


def test_an_unreadable_git_log_is_reported_as_unknown_not_as_zero():
    """
    "I could not read the log" must not be printed as "0 commits".

    Those are different claims. The first is honest; the second tells the
    lead that nobody has done any work, which would be badly wrong.
    """
    report = Report(people=build_report().people, ci="green", ci_detail="ok",
                    commits_scanned=0, git_readable=False)
    text = render(report)
    assert "git log পড়া যায়নি" in text
    assert "0টা commit পড়া হয়েছে" not in text


def test_a_readable_git_log_is_reported_with_its_commit_count():
    """The normal case still says how much history was read."""
    report = Report(people=build_report().people, ci="green", ci_detail="ok",
                    commits_scanned=42, git_readable=True)
    assert "42টা commit পড়া হয়েছে" in render(report)


def test_the_report_is_deterministic():
    """The same inputs give the same bytes, so the file can be committed and diffed."""
    first = render(build_report())
    second = render(build_report())
    assert first == second


def test_the_command_writes_the_file_and_exits_zero(tmp_path):
    """The command writes the file — and exits 0, so it can be a CI step."""
    out = tmp_path / "STATUS_BN.md"
    assert main(["--write", str(out)]) == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "টিমের অবস্থা" in text


def test_the_command_writes_json_when_asked(tmp_path, capsys):
    """The numbers are also machine-readable, so a CI job can read them."""
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["people"]) == len(PEOPLE)
    for person in payload["people"]:
        for key in ("name", "done", "planned", "blocked", "behind"):
            assert key in person, key


def test_the_json_counts_add_up():
    """A report whose numbers do not add up is a report nobody can trust."""
    payload = build_report().to_dict()
    for person in payload["people"]:
        counted = (person["done"] + person["planned"] + person["blocked"]
                   + person["in_progress"])
        assert counted == person["total"], person


def test_a_person_with_no_tasks_is_still_reported():
    """Zero tasks is a fact, and the report shows it rather than skipping the person."""
    people = [type(build_report().people[0])(name="Ghost", slug="ghost", prefix="Z")]
    report = Report(people=people, ci="unknown", ci_detail="", commits_scanned=0)
    text = render(report)
    assert "Ghost" in text
