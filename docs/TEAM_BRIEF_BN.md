# CloudSentinel: টিম ব্রিফ (৫ নভেম্বর থেকে)

- ⏰ **Deadline:** রবিবার ১৫ নভেম্বর রাত ১১:৫৯ (BST)। Final submit **সন্ধ্যা ৬টার মধ্যে**, draft submit শুক্রবার ১৩ নভেম্বর (Taseen platform-এ তারিখটা মিলিয়ে নেবে)।
- 🧩 **Checkpoint (রাত ৯টা):** CP1 শুক্র ৬ · CP2 রবি ৮ · CP3 মঙ্গল ১০ (feature freeze) · CP4 বৃহস্পতি ১২ (code freeze, `v1.0-rc`)।
- 🔀 **Merge-এর নিয়ম:** শুধু নিজের folder, নিজের branch (`নাম/কাজ`), `main`-এ PR, CI সবুজ হলে squash merge। Taseen রাত ১০টায় merge করে। Alif-এর agent CI সবুজ হলে নিজেই merge করে।
- 📚 **সবকিছুর বিস্তারিত:** `docs/HANDOFF.md` (setup, অবস্থা, ঝুঁকি) · `docs/PLAN.md` (দিনভিত্তিক কাজ, cut list) · `AGENTS.md` (AI tool-এর নিয়ম)।
- 🔗 **Repo:** https://github.com/abdullahalyf/Cloud-Sentinel

---

## Taseen (Antigravity)
- **তোমার কাজ:** `infra/` + CI/CD + integration + submission: Docker/K8s/Helm, public demo URL, secrets, checkpoint merge।
- **কোথায় পড়বে:** `docs/tasks/taseen.md` · `docs/CONTRACTS.md` §2, §9 · `docs/HANDOFF.md` §3–§5 · `docs/PLAN.md`
- **কোথায় কাজ করবে:** `infra/`, `.github/`, `docker-compose.yml`, `docs/`, `README.md`, `AGENTS.md` · branch `taseen/<task>` (যেমন `taseen/t1-secrets-ci`)
- **কোথা থেকে নেবে:** `shared/contracts.py` (`Executor`), `infra/executor/`, C2 API `/v1/health` `/v1/fleet` (mock: `shared/mocks/mock_api.py`)
- **প্রথম ৩টা কাজ:** H1–H5: Gemini key revoke, ruleset + Alif-এর bypass, Anthropic key, Alif-এর laptop, deadline মেলানো · T1: gitleaks + folder-guard CI · T2/T3: `docker compose up` + আসল Docker executor
- **কীভাবে শুরু করবে:** `Read AGENTS.md and docs/tasks/taseen.md. Do task T1 exactly as written there. Only edit .github/ and .gitleaks.toml. At the end run python -m pytest -q and explain what you changed.`
- **শেষ হলে:** `python -m pytest -q` + task-এর "Done when" → `git push -u origin taseen/<task>` → PR → CI সবুজ হলে squash merge।

## Tamjid (Antigravity)
- **তোমার কাজ:** judge-রা প্রথমে যেটা দেখবে: React + Vite দিয়ে production-মানের web dashboard (`dashboard/web/`)। Streamlit শুধু backup।
- **কোথায় পড়বে:** `docs/tasks/tamjid.md` (Hard rules + screenshot review) · `docs/CONTRACTS.md` §2, §6 · `docs/ARCHITECTURE.md` §7a · `docs/DESIGN.md` (D1-এ তুমিই লিখবে)
- **কোথায় কাজ করবে:** `dashboard/` (নতুন app `dashboard/web/`) + শুধু `docs/DESIGN.md` · branch `tamjid/<task>` (যেমন `tamjid/d1-design`)
- **কোথা থেকে নেবে:** mock API `python -m shared.mocks.mock_api` (`shared/mocks/mock_api.py`, :8000)। একই shape আসল brain-এও (`python -m brain --fake`)।
- **প্রথম ৩টা কাজ:** D1: `docs/DESIGN.md` (direction, tokens, component rules) · D2: `dashboard/web` scaffold + typed API client + loading/empty/error state · D3: fleet overview
- **কীভাবে শুরু করবে:** `Read AGENTS.md, docs/tasks/tamjid.md and docs/CONTRACTS.md section 6. Do task D1 exactly as written there. Only create docs/DESIGN.md. No UI code yet.`
- **শেষ হলে:** `cd dashboard/web && npm test` + `python -m pytest -q` + `npm run shots` দিয়ে screenshot review → PR-এ একটা projector screenshot দাও → reviewer Taseen।

