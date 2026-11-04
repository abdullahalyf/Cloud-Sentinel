# Branch and merge strategy

## Branches
- `main` is always demo-able and protected: PR required, 1 approval, CI `test` green, no direct pushes.
- Each person works on short-lived branches with **their own prefix**: `alif/…`, `taseen/…`,
  `tamjid/…`, `fojle/…`, `orin/…`. Contract changes use `contract/…`.
  One task per branch, e.g. `fojle/supabase-writes`, `tamjid/memory-editor`.
- Keep branches **under 1 day old**. Open a Draft PR early, and rebase or merge `main` every morning.

## Daily flow
```bash
git checkout main && git pull
git checkout -b <you>/<task>
# work, commit small
python -m pytest -q
git push -u origin <you>/<task>       # open a PR → reviewer: Taseen (CODEOWNERS adds the owner)
```

## Merging (Taseen)
- **Squash merge**, so there is one commit per task on `main`, with the PR title as the message.
- Merge order at checkpoints: `contract/*` → `fojle/*` → `alif/*` → `taseen/*` → `tamjid/*` → `orin/*`
  (producers before consumers).
- Reject a PR if it touches another owner's folder, changes `shared/` without both Alif and Taseen,
  contains secrets, or is red in CI.
- If there's a conflict, the **PR author** fixes it on their branch (`git merge origin/main`), never on `main`.

## Contract changes (`shared/`, CONTRACTS.md, schema.sql)
1. Open an issue "Contract: <change>" and explain why.
2. Alif or Taseen makes the change on `contract/<name>`, updating the dataclass, `schema.sql`, `LocalStore`,
   the mock API, `docs/CONTRACTS.md` and the contract tests **in the same PR**.
3. Both approve, merge first, and announce it in the group. Everyone merges `main` that day.

## Tags
- `cp1` … `cp4` at each integration checkpoint, `v1.0-rc` on Day 8, `v1.0` on the submission commit.

## Emergencies
- If `main` is broken: Taseen reverts the offending squash commit (`git revert <sha>`), and the author fixes it on their branch.
- Never `git push --force` to `main`.
