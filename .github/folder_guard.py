"""
Folder-guard CI check (ARCHITECTURE / AGENTS.md / Taseen T1).
Ensures branches only edit files within their owner's domain.

Rules:
- taseen/   → anything
- fojle/    → telemetry/, shared/store.py
- orin/     → eval/
- tamjid/   → dashboard/
- alif/     → brain/, docs/tasks/alif.md, docs/SUMMARY_BN.md, docs/research/
- contract/ → shared/, docs/CONTRACTS.md, docs/ARCHITECTURE.md, telemetry/db/schema.sql, shared/mocks/, .env.example
- Any branch may also edit docs/tasks/*.md ("Notes" and "Contract requests" sections)
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys

PREFIX_RULES = {
    "fojle/": lambda path: path.startswith("telemetry/") or path == "shared/store.py",
    "orin/": lambda path: path.startswith("eval/"),
    "tamjid/": lambda path: path.startswith("dashboard/"),
    "alif/": lambda path: (
        path.startswith("brain/")
        or path == "docs/tasks/alif.md"
        or path == "docs/SUMMARY_BN.md"
        or path.startswith("docs/research/")
    ),
    "contract/": lambda path: (
        path.startswith("shared/")
        or path in {
            "docs/CONTRACTS.md",
            "docs/ARCHITECTURE.md",
            "telemetry/db/schema.sql",
            ".env.example",
        }
    ),
    "taseen/": lambda path: True,
}


def normalize_path(path: str) -> str:
    p = path.replace("\\", "/").strip().strip('"').strip("'")
    if p.startswith("./"):
        p = p[2:]
    return p


def is_allowed(branch: str, path: str) -> bool:
    norm_path = normalize_path(path)
    if not norm_path:
        return True

    # Any branch may edit task files (for Notes and Contract requests sections)
    if fnmatch.fnmatch(norm_path, "docs/tasks/*.md"):
        return True

    for prefix, rule in PREFIX_RULES.items():
        if branch.startswith(prefix):
            return rule(norm_path)

    return False


def get_changed_files(base_ref: str = "origin/main") -> list[str]:
    # Try the requested base_ref, then fallbacks without remote prefix
    candidates = [base_ref]
    if "origin/" in base_ref:
        candidates.append(base_ref.replace("origin/", ""))
    candidates.append("main")

    for ref in candidates:
        try:
            out = subprocess.check_output(
                ["git", "diff", "--name-only", f"{ref}...HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return [normalize_path(line) for line in out.splitlines() if line.strip()]
        except subprocess.CalledProcessError:
            continue

    # If local refs aren't resolved yet (e.g. shallow PR fetch), fetch origin main explicitly
    try:
        subprocess.check_call(["git", "fetch", "origin", "main"], stderr=subprocess.DEVNULL)
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return [normalize_path(line) for line in out.splitlines() if line.strip()]
    except Exception as exc:
        print(f"Error: git diff against base refs failed: {exc}", file=sys.stderr)
        raise


def run_self_tests() -> None:
    print("Running folder guard self-tests...")
    # orin
    assert is_allowed("orin/test", "eval/roi.py")
    assert is_allowed("orin/test", "eval/tests/test_roi.py")
    assert is_allowed("orin/test", "docs/tasks/orin.md")
    assert is_allowed("orin/test", "docs/tasks/alif.md")
    assert not is_allowed("orin/test", "brain/engine.py")
    assert not is_allowed("orin/test", "telemetry/collector/app.py")

    # fojle
    assert is_allowed("fojle/db", "telemetry/collector/app.py")
    assert is_allowed("fojle/db", "telemetry/db/schema.sql")
    assert is_allowed("fojle/db", "shared/store.py")
    assert is_allowed("fojle/db", "docs/tasks/fojle.md")
    assert not is_allowed("fojle/db", "shared/config.py")
    assert not is_allowed("fojle/db", "brain/engine.py")

    # tamjid
    assert is_allowed("tamjid/ui", "dashboard/app.py")
    assert is_allowed("tamjid/ui", "dashboard/api_client.py")
    assert is_allowed("tamjid/ui", "docs/tasks/tamjid.md")
    assert not is_allowed("tamjid/ui", "brain/api.py")

    # alif
    assert is_allowed("alif/a1", "brain/engine.py")
    assert is_allowed("alif/a1", "brain/judge.py")
    assert is_allowed("alif/a1", "docs/tasks/alif.md")
    assert is_allowed("alif/a1", "docs/SUMMARY_BN.md")
    assert is_allowed("alif/a1", "docs/research/judge-eval.md")
    assert is_allowed("alif/a1", "docs/tasks/taseen.md")
    assert not is_allowed("alif/a1", "shared/contracts.py")
    assert not is_allowed("alif/a1", "dashboard/app.py")

    # contract
    assert is_allowed("contract/c1", "shared/contracts.py")
    assert is_allowed("contract/c1", "shared/mocks/mock_api.py")
    assert is_allowed("contract/c1", "docs/CONTRACTS.md")
    assert is_allowed("contract/c1", "docs/ARCHITECTURE.md")
    assert is_allowed("contract/c1", "telemetry/db/schema.sql")
    assert is_allowed("contract/c1", ".env.example")
    assert is_allowed("contract/c1", "docs/tasks/contract.md")
    assert not is_allowed("contract/c1", "brain/engine.py")
    assert not is_allowed("contract/c1", "dashboard/app.py")

    # taseen
    assert is_allowed("taseen/t1", "infra/executor/docker_exec.py")
    assert is_allowed("taseen/t1", ".github/workflows/ci.yml")
    assert is_allowed("taseen/t1", ".gitleaks.toml")
    assert is_allowed("taseen/t1", "docker-compose.yml")
    assert is_allowed("taseen/t1", "README.md")
    assert is_allowed("taseen/t1", "brain/engine.py")

    # unknown prefix
    assert not is_allowed("random/branch", "brain/engine.py")
    assert is_allowed("random/branch", "docs/tasks/alif.md")

    print("All folder guard self-tests passed successfully!")


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudSentinel Folder Guard CI Check")
    parser.add_argument("--branch", default=None, help="Head branch name (defaults to GITHUB_HEAD_REF or git HEAD)")
    parser.add_argument("--base", default="origin/main", help="Base ref for diff (default: origin/main)")
    parser.add_argument("--self-test", action="store_true", help="Run internal self-tests")
    args = parser.parse_args()

    if args.self_test:
        run_self_tests()
        sys.exit(0)

    branch = (
        args.branch
        or os.environ.get("GITHUB_HEAD_REF")
        or os.environ.get("BRANCH")
        or ""
    ).strip()

    if not branch:
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
            ).strip()
        except Exception:
            branch = ""

    print(f"Folder guard: checking branch '{branch}' against base '{args.base}'")

    if not branch:
        print("Error: Could not determine branch name.", file=sys.stderr)
        sys.exit(1)

    if branch.startswith("dependabot/"):
        print(f"Skipping folder guard for automated branch '{branch}'.")
        sys.exit(0)

    matched_prefix = next((p for p in PREFIX_RULES if branch.startswith(p)), None)
    if not matched_prefix:
        print(
            f"Error: Branch '{branch}' does not match any allowed prefix.\n"
            f"Allowed prefixes: {', '.join(sorted(PREFIX_RULES.keys()))} (see AGENTS.md).",
            file=sys.stderr,
        )
        sys.exit(1)

    changed_files = get_changed_files(args.base)
    if not changed_files:
        print(f"No files changed between {args.base} and {branch}.")
        sys.exit(0)

    print(f"Changed files ({len(changed_files)}):")
    for f in changed_files:
        print(f"  - {f}")

    disallowed = [f for f in changed_files if not is_allowed(branch, f)]

    if disallowed:
        print(f"\nFolder guard violation on branch '{branch}':", file=sys.stderr)
        print(f"Prefix '{matched_prefix}' cannot modify:", file=sys.stderr)
        for f in disallowed:
            print(f"  ❌ {f}", file=sys.stderr)
        print("\nAllowed folders per AGENTS.md:", file=sys.stderr)
        print("  - fojle/    → telemetry/, shared/store.py, docs/tasks/*.md", file=sys.stderr)
        print("  - orin/     → eval/, docs/tasks/*.md", file=sys.stderr)
        print("  - tamjid/   → dashboard/, docs/tasks/*.md", file=sys.stderr)
        print("  - alif/     → brain/, docs/tasks/alif.md, docs/SUMMARY_BN.md, docs/research/, docs/tasks/*.md", file=sys.stderr)
        print("  - contract/ → shared/, docs/CONTRACTS.md, docs/ARCHITECTURE.md, telemetry/db/schema.sql, .env.example, docs/tasks/*.md", file=sys.stderr)
        print("  - taseen/   → anything", file=sys.stderr)
        sys.exit(1)

    print(f"\nFolder guard passed: all {len(changed_files)} changed file(s) are permitted for '{branch}'.")


if __name__ == "__main__":
    main()
