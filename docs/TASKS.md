# TASKS — কে কী করবে

Framework এখনই end-to-end কাজ করে (`python -m sentinel --fake` + dashboard)। তাই প্রত্যেকে আজ থেকেই নিজের অংশ নিয়ে কাজ শুরু করতে পারবে, অন্য কারো জন্য অপেক্ষা করতে হবে না।
প্রতিটা task-এর নিচে **AI prompt** দেওয়া আছে, সেটা Codex / AntiGravity / Puku-তে copy-paste করলেই হবে।
Task-গুলো ক্রম অনুযায়ী সাজানো: আগে **MVP** (demo-তে না থাকলেই নয়), তারপর **Polish** (সময় থাকলে)।

---

## 🧠 Alif — Core engine + Claude brain + Docker  (`sentinel/`, `shared/config.py`)

**MVP**
1. Claude API key `.env`-এ বসাও, তারপর `python scripts/check_setup.py` চালাও।
2. Docker mode পরীক্ষা: `docker compose up -d --build` → `python -m sentinel` → `python scripts/command.py rogue beta` চালিয়ে দেখো beta সত্যিই kill হচ্ছে কিনা।
3. `python scripts/demo.py` দিয়ে offline rehearsal: ১০s-এ beta rogue → flagged → killed timeline যাচাই করো। এটি আলাদা temporary SQLite ও fallback brain ব্যবহার করে; Claude timing আলাদা করে যাচাই করো।
4. Fojle-এর Supabase তৈরি হয়ে গেলে Supabase-এর সাথে পুরো flow একবার চালিয়ে দেখো।

**Polish**
5. Brain history তৈরি আছে; `.env`-এর `BRAIN_ESCALATE_WINDOW_SECONDS=60` দিয়ে fallback escalation window যাচাই করো। `LOOP_REPEAT_THRESHOLD=5` এখন default।
6. **PAUSE/RESUME** তৈরি আছে: quarantine-এ execution ও বিচার বন্ধ; resume-এ monitoring ফেরে। Fake ও Docker mode-এ যাচাই করো; paused অবস্থায় Emergency Kill-ও কাজ করতে হবে।

> যাচাই: `python -m pytest -q` এখন rehearsal test-ও চালায়; প্রতিটি push ও PR-এ GitHub Actions একই suite চালাবে।

---

## 📊 Tamjid — Command Center dashboard  (`dashboard/`)

এখনকার `dashboard/app.py` একটা কাজ-চলা baseline, এটাকেই সুন্দর করে তোলাই তোমার কাজ। কাজ করার সময় অন্য একটা terminal-এ `python -m sentinel --fake` চালিয়ে রাখবে, তাহলে live data দেখতে পাবে।

**MVP**
1. Design: dark theme, আর প্রতিটা agent-এর জন্য বড় রঙিন card (🟢 running / 🟠 warned / 💀 killed)।
2. "💰 Money saved" counter একদম উপরে বড় করে, judge-রা যেন প্রথমেই দেখে।
3. 🛑 Emergency Kill-এ চাপলে একটা confirm dialog আসবে (`st.dialog`)।
4. Claude-এর verdict-এর **reason** আলাদা একটা highlighted box-এ দেখানো ("🧠 Claude: stuck in a loop…")। এটা demo-র সবচেয়ে শক্তিশালী মুহূর্ত।
5. [Pause/Resume button code](handoff/tamjid-pause-buttons.md) বসাও; paused status/card আলাদা দেখাও, running count থেকে বাদ দাও, Simulate rogue disable করো। Dashboard শুধু `CommandRow` পাঠাবে।

**Polish**
6. Kill হওয়ার মুহূর্তে লাল flash বা animation।
7. প্রতিটা agent-এর জন্য memory chart।

> AI prompt (task 1–2): *Read AGENTS.md. Improve dashboard/app.py only. Make a dark, modern Command Center: a big "Money saved" number at the top, one large colored card per agent (running/warned/killed), keep the token flow chart and the kill/rogue buttons. Read data only through get_store(); send actions only by inserting CommandRow. Keep the @st.fragment(run_every="2s") auto-refresh. Run pytest.*

---

## 😈 Fojle — Rogue agent + Database  (`agents/`, `db/`, `shared/store.py`)

তুমি নতুন, তাই আগে `docs/TEAM.md` পুরোটা অনুসরণ করো। `--fake` চালিয়ে dashboard দেখতে পেলেই বুঝবে setup শেষ।

