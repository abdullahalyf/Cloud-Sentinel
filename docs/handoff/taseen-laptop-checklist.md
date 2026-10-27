# Demo laptop checklist — Taseen

ধাপগুলো **ক্রমানুসারে** চালান। প্রতিটার নিচে "সফল হলে" লেখা আছে; না মিললে থামুন, পরের ধাপে যাবেন না।
Windows PowerShell-এর কমান্ড দেওয়া আছে; Mac/Linux-এ যেখানে আলাদা সেখানে মন্তব্য আছে। সব কমান্ড repo-র root ফোল্ডার থেকে।

## 0. আগে থেকে লাগবে
Python 3.11+, Git, Docker Desktop (চালু, whale আইকন স্থির), Claude বা Gemini API key (না থাকলেও demo চলে, brain তখন offline rules দিয়ে চলে)।

## 1. Setup (একবার)
```powershell
git clone https://github.com/abdullahalyf/Cloud-Sentinel.git
cd Cloud-Sentinel
git checkout main               # PR #9, #10 আর "DAY: Alif day 2" merge হওয়ার পরে। আগে হলে: git checkout alif/day2
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Mac/Linux:  cp .env.example .env
```
**সফল হলে:** `pip` শেষে error ছাড়া ফেরে; `.env` ফাইল তৈরি হয়েছে (`dir .env`)। প্রম্পটের শুরুতে `(.venv)`।

## 2. `.env`-এ keys (ফাইল খুলে এই লাইনগুলো ঠিক করুন, `.env` কখনও commit করবেন না)
```ini
# brain কোনটা: claude অথবা gemini (key না থাকলে offline rules)
BRAIN_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...          # BRAIN_PROVIDER=claude হলে
# BRAIN_PROVIDER=gemini হলে এই দুটো:
# GEMINI_API_KEY=...
# GEMINI_MODEL=gemini-2.5-flash

# একই database সবাই দেখবে (sentinel লেখে, dashboard পড়ে). খালি রাখলে ল্যাপটপের local SQLite।
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=...                      # service_role key (Settings → API)

# optional: প্রতিটা KILL/PAUSE Discord/Slack-এ যাবে
WEBHOOK_URL=
```
Supabase হলে: Supabase → SQL Editor-এ `db/schema.sql` পুরোটা paste করে Run করুন (একবার)।
**সফল হলে:** `BRAIN_PROVIDER`-এর সাথে মিল রেখে শুধু সেই provider-এর key বসানো; `.env` git-এ untracked (`git status`-এ দেখা যায় না)।
দ্রষ্টব্য: যেকোনো key যা কখনও chat বা git-এ গেছে তা বাতিল করে নতুন নিন।

## 3. Docker agents চালু
```powershell
docker compose up -d --build
```
**সফল হলে:** শেষে `Container agent-alpha Started`, `agent-beta Started`, `agent-gamma Started`। `docker ps` তিনটা `agent-*` দেখায়, `STATUS Up`।
কে কীভাবে rogue হবে (ডিফল্ট): alpha = `loop`, beta = `token_bomb`, gamma = `memory_leak`। বদলাতে (PowerShell): `$env:BETA_ROGUE_TYPE="paraphrase_loop"; docker compose up -d --force-recreate`।

## 4. Setup পরীক্ষা
```powershell
python scripts/check_setup.py
```
**সফল হলে** (সব ✅, শেষে `All good! 🎉`):
```
✅ Python 3.11+            ✅ package ...            ✅ .env file found
✅ Docker is running       ✅ agent image cloudsentinel-agent built
✅ 3 agent containers running with cloudsentinel.monitor=true
✅ agent-… has a memory limit  (তিনবার)
✅ database: Supabase   (বা local SQLite) + 4টা Supabase table ✅
✅ Claude API works (…)  অথবা  Gemini API works (…)
```
`❌` থাকলে ঠিক নিচের `→` লাইনের নির্দেশ মানুন। `⚠️ no ANTHROPIC_API_KEY` মানে brain offline rules-এ চলবে (demo তবু চলে)।