## Fojle (Codex)
- **তোমার কাজ:** `telemetry/`: agent-দের সব data যেন নিরাপদে database-এ পৌঁছায়। Supabase, collector, rogue agent, framework adapter।
- **কোথায় পড়বে:** `docs/tasks/fojle.md` (প্রতিটা কাজ ছোট ছোট step-এ ভাগ করা) · `docs/CONTRACTS.md` §4, §5, §10 · `docs/HANDOFF.md` §4 (setup, CrewAI-র আলাদা venv)
- **কোথায় কাজ করবে:** `telemetry/` + `shared/store.py`-র শুধু `SupabaseStore` class · branch `fojle/<task>` (যেমন `fojle/f2-supabase-writes`)
- **কোথা থেকে নেবে:** `telemetry/db/schema.sql`, `shared/contracts.py` (`SpanRow`), `shared/store.py`-র `LocalStore` (এটার মতোই হুবহু কাজ করতে হবে)
- **প্রথম ৩টা কাজ:** F1: setup + Supabase project + `schema.sql` · F2: SupabaseStore-এ write method · F3: SupabaseStore-এ read method + contract test
- **কীভাবে শুরু করবে:** `Read AGENTS.md and docs/HANDOFF.md section 4. Walk me through task F1 in docs/tasks/fojle.md one step at a time: give me one command, wait for my output, then the next.`
- **শেষ হলে:** প্রতিটা step-এর পর `python -m pytest -q` + commit। শেষ step হলে `git push -u origin fojle/<task>` → PR → reviewer Taseen।

## Orin (Codex)
- **তোমার কাজ:** `eval/`: সংখ্যা দিয়ে প্রমাণ (benchmark, with vs without CloudSentinel, QA) আর pitch deck + video script।
- **কোথায় পড়বে:** `docs/tasks/orin.md` (প্রতিটা কাজ ১–২ ঘণ্টার) · `docs/CONTRACTS.md` §8 · `docs/HANDOFF.md` §4 · `docs/DECISION.md` §5
- **কোথায় কাজ করবে:** শুধু `eval/` (`QA.md`, `RESULTS.md`, `pitch/`) · branch `orin/<task>` (যেমন `orin/o2-qa`)
- **কোথা থেকে নেবে:** `eval/harness.py` + `shared/mocks/fake_fleet.py` (fake agent), `eval/roi.py`, `/v1/roi` (`python -m brain --fake` চালিয়ে)
- **প্রথম ৩টা কাজ:** O1: setup + একবার demo দেখা · O2: QA checklist-এ ২০টা case · O3/O4: ROI sentence + `eval/RESULTS.md`। প্রতিটা checkpoint-এ O5।
- **কীভাবে শুরু করবে:** `Read AGENTS.md and docs/HANDOFF.md section 4. Walk me through task O1 in docs/tasks/orin.md one step at a time, then do task O2 exactly as written (only edit eval/QA.md).`
- **শেষ হলে:** `python -m pytest -q` + "Done when" নিজে মিলিয়ে দেখো → `git push -u origin orin/<task>` → PR → reviewer Taseen।

## Alif (Codex in VS Code, autonomous agent)
- **তোমার কাজ:** `brain/` + contract (`shared/`), সবচেয়ে কঠিন কাজগুলো। পুরোটা Codex agent নিজে করে: task বাছাই, test, merge আর Bangla log।
- **কোথায় পড়বে:** `AGENTS.md` → "Alif's agent loop" · `docs/tasks/alif.md` (A0–A15) · `docs/HANDOFF.md` · পুরো `docs/CONTRACTS.md`
- **কোথায় কাজ করবে:** `brain/`, contract-এর জন্য `shared/` · branch `alif/<id>-<slug>` বা `contract/<slug>`
- **কোথা থেকে নেবে:** `shared/contracts.py`, `shared/mocks/fake_fleet.py`, সবার task file-এর "Contract requests" অংশ
- **প্রথম ৩টা কাজ:** A0: Fojle-র ৩টা contract request · A10: `brain/nightly.py` বানানো · A1: labeled incident দিয়ে judge-এর precision/recall
- **কীভাবে শুরু করবে:** `Read AGENTS.md (section "Alif's agent loop"), docs/HANDOFF.md and docs/tasks/alif.md. Run the loop: pick the next task, build it, test it, merge it when CI is green, log it, and continue. Do not wait for my approval.`
- **শেষ হলে:** agent নিজেই `gh pr checks --watch` দেখে সবুজ হলে squash merge করে, `alif.md`-এ টিক দেয়, `docs/SUMMARY_BN.md`-এ ৩ লাইন লেখে। Key বা account লাগলে Taseen-এর file-এ লিখে রাখে।