**MVP**
1. **Supabase**: supabase.com-এ free project খোলো → বাঁ দিকের **SQL Editor**-এ গিয়ে `db/schema.sql`-এর পুরো লেখাটা paste করে **Run** করো → **Project Settings → API** থেকে URL আর `service_role` key নিয়ে নিজের `.env`-এ বসাও → `python scripts/check_setup.py`-এ "database: Supabase ✅" দেখাবে। Key দুটো team-কে private-ভাবে পাঠাবে, GitHub-এ কখনো না।
2. `agents/agent.py`-তে ৩ ধরনের rogue বানানো, environment variable `ROGUE_TYPE` দিয়ে বেছে নেওয়া যাবে:
   `loop` (একই prompt বারবার, এখনকারটা), `token_bomb` (একেকটা call-এ বিশাল token), `memory_leak` (RAM দ্রুত বাড়বে)।
3. প্রতিটা ধরন Docker-এ চালিয়ে দেখো sentinel ধরতে পারছে কিনা।

> AI prompt (task 2): *Read AGENTS.md. Edit agents/agent.py only. Add an env var ROGUE_TYPE with three rogue behaviours: "loop" (current behaviour), "token_bomb" (varied prompts but 5,000–15,000 tokens per call), "memory_leak" (normal prompts and speed, but +20 MB RAM per second). Keep using emit() from shared/contracts.py exactly as now. Explain to me like a beginner how to build and run it with docker compose.*

---

## 🎤 Orin — Presentation + QA  (`presentation/`, `docs/QA.md`)

তুমিও নতুন। Coding না জানলেও চলবে, তবে `docs/TEAM.md` অনুসরণ করে অন্তত `--fake` demo-টা নিজের laptop-এ একবার চালিয়ে দেখো।

**MVP**
1. Pitch deck (৮–১০ slide): Problem (rogue AI-র কারণে বিল লাখ টাকা) → Solution → **Live demo** → কীভাবে কাজ করে (README-র diagram) → কেন Claude আর কেন শুধু rule যথেষ্ট নয় → Business model (প্রতি agent হিসেবে মাসিক SaaS ফি) → Market → Team।
2. `docs/QA.md` বানাও: test case-এর একটা table, কলাম হবে *কী করলাম → কী হওয়ার কথা → কী হলো → Pass/Fail*। উদাহরণ: "dashboard-এ alpha-র Kill চাপলাম → ১–২ সেকেন্ডে 💀"।
3. Bug পেলে GitHub-এ **Issues → New issue** খুলবে, সাথে screenshot দেবে।
4. Demo-র script লেখা: কে কোন সময়ে কী বলবে আর কী চাপবে। পুরো demo ৩ মিনিটের মধ্যে। `python scripts/demo.py` দিয়ে offline timing মাপো; default timeout ৬০s।

> AI prompt (task 2): *Read README.md and AGENTS.md of this project. Write docs/QA.md: a table of 20 manual test cases for CloudSentinel (dashboard kill switch, rogue agent detection, normal agents not killed, no API key, no Docker, database empty, killing an already-dead agent, etc.). Columns: ID, Steps, Expected, Actual, Pass/Fail. Use simple English.*

---

## 👑 Taseen — Leader  (review, merge, extra features)

1. `main` branch protect করো (Settings → Branches → "Require a pull request before merging")।
2. প্রতিটা PR-এ দেখবে: `pytest` pass করছে কিনা, কেউ নিজের folder-এর বাইরে বা `shared/contracts.py`-তে হাত দিয়েছে কিনা, `.env` বা key commit হয়ে গেছে কিনা।
3. Extra feature-এর আইডিয়া: kill হলেই Discord/Slack-এ alert, dashboard থেকে প্রতিটা agent-এর budget বদলানো, sentinel-কে নিজেই একটা Docker container বানানো।

---

## 🗓️ পরামর্শ: কাজের ক্রম
| দিন | লক্ষ্য |
|---|---|
| Day 1 | সবার setup শেষ, `--fake` demo চলছে। Fojle Supabase তৈরি করে ফেলেছে। |
| Day 2 | Docker mode + Claude দিয়ে আসল kill হচ্ছে। Dashboard-এর নতুন design-এর প্রথম PR। |
| Day 3 | Rogue type ৩টা, QA checklist পুরোটা চালানো, deck-এর draft। |
| Day 4 | শুধু bug fix + demo rehearsal (অন্তত ৫ বার)। নতুন কোনো feature নয়। |
