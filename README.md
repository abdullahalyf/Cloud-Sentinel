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
