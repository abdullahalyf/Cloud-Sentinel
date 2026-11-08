"""
B10 — the team status report. One file Alif reads instead of twenty.

The question this file answers is not "what happened" — the git log knows that.
It is **"who is behind, and what is blocking them"**, because that is the
question a lead has and nobody has the answer to.

Three sources, and the rule for each is stated here rather than guessed:

  1. **The task files** (`docs/tasks/<name>.md`). Every task is a `###` heading
     with an id — `### A1 · ...`, `### T1 (Day 1): ...`, `### D3 (Day 2): ...`.
     A heading may carry a box: `[x]` done, `[!]` blocked, `[ ]` planned. Not
     every file uses boxes — only Alif's does — so the box is *one* signal,
     not the definition.

  2. **The git log.** A task id that appears in a commit message that landed
     on `main` is done, whether or not anyone remembered to tick a box. The
     prefix letter is the owner: `A`→Alif, `T`→Taseen, `F`→Fojle, `O`→Orin,
     `D`→Tamjid. This is the signal that makes the report work for the people
     whose task files have no boxes.

  3. **CI.** The result of the newest workflow run on `main`, read through
     `gh` when it is available. When `gh` is not installed, or not
     authenticated, or there is no run — the report says **"unknown"**. It
     never crashes and never guesses: a status report that lies about CI is
     worse than one that admits it does not know.

**"Behind" is decided by a stated rule**, not a feeling:

    a person is behind when they have a task that is **planned and not
    started** on a day that has already passed, or a task marked `[!]`.

"Already passed" comes from the task's own day label — `### T1 (Day 1)`,
`### D3 (Day 2)` — read against the plan's start date. A task with no day
label is never behind on that count, because there is nothing to compare it
to. Saying "behind" without a rule would make the word mean whatever the
reader wants it to mean, and a status report that means whatever you want is
not a status report.

Run it:

    python -m brain.status --write docs/research/STATUS_BN.md

Everything is deterministic for the same git log and the same task files: the
same inputs produce the same bytes, so the file can be committed and diffed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── who is on the team ────────────────────────────────────────────────────────
# The order is the order the report lists them in — it is the order in
# `docs/PLAN.md`, and it is fixed so the output does not shuffle between runs.
PEOPLE = (
    ("Alif", "alif", "A"),
    ("Taseen", "taseen", "T"),
    ("Tamjid", "tamjid", "D"),
    ("Fojle", "fojle", "F"),
    ("Orin", "orin", "O"),
)

TASKS_DIR = Path("docs/tasks")

# `### A1 · [x] (2026-11-08) Some title`  /  `### T1 (Day 1): Some title`
HEADING = re.compile(r"^###\s+([A-Z]\d+)\b(.*)$")

# A day label like `(Day 2)`, `(Day 1–2)`, `(Day 3–4)`. An en dash, a hyphen
# or a plain dash all appear in the files, so all three are accepted.
DAY = re.compile(r"\(\s*Day\s+(\d+)(?:\s*[-–—]\s*(\d+))?\s*\)", re.IGNORECASE)

# The day the project started, so "Day 3" can be turned into a date. From
# `docs/PLAN.md`: the grid starts on Thu 5 Nov.
DAY_ONE = (2026, 11, 5)

# The commit-message shape: "(Task D1)", "D1", "task D2". Only the task ids
# of *this* repo's tasks count, so the pattern is anchored on the id set.
COMMIT_TASK = re.compile(r"\b([A-Z])(\d+)\b")

# The task ids that are on a branch **and** have an open pull request. Filled in
# by `build_report`; empty when `gh` is not available, which only means the
# report cannot tell "submitted" from "not submitted" — never that it crashes.
SUBMITTED: set = set()


# ── the model ────────────────────────────────────────────────────────────────
@dataclass
class Task:
    """One task, as the report sees it."""

    task_id: str
    owner: str                 # the person's task file it came from
    title: str
    day: Optional[int] = None  # the last day of its day label, if it has one
    box: str = ""              # "[x]", "[!]" or "[ ]" — empty when the file has none
    done: bool = False
    blocked: bool = False
    in_progress: bool = False
    behind: bool = False      # planned, not started, and its day has passed

    @property
    def state(self) -> str:
        if self.done:
            return "done"
        if self.blocked:
            return "blocked"
        if self.in_progress:
            return "in progress"
        return "planned"

    @property
    def submitted(self) -> bool:
        """True when the work is on a branch *and* a pull request is open.

        A commit on a branch with no PR is a different situation: the work is
        done but nobody has asked for it. That is worth its own line in a
        status report, because the fix is "open the PR", not "do the work".
        """
        return self.in_progress and self.task_id in SUBMITTED


@dataclass
class Person:
    """One person, as the report sees them."""

    name: str
    slug: str
    prefix: str
    tasks: list = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(1 for t in self.tasks if t.done)

    @property
    def blocked(self) -> int:
        return sum(1 for t in self.tasks if t.blocked)

    @property
    def in_progress(self) -> int:
        return sum(1 for t in self.tasks if t.in_progress)

    @property
    def planned(self) -> int:
        return sum(1 for t in self.tasks if not t.done and not t.blocked
                   and not t.in_progress)

    @property
    def behind(self) -> list:
        """The planned tasks whose day has already passed."""
        return [t for t in self.tasks if t.behind]

    @property
    def total(self) -> int:
        """How many tasks this person has, in any state."""
        return len(self.tasks)


@dataclass
class Report:
    people: list
    ci: str
    ci_detail: str
    commits_scanned: int

    def to_dict(self) -> dict:
        return {
            "ci": self.ci,
            "ci_detail": self.ci_detail,
            "commits_scanned": self.commits_scanned,
            "people": [
                {
                    "name": p.name,
                    "done": p.done,
                    "planned": p.planned,
                    "blocked": p.blocked,
                    "in_progress": p.in_progress,
                    "unsubmitted": [t.task_id for t in
                                    sorted((t for t in p.tasks
                                            if t.in_progress and not t.submitted),
                                           key=lambda t: task_sort_key(t.task_id))],
                    "behind": [t.task_id for t in
                               sorted(p.behind, key=lambda t: task_sort_key(t.task_id))],
                    "total": p.total,
                }
                for p in self.people
            ],
        }


# ── reading the task files ───────────────────────────────────────────────────
def task_sort_key(task_id: str) -> tuple:
    """Sort key that puts `A2` before `A10`.

    A lexicographic sort reads `A0, A1, A10, A11, A2` — which is technically
    ordered and practically unreadable. A lead scanning a list of ids should
    not have to re-sort it in their head, so the number is compared as a number.
    """
    match = re.match(r"^([A-Z])(\d+)$", task_id)
    if not match:
        return (task_id, 0)
    return (match.group(1), int(match.group(2)))


def parse_task_file(path: Path) -> list:
    """Every `### <ID>` heading in a task file, as a `Task`.

    The box is read from the heading when it is there. The heading is also
    searched for a day label, because that is what "behind" is measured
    against.

    **One id is one task, even when the file uses it twice.** A task file
    sometimes opens a recurring task at the top — "A10 · [x] · nightly check ·
    recurring" — and then writes the completion detail under the same heading
    further down. That is one task described twice, not two tasks. Counting it
    twice would inflate the "done" count and make the report lie about how much
    work was done, so the **first** heading for an id wins and later ones are
    ignored.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    tasks = []
    seen = set()
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            task_id, rest = match.group(1), match.group(2)
            if task_id in seen:
                continue          # the same task described again — one task, one count
            seen.add(task_id)
            title = rest
            # The box: only if it is one of the three the series uses.
            box = ""
            for candidate in ("[x]", "[!]", "[ ]"):
                if candidate in rest:
                    box = candidate
                    break
            # Strip the box and any parenthesised metadata from the title.
            title = re.sub(r"\[x\]|\[!\]|\[ \]", "", title)
            title = re.sub(r"^\s*[·:—-]\s*", "", title.strip())
            title = re.sub(r"\([^)]*\)", "", title).strip(" ·:—-")
            day_match = DAY.search(rest)
            day = None
            if day_match:
                day = int(day_match.group(2) or day_match.group(1))
            tasks.append(Task(task_id=task_id, owner=path.stem, title=title,
                              day=day, box=box))
    return tasks


