# টিমের অবস্থা

এই ফাইলটাই পড়লেই চলবে — কে কতটা করেছে, কে আটকে আছে, আর CI কেমন।

**CI:** সবুজ — সব CI পাস — `ci` passed on the last run

*102টা commit পড়া হয়েছে `main` থেকে।*

## এক নজরে

| কে | হয়েছে | চলছে | পরিকল্পনায় | আটকে | পিছিয়ে |
| --- | --- | --- | --- | --- | --- |
| Alif | 30 | 1 | 8 | 0 | 0 |
| Taseen | 2 | 0 | 13 | 0 | 3 |
| Tamjid | 0 | 4 | 6 | 0 | 0 |
| Fojle | 0 | 2 | 10 | 0 | 2 |
| Orin | 0 | 0 | 11 | 0 | 5 |

## মানুষের দরকার — Taseen (8টা)

এগুলো **কোনো agent করতে পারে না** — key, account, বা GitHub setting লাগে। এগুলো বাকি থাকলে পুরো কাজ আটকে থাকে।

- **`H1`** — (Day 1, first thing): revoke the leaked Gemini key
  - (aistudio.google.com → API keys). It's in git history.
- **`H2`** — (Day 1): branch protection that still lets Alif's agent merge.
  - GitHub → Settings → Rules → Rulesets →
  - New ruleset for `main`:
  - Require a pull request, require 1 approval, require the status checks `test`, `adapters` and `compose`, and block force pushes.
  - Bypass list: add **Alif's GitHub account** with mode **"For pull requests only"**. That lets his agent squash-merge its own green PRs without a human review.
  - Never let anyone push directly.
- **`H3`** — (Day 1): API keys.
  - Create an Anthropic API key with a $10 spend limit.
  - Put it in GitHub → Settings → Secrets and variables → Actions as `ANTHROPIC_API_KEY`, so the nightly job runs the real judge.
  - On a call, put it in Alif's laptop `.env` and in the Claude Code cloud environment's secrets.
  - Never paste it in chat.
- **`H4`** — (Day 1): Alif's laptop runs the agent loop.
  - Install the GitHub CLI and run `gh auth login`. Install Codex in VS Code.
  - Set Codex to **Agent (full access)** mode, so it can run `pip`, `pytest` and `gh`.
  - Open the repo folder and check that `gh pr list` works inside the VS Code terminal.
- **`H5`** — (Day 1): platform check.
  - Open the hackathon dashboard on cloudcampbd.com.
  - Copy the AgentOps **Winning Signal** text into `docs/DECISION.md` §6.
  - Confirm the real deadline. If it differs from PLAN.md, update PLAN.md and tell the group.
  - The cloud session couldn't reach the site.
- **`H6`** — (Day 3): cloud account
  - for the public demo (T9). AWS Lightsail, GCP, Hetzner or DigitalOcean is fine; pick the
  - one with free credit. Add a budget alarm at $20. Buy or borrow a domain, or use the VM's IP with `sslip.io`.
- **`H7`** — (Day 6): NRB reviewer
  - (risk R7). Find one NRB engineer for a 30-minute architecture review and record it honestly in `docs/NRB.md`.
- **`H8`** — (buffer): submit.
  - Fill the 8 submission sections, submit the draft on Fri 13, and submit the final by Sun 15, 18:00 BST.

## Alif

**হয়েছে (30):** `A0`, `A1`, `A2`, `A3`, `A4`, `A5`, `A6`, `A7`, `A8`, `A9`, `A10`, `A11`, `A12`, `A13`, `A14`, `A15`, `B1`, `B2`, `B3`, `B4`, `B5`, `B6`, `B7`, `B8`, `B9`, `B10`, `B11`, `B12`, `C0`, `C1`

**কাজ হয়ে গেছে কিন্তু PR খোলা হয়নি (1)** — শুধু PR খুললেই হবে:

- `C2` — 🔴 The real integration rehearsal

**পরিকল্পনায় (8):** `C3`, `C4`, `C5`, `C6`, `C7`, `C8`, `C9`, `C10`

## Taseen

**পিছিয়ে আছে (3)** — পরিকল্পনায় ছিল, কিন্তু দিন চলে গেছে:

- `T2` — boot everything (Day 1)
- `T4` — lock down the Docker socket (Day 2)
- `T5` — CI/CD + releases (Day 3)

**হয়েছে (2):** `T1`, `T3`

**পরিকল্পনায় (10):** `T6`, `T7`, `T8`, `T9`, `T10`, `T11`, `T12`, `T13`, `T14`, `T15`

## Tamjid

**কাজ হয়ে গেছে কিন্তু PR খোলা হয়নি (4)** — শুধু PR খুললেই হবে:

- `D1` — `docs/DESIGN.md` first
- `D2` — app scaffold + typed API client + panel states
- `D3` — fleet overview
- `D4` — full C2 on the agent page

**পরিকল্পনায় (6):** `D5`, `D6`, `D7`, `D8`, `D9`, `D10`

## Fojle

**পিছিয়ে আছে (2)** — পরিকল্পনায় ছিল, কিন্তু দিন চলে গেছে:

- `F1` — setup + Supabase project (Day 1)
- `F4` — collector tests (Day 3)

**PR খোলা আছে, merge-এর অপেক্ষায় (2):** `F2`, `F3`

**পরিকল্পনায় (8):** `F5`, `F6`, `F7`, `F8`, `F9`, `F10`, `F11`, `F12`

## Orin

**পিছিয়ে আছে (5)** — পরিকল্পনায় ছিল, কিন্তু দিন চলে গেছে:

- `O1` — setup + watch the demo once (Day 1)
- `O2` — QA checklist v1 (Day 1)
- `O3` — ROI sentences (Day 2)
- `O4` — `eval/RESULTS.md`, the results table you fill at every checkpoint (Day 2)
- `O6` — scenarios: healthy, exact loop, token bomb (Day 3)

**পরিকল্পনায় (6):** `O5`, `O7`, `O8`, `O9`, `O10`, `O11`

## এই report-টা কিভাবে তৈরি হয়

তিনটা জায়গা থেকে: **task file** (কোন task কার, কোনটা হয়েছে), **git log** (commit-এর বার্তায় task id থাকলে সেটা হয়ে গেছে), আর **CI** (`gh` দিয়ে)।

**"পিছিয়ে" কী — নিয়মটা বলে দেওয়া আছে, অনুমান নয়:** যে task পরিকল্পনায় থেকে গেছে, শুরু হয়নি, আর তার নিজের দিন (যেমন `Day 2`) চলে গেছে — সেটাই পিছিয়ে। যে task-এর দিন-লেবেল নেই, সেটা কখনো এই নিয়মে পিছিয়ে গোনা হয় না — তুলনার কিছু নেই। যে task-এ `[!]` আছে, সেটা আটকে।

**"কাজ হয়ে গেছে কিন্তু PR খোলা হয়নি"** — commit আছে branch-এ, কিন্তু `main`-এ নেই, আর PR-ও নেই। এটা "শুরুই হয়নি" থেকে আলাদা সমস্যা: কাজটা শেষ, শুধু চাওয়ার দরকার।

**"মানুষের দরকার"** — task file-এর "Human-only items" সেকশন থেকে আসে, `### <ID>` হেডিং না, তাই উপরের task গণনায় ধরা পড়ে না। এগুলো key, account বা GitHub setting লাগে — কোনো agent করতে পারে না।

**CI না পড়া গেলে report ভাঙে না** — সেটা "অজানা" লেখে, কারণ CI-এর খবর না জেনে কিছু বলা ভুল; আর যা জানা যায় তা-ই লেখা হয়।

