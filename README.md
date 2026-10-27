# 🛡️ CloudSentinel

AI agent-দের জন্য **circuit breaker**। কোনো agent loop-এ আটকে গেলে, টাকা (token) উড়াতে থাকলে বা RAM খেয়ে ফেলতে থাকলে CloudSentinel নিজে থেকেই সেই container kill করে দেয়।

## এটা কীভাবে কাজ করে (৩০ সেকেন্ডে)

```
 ┌───────────── Docker ─────────────┐
 │  agent-alpha  agent-beta  agent-gamma │   ← Fojle: প্রতিটা "AI call" stdout-এ JSON লাইন হিসেবে লেখে
 └──────────────┬───────────────────┘
                │ logs + memory
                ▼
 ┌──────────── SENTINEL (Alif) ────────────┐
 │ collector → numbers (tokens/min, loop)  │
 │ detector  → OK / SUSPICIOUS / CRITICAL   │
 │   CRITICAL   → সাথে সাথে KILL (AI লাগে না)  │
 │   SUSPICIOUS → Claude-কে জিজ্ঞেস করে      │
 │                KILL / WARN / IGNORE      │
 └──────────────┬──────────────────────────┘
                │ metrics, alerts, actions
                ▼
        DATABASE (Supabase / local SQLite)   ← Fojle
                ▲              │
   KILL command │              │ পড়ে
                │              ▼
 ┌──────── DASHBOARD (Tamjid) ────────┐
 │ token flow chart, alerts, 🛑 KILL   │
 └────────────────────────────────────┘
```

দুই স্তরের নিরাপত্তা: **Claude** সন্দেহজনক কেসে বুদ্ধি খাটিয়ে সিদ্ধান্ত নেয়, আর **hard limit** এমন একটা backstop যেটা Claude-এর API down থাকলেও কাজ করে।

## চালানো (Docker বা API key ছাড়াই)

```bash
pip install -r requirements.txt
python scripts/check_setup.py      # সব ঠিক আছে কিনা দেখায়
python -m sentinel --fake          # Terminal 1: ৩টা নকল agent, ২০ সেকেন্ড পর beta rogue হবে
streamlit run dashboard/app.py     # Terminal 2: dashboard → http://localhost:8501
```

আসল Docker দিয়ে চালাতে:
```bash
docker compose up -d --build       # ৩টা agent container
python -m sentinel                 # sentinel
python scripts/command.py rogue beta
docker compose up -d --force-recreate   # demo শেষে আবার সব চালু করতে
```

## Quarantine, rehearsal ও test

`PAUSE` agent-কে quarantine করে: execution থামে, sentinel বিচার করে না। `RESUME`-এ
আবার চলে; Emergency Kill তখনও কাজ করে। Dashboard integration-এর copy-paste code:
[Pause/Resume handoff](docs/handoff/tamjid-pause-buttons.md)। Command পাঠাতে existing
store ব্যবহার করুন (`python -m sentinel --fake --no-auto-rogue` চালু রেখে):

```python
from shared.contracts import CommandRow
from shared.store import get_store
get_store().insert_command(CommandRow("beta", "PAUSE", "dashboard", "Review"))
# যাচাই শেষে:
get_store().insert_command(CommandRow("beta", "RESUME", "dashboard", "Reviewed"))
```

```bash
python scripts/demo.py             # একাই চালান: ১০s-এ beta rogue, flag/kill timeline, তারপর বন্ধ
python -m pytest -q                # demo integration test-সহ সব test; push/PR-এ CI-ও চালায়
```

Rehearsal offline চলে; আলাদা temporary SQLite ব্যবহার করে, বর্তমান ডেটা বদলায় না।
Claude/Supabase বন্ধ রাখে; শেষে নিজের sentinel ও temporary ডেটা পরিষ্কার করে।

`.env.example` থেকে `.env` বানান; key কখনো commit করবেন না। নতুন/বদলানো settings:

| Setting | Default | কাজ |
|---|---|---|
| `LOOP_REPEAT_THRESHOLD` | `5` | একই prompt এতবার হলে brain বিচার করে |
| `BRAIN_ESCALATE_WINDOW_SECONDS` | `60` | এই সময়ের মধ্যে আগের WARN/KILL থাকলে এবং evidence **খারাপ হলে** (repeats +2, tokens/min +25% বা memory +5 point) পরের verdict KILL হয়; `legitimate_burst` কখনো KILL হয় না; evidence একই থাকলে WARN-ই থাকে |
| `SOFT_MEMORY_GROWTH_MB_PER_S` | `10` | memory প্রতি সেকেন্ডে এত MB-এর বেশি বাড়লে (~5s মাপা) leak ধরে brain আগেই বিচার করে |
| `MEMORY_RECHECK_SECONDS` | `3` | দ্রুত বাড়তে থাকা memory এত সেকেন্ড পরে আবার দেখা হয়; তখনও বাড়লে (বা memory soft limit পার করলে) KILL, এককালীন লাফ (model load) হলে শুধু WARN |
| `STORE_MAX_ROW_FAILURES` | `5` | database ঠিক থাকা সত্ত্বেও একটি buffered row এতবার fail করলে ফেলে দেওয়া হয় (Kill switch আটকায় না) |

API key ছাড়া fallback rules ও Supabase settings খালি থাকলে SQLite চলে। `DRY_RUN=true`
হলে KILL/PAUSE/RESUME কার্যকর হয় না; rehearsal নিজে `DRY_RUN=false` রাখে।

## Team
| কে | কী | Folder |
|---|---|---|
| Taseen | Leader: review, merge, extra features | সব |
| Alif | Core engine + Claude brain + Docker | `sentinel/`, `shared/` |
| Tamjid | Dashboard + Kill Switch | `dashboard/` |
| Fojle | Rogue agent + Database | `agents/`, `db/`, `shared/store.py` |
| Orin | Presentation + QA | `presentation/`, `docs/QA.md` |

👉 প্রথমবার? পড়ো **[docs/TEAM.md](docs/TEAM.md)** (setup + Git), তারপর **[docs/TASKS.md](docs/TASKS.md)** থেকে নিজের অংশটা।
👉 AI tool (Codex / AntiGravity / Puku) ব্যবহার করলে তাকে সবার আগে **[AGENTS.md](AGENTS.md)** পড়তে বলবে।