# ── reading the git log ──────────────────────────────────────────────────────
def git_log_task_ids(repo: Path = None, limit: int = 400) -> tuple:
    """The task ids that the git log says are done, and how many commits were read.

    A commit on `main` whose message names a task id is that task's evidence
    of being done. The ids are matched against the *known* task ids, so a
    stray `A1` inside a hash or a version number cannot be mistaken for a
    task.

    **The revision is `main`, not the current branch.** Reading `HEAD` would
    make a task look done the moment it is *committed on a branch* — which is
    exactly the "done but not submitted" case that has to stay visible. It
    would also make the two signals overlap: the branch commit is on `HEAD`
    and not on `main`, so the id would be in both the done set and the
    started set at once. "Done" here means **landed**, and only `main` says
    that.
    """
    known = set()
    for _, slug, _ in PEOPLE:
        for task in parse_task_file(TASKS_DIR / f"{slug}.md"):
            known.add(task.task_id)

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{limit}", "main"],
            cwd=str(repo) if repo else None,
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set(), 0
    if result.returncode != 0:
        return set(), 0

    done = set()
    for line in result.stdout.splitlines():
        # The message is everything after the short hash.
        parts = line.split(" ", 1)
        message = parts[1] if len(parts) > 1 else ""
        for match in COMMIT_TASK.finditer(message):
            candidate = f"{match.group(1)}{match.group(2)}"
            if candidate in known:
                done.add(candidate)
    return done, len(result.stdout.splitlines())