## 5. Brain eval (প্রমাণ: ৮টা scenario)
```powershell
python scripts/eval_brain.py            # key থাকলে আসল LLM; আর  --offline  দিলে সবসময় offline rules
```
**সফল হলে:** শেষে `score: 8/8` (offline rules-এ ৮/৮; আসল LLM দিয়ে এখনও চালানো হয়নি, তাই সংখ্যা কম হলে ব্যর্থ লাইনটা Alif-কে দেখান)। `legit_busy_burst`, `slow_healthy_agent`, `monitoring_docs_false_alarm` = `keep` (agent বেঁচে থাকে), বাকিগুলো `KILL`।

## 6. Dashboard (আলাদা নতুন terminal, আগে `.venv\Scripts\activate`)
```powershell
streamlit run dashboard/app.py
```
**সফল হলে:** browser-এ `http://localhost:8501`। এখন "No data yet" দেখায়, এটা ঠিক (sentinel এখনও চলেনি)।

## 7. Demo (মূল ধাপ), প্রথম terminal-এ
```powershell
python scripts/demo.py --docker
```
এটা নিজেই sentinel চালায় (তাই `python -m sentinel` আলাদা চালাবেন না, নইলে দুটো sentinel একই command দুইবার চালাবে)। ১০ সেকেন্ডে beta-কে rogue করে, তারপর সময় ছাপে।
**সফল হলে** (প্রায় ২০ সেকেন্ডের মধ্যে, সর্বোচ্চ ৬০s, একটা লাইন):
```
rogue at 10.x s → flagged at 1x.x s → killed at 1x.x s by rules|claude|gemini|fallback
Reset the agents for the next run:  docker compose up -d --force-recreate
```
Dashboard-এ: beta 💀 (killed), alpha ও gamma চলছে, "Agents killed 1", alerts-এ beta-র ঘটনা।
sentinel বন্ধ হলে প্রায় ১৫ সেকেন্ড পর Sentinel 🔴 OFFLINE দেখাবে। এটা প্রত্যাশিত (Tamjid-এর heartbeat কার্ড যুক্ত থাকলে)।

**ল্যাপটপ ছাড়াই আগে রিহার্সাল (Docker লাগে না):** `python scripts/demo.py --all` চালালে চারটা rogue type পরপর মারা পড়ে আর টেবিলে `healthy survived = yes` আসে।

## 8. Demo শেষে reset (পরের বারের জন্য)
```powershell
docker compose up -d --force-recreate     # মারা agent-গুলো আবার জীবিত, সব নতুন
python db/reset.py --yes                  # (ঐচ্ছিক) database-এর পুরোনো demo data মুছে ফেলে; sentinel বন্ধ থাকা অবস্থায়
```
**সফল হলে:** `docker ps`-এ তিনটা `agent-*` আবার `Up (…seconds)`, আর `python scripts/check_setup.py` আবার সব ✅। পুরোটা শেষ করে বন্ধ করতে: `docker compose down`।

## সমস্যা হলে
| লক্ষণ | করণীয় |
|---|---|
| `Cannot reach Docker` | Docker Desktop চালু করুন, ১ মিনিট অপেক্ষা, আবার |
| dashboard-এ কিছু নেই অথচ demo চলছে | dashboard আর sentinel একই database দেখছে? দুই জায়গায় একই `.env` (একই `SUPABASE_URL` / `LOCAL_DB_PATH`) |
| `rehearsal timed out` | agents চালু আছে? `docker ps`; তারপর `docker compose up -d --force-recreate` |
| ইন্টারনেট/API নেই | `BRAIN_PROVIDER` ঠিক রেখে key খালি রাখুন: brain offline rules-এ চলবে, demo একই থাকবে |