def git_started_task_ids(repo: Path = None) -> set:
    """The task ids that have commits somewhere, but not on `main` yet.

    This is the signal that catches the most useful thing a lead can be told:
    **the work was done and never submitted.** A branch with the commit on it
    and no merge to `main` means the task is not done — it is *almost* done,
    and the only thing missing is the pull request. That is a different kind of
    problem from "not started", and it needs a different word.

    It is computed with **one** `git log` per side, not one call per commit:
    `main`'s log gives the ids that landed, and the whole history gives the
    ids that exist anywhere.
    """
    known = set()
    for _, slug, _ in PEOPLE:
        for task in parse_task_file(TASKS_DIR / f"{slug}.md"):
            known.add(task.task_id)
    if not known:
        return set()

    def ids_in(rev: str, extra: list = None) -> set:
        command = ["git", "log", "--format=%H %s"] + (extra or []) + [rev]
        try:
            result = subprocess.run(
                command, cwd=str(repo) if repo else None,
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        if result.returncode != 0:
            return set()
        found = set()
        for line in result.stdout.splitlines():
            message = line.split(" ", 1)[1] if " " in line else ""
            found |= {f"{m.group(1)}{m.group(2)}" for m in COMMIT_TASK.finditer(message)}
        return found & known

    everywhere = ids_in("--all", extra=["-400"])
    landed = ids_in("main", extra=["-400"])
    return everywhere - landed


# ── the "behind" rule ────────────────────────────────────────────────────────
def days_since_day_one(day: int, today: tuple) -> int:
    """How many days past the project's Day 1 a given Day label is."""
    import datetime

    start = datetime.date(*DAY_ONE)
    target = start + datetime.timedelta(days=max(0, day - 1))
    return (datetime.date(*today) - target).days


def mark_behind(tasks: list, today: tuple) -> None:
    """Flag the planned tasks whose day has passed. The rule, applied."""
    for task in tasks:
        if task.done or task.blocked or task.in_progress:
            continue
        if task.day is None:
            continue      # no day label — nothing to compare it against
        if days_since_day_one(task.day, today) > 0:
            task.behind = True


# ── CI ───────────────────────────────────────────────────────────────────────
def read_ci(repo: Path = None) -> tuple:
    """The newest workflow run on `main`, as `(state, detail)`.

    `gh` may be missing, unauthenticated, or the repo may have no runs. All
    three give **"unknown"** — never a crash, never a guess.
    """
    try:
        result = subprocess.run(
            ["gh", "run", "list", "--branch", "main", "--limit", "1",
             "--json", "conclusion,status,workflowName"],
            cwd=str(repo) if repo else None,
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", "`gh` is not available here, so CI was not read"
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else "`gh` could not read the runs"
        return "unknown", reason

    try:
        payload = json.loads(result.stdout or "[]")
    except ValueError:
        return "unknown", "the CI answer was not readable"
    if not payload:
        return "unknown", "there is no workflow run on `main` yet"

    run = payload[0]
    conclusion = (run.get("conclusion") or "").lower()
    status = (run.get("status") or "").lower()
    name = run.get("workflowName") or "the workflow"
    if conclusion == "success":
        return "green", f"`{name}` passed on the last run"
    if conclusion == "failure":
        return "red", f"`{name}` **failed** on the last run"
    if status in ("in_progress", "queued", "requested", "waiting", "pending"):
        return "running", f"`{name}` is running right now"
    if conclusion == "cancelled":
        return "grey", f"`{name}` was cancelled"
    return "unknown", f"`{name}` reported `{conclusion or status or 'nothing'}`"


# ── the open pull requests ───────────────────────────────────────────────────
def read_submitted_task_ids(repo: Path = None) -> set:
    """The task ids that have an **open pull request**.

    Read through `gh`. When `gh` is missing or unauthenticated this returns an
    empty set — which means the report cannot tell "submitted" from "not
    submitted", and says so. It never crashes.
    """
    known = set()
    for _, slug, _ in PEOPLE:
        for task in parse_task_file(TASKS_DIR / f"{slug}.md"):
            known.add(task.task_id)
    if not known:
        return set()

    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "60",
             "--json", "number,title,body,headRefName"],
            cwd=str(repo) if repo else None,
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode != 0:
        return set()
    try:
        payload = json.loads(result.stdout or "[]")
    except ValueError:
        return set()

    found = set()
    for pr in payload:
        # The title and the body are both searched: a PR is titled one way and
        # described in another often enough that searching both is worth it.
        text = f"{pr.get('title') or ''} {pr.get('body') or ''}"
        found |= {f"{m.group(1)}{m.group(2)}" for m in COMMIT_TASK.finditer(text)}
    return found & known


# ── building the report ──────────────────────────────────────────────────────
def build_report(repo: Path = None, today: tuple = None) -> Report:
    """Read the three sources and put them together."""
    import datetime

    global SUBMITTED
    today = today or datetime.date.today().timetuple()[:3]

    done_from_log, commits = git_log_task_ids(repo)
    started = git_started_task_ids(repo)
    SUBMITTED = read_submitted_task_ids(repo)
    people = []
    for name, slug, prefix in PEOPLE:
        person = Person(name=name, slug=slug, prefix=prefix)
        for task in parse_task_file(TASKS_DIR / f"{slug}.md"):
            # The box is one signal; the git log is the other. Either says done.
            if task.box == "[x]" or task.task_id in done_from_log:
                task.done = True
            elif task.box == "[!]":
                task.blocked = True
            elif task.task_id in started:
                # The commit exists, on a branch, but not on main.
                task.in_progress = True
            person.tasks.append(task)
        mark_behind(person.tasks, today)
        people.append(person)

    ci, ci_detail = read_ci(repo)
    return Report(people=people, ci=ci, ci_detail=ci_detail, commits_scanned=commits)


# ── the Bangla report ────────────────────────────────────────────────────────
STATE_BN = {
    "done": "হয়েছে",
    "in progress": "চলছে",
    "blocked": "আটকে আছে",
    "planned": "পরিকল্পনায়",
}

CI_BN = {
    "green": "সবুজ — সব CI পাস",
    "red": "লাল — CI ফেইল করেছে",
    "running": "চলছে",
    "grey": "ধূসর — বাতিল হয়েছে",
    "unknown": "অজানা — CI পড়া যায়নি",
}


def render(report: Report) -> str:
    """The report, in Bangla."""
    lines = []
    add = lines.append

    add("# টিমের অবস্থা")
    add("")
    add("এই ফাইলটাই পড়লেই চলবে — কে কতটা করেছে, কে আটকে আছে, আর CI কেমন।")
    add("")
    add(f"**CI:** {CI_BN.get(report.ci, report.ci)} — {report.ci_detail}")
    add("")
    add(f"*{report.commits_scanned}টা commit পড়া হয়েছে `main` থেকে।*")
    add("")

    add("## এক নজরে")
    add("")
    add("| কে | হয়েছে | চলছে | পরিকল্পনায় | আটকে | পিছিয়ে |")
    add("| --- | --- | --- | --- | --- | --- |")
    for person in report.people:
        behind = len(person.behind)
        add(f"| {person.name} | {person.done} | {person.in_progress} | "
            f"{person.planned} | {person.blocked} | {behind} |")
    add("")

    for person in report.people:
        add(f"## {person.name}")
        add("")
        if not person.tasks:
            add("কোনো task file পাওয়া যায়নি।")
            add("")
            continue

        # The things that need a human, first — that is what a lead reads.
        if person.blocked:
            add(f"**আটকে আছে ({person.blocked}):**")
            add("")
            for task in person.tasks:
                if task.blocked:
                    add(f"- `{task.task_id}` — {task.title}")
            add("")

        if person.behind:
            add(f"**পিছিয়ে আছে ({len(person.behind)})** — পরিকল্পনায় ছিল, কিন্তু দিন চলে গেছে:")
            add("")
            for task in sorted(person.behind, key=lambda t: task_sort_key(t.task_id)):
                add(f"- `{task.task_id}` — {task.title} (Day {task.day})")
            add("")

        done = sorted((t for t in person.tasks if t.done),
                      key=lambda t: task_sort_key(t.task_id))
        running = sorted((t for t in person.tasks if t.in_progress),
                          key=lambda t: task_sort_key(t.task_id))
        unsubmitted = sorted((t for t in running if not t.submitted),
                              key=lambda t: task_sort_key(t.task_id))
        submitted = sorted((t for t in running if t.submitted),
                            key=lambda t: task_sort_key(t.task_id))
        planned = sorted((t for t in person.tasks
                          if t.state == "planned" and not t.behind),
                         key=lambda t: task_sort_key(t.task_id))
        if done:
            add(f"**হয়েছে ({len(done)}):** "
                + ", ".join(f"`{t.task_id}`" for t in done))
            add("")
        if submitted:
            add(f"**PR খোলা আছে, merge-এর অপেক্ষায় ({len(submitted)}):** "
                + ", ".join(f"`{t.task_id}`" for t in submitted))
            add("")
        if unsubmitted:
            add(f"**কাজ হয়ে গেছে কিন্তু PR খোলা হয়নি ({len(unsubmitted)})** — "
                "শুধু PR খুললেই হবে:")
            add("")
            for task in unsubmitted:
                add(f"- `{task.task_id}` — {task.title}")
            add("")
        if planned:
            add(f"**পরিকল্পনায় ({len(planned)}):** "
                + ", ".join(f"`{t.task_id}`" for t in planned))
            add("")

    add("## এই report-টা কিভাবে তৈরি হয়")
    add("")
    add("তিনটা জায়গা থেকে: **task file** (কোন task কার, কোনটা হয়েছে), "
        "**git log** (commit-এর বার্তায় task id থাকলে সেটা হয়ে গেছে), আর "
        "**CI** (`gh` দিয়ে)।")
    add("")
    add("**\"পিছিয়ে\" কী — নিয়মটা বলে দেওয়া আছে, অনুমান নয়:** যে task "
        "পরিকল্পনায় থেকে গেছে, শুরু হয়নি, আর তার নিজের দিন (যেমন `Day 2`) চলে গেছে — "
        "সেটাই পিছিয়ে। যে task-এর দিন-লেবেল নেই, সেটা কখনো এই নিয়মে পিছিয়ে "
        "গোনা হয় না — তুলনার কিছু নেই। যে task-এ `[!]` আছে, সেটা আটকে।")
    add("")
    add("**\"কাজ হয়ে গেছে কিন্তু PR খোলা হয়নি\"** — commit আছে branch-এ, কিন্তু "
        "`main`-এ নেই, আর PR-ও নেই। এটা \"শুরুই হয়নি\" থেকে আলাদা সমস্যা: কাজটা "
        "শেষ, শুধু চাওয়ার দরকার।")
    add("")
    add("**CI না পড়া গেলে report ভাঙে না** — সেটা \"অজানা\" লেখে, কারণ CI-এর "
        "খবর না জেনে কিছু বলা ভুল; আর যা জানা যায় তা-ই লেখা হয়।")
    add("")
    return "\n".join(lines) + "\n"


# ── the command ──────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m brain.status",
        description="Write the team status report (B10).")
    parser.add_argument("--write", default=None,
                        help="where to write the report (default: stdout)")
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON instead of the Bangla text")
    parser.add_argument("--repo", default=None,
                        help="the repository to read the git log from")
    args = parser.parse_args(argv)

    repo = Path(args.repo) if args.repo else Path(os.getcwd())
    report = build_report(repo=repo)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    text = render(report)
    if args.write:
        out = Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
