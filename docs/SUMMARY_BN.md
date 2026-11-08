# সংক্ষেপে: আমরা কী বানাচ্ছি, কেন জিতব, কে আগে কী করবে

## চূড়ান্ত আইডিয়া
**CloudSentinel = AI agent-দের circuit breaker + control tower।**
প্রতিটা agent OpenTelemetry দিয়ে নিজের কাজের হিসাব (token, prompt, tool call) পাঠায়। আমাদের **brain** তিন ধাপে বিচার করে:
১) hard limit (বাজেট, tokens/min, RAM): সাথে সাথে kill, AI লাগে না
২) **semantic loop detector**: একই কথা ভিন্ন ভাষায় বারবার বললে ধরে ফেলে, কোনো LLM call ছাড়াই
৩) সন্দেহজনক কেসে **Claude judge** সিদ্ধান্ত দেয়: PAUSE / KILL / WARN / IGNORE, সাথে memory ঠিক করার পরামর্শ

তারপর agent-কে **pause** করা হয় (মারা হয় না)। মানুষ dashboard থেকে (বা Claude, MCP দিয়ে) agent-এর **memory ঠিক করে resume** করে, agent probation-এ থেকে আবার সুস্থ হয়।
টাকা নড়ানো tool call (যেমন ৫০,০০০ টাকার refund) মানুষের অনুমতি ছাড়া চলে না: approve / deny / rewrite।
শেষে **ROI panel** দেখায় প্রতিটা হস্তক্ষেপে কত ডলার বাঁচল।

Demo-র গল্প: **"রাত ৩টার ঘটনা"** (ShopBD-র ৪টা agent: beta loop করে → pause → memory ঠিক → সুস্থ; gamma token bomb → সাথে সাথে kill; delta-র বড় refund আটকে যায়; Claude Desktop-কে বললেই "সবচেয়ে খরুচে agent-কে থামাও")।

## কেন জিতব
- **অন্যরা শুধু দেখে, আমরা থামাই এবং সারিয়ে তুলি।** LangSmith, Phoenix, AgentOps.ai সব "black-box recorder"। ছোট OSS breaker-গুলো agent-এর ভেতরে চলে আর শুধু kill করে। Memory edit, tool override আর container pause একসাথে কেউ দেয় না (`docs/research/landscape.md`-এর gap table দেখো)।
- Judging rubric-এর সাথে মেলে: Innovation (heal, not kill + semantic loop), Technical (OTel standard, MCP, test, Docker/K8s), Business (open-core, "নিজের খরচ নিজেই তুলে নেয়"), Impact + Ethics (human-in-the-loop, audit log, prompt-injection প্রতিরোধ, শুধু synthetic data)।
- Submission-এ **MCP disclosure** আর **evaluation** আলাদা করে নম্বর পায়। দুটোই আমাদের মূল feature।
- পুরোটা **offline** চলে, তাই venue-র Wi-Fi চলে গেলেও demo থামবে না।

## প্রত্যেকের প্রথম কাজ (Day 1, বৃহস্পতিবার ৫ নভেম্বর)
| কে | প্রথম কাজ | বিস্তারিত |
|---|---|---|
| **Taseen** | `main` branch protect করা, **ফাঁস হওয়া Gemini key revoke করা**, platform থেকে AgentOps-এর "Winning Signal" আর আসল deadline মিলিয়ে দেখা, `docker compose up -d --build` চালানো | `docs/tasks/taseen.md` |
| **Alif** | `.env`-এ Claude key বসিয়ে `python -m brain --fake -v` চালানো, judge `source=claude` দেখাচ্ছে কিনা দেখা, semantic loop-এর threshold ঠিক করা | `docs/tasks/alif.md` |
| **Tamjid** | `python -m shared.mocks.mock_api` + `streamlit run dashboard/app.py` চালিয়ে dark theme আর বড় agent card বানানো | `docs/tasks/tamjid.md` |
| **Fojle** | setup শেষ করে `python -m brain --fake` চালানো, Supabase project খুলে `telemetry/db/schema.sql` run করা | `docs/tasks/fojle.md` |
| **Orin** | setup শেষ করে demo একবার চালিয়ে দেখা, তারপর `eval/QA.md`-তে ২০টা test case লেখা | `docs/tasks/orin.md` |

নিয়ম: শুধু নিজের folder, নিজের branch (`নাম/কাজ`)। প্রতিদিন ছোট PR, রাত ১০টায় Taseen merge করবে। AI tool-কে প্রথমেই `AGENTS.md` পড়তে বলবে।
Deadline: **১৫ নভেম্বর রাত ১১:৫৯ (BST)**। Draft submit **১৩ নভেম্বর**, final **১৫ নভেম্বর সন্ধ্যা ৬টার মধ্যে**।

## আপডেট: ৪ নভেম্বর রাত (কী বদলাল, Alif-এর পরের কাজ)
১. পুরো কাজ `main`-এ merge হয়েছে (PR #16), কাল সবাই `main` থেকেই শুরু করবে।
২. brain এখন আরও শক্ত: ভুল span, ভুল command, অদ্ভুত LLM উত্তর বা agent-এর লেখা কৌশল কোনোটাতেই engine থামে না, ভুলও সিদ্ধান্ত নেয় না (৭৫টা test পাস)।
৩. প্রতিটা contract-এর জন্য mock আছে (`shared/mocks/README.md`)। mock API এখন আসল API-র মতোই error দেয়, তাই কেউ কারও জন্য আটকে থাকবে না।
৪. Loop এখন ১৩ সেকেন্ডের বদলে **৩ সেকেন্ডে** ধরা পড়ে। কিন্তু আসল Claude judge এখনো চালানো যায়নি, কারণ cloud session-এ key আর cloudcampbd.com কোনোটাই পৌঁছায়নি।
৫. **Alif, পরের কাজ:** `.env`-এ key বসিয়ে `python -m brain.judge_bench --judge claude --runs 3 --write` চালাও, `docs/research/judge-eval.md`-এর checklist মেলাও (legit_burst-এ যেন PAUSE না আসে, p50 < ৩ সেকেন্ড), তারপর `alif/judge-eval` branch-এ commit করো।

## আপডেট: ৪ নভেম্বর রাত (২): merge + যা এখনো আটকে আছে
- LangGraph/CrewAI adapter, live graph feed, per-task ROI আর Phoenix export এখন `main`-এ (PR #18, squash merge)। কাল সবাই `main` থেকে শুরু করবে।
- ⛔ **আটকে আছে ১:** cloudcampbd.com এই cloud session থেকে এখনো খোলে না (DNS/proxy 403)। তাই Winning Signal আর আসল deadline মেলানো যায়নি। **Taseen:** platform থেকে হাতে কপি করে `docs/DECISION.md` §6-এ বসাও, অথবা নতুন session খোলো যেখানে domain-টা allowed।
- ⛔ **আটকে আছে ২:** এই container-এ `ANTHROPIC_API_KEY` নেই, তাই আসল Claude judge চালানো যায়নি। **Taseen:** key-টা cloud environment-এর secret আর GitHub Actions secret (`ANTHROPIC_API_KEY`) হিসেবে বসাও। তারপর Alif-এর agent নিজেই `alif.md`-এর A1 task চালাবে।

## আপডেট: ৪ নভেম্বর রাত (৩): পরের ধাপের প্রস্তুতি
১. সবার task file নতুন করে সাজানো হয়েছে: 🔴 MUST → 🟡 SHOULD → 🟢 STRETCH। প্রতিটা কাজে Codex/Antigravity-র জন্য prompt আর "Done when" আছে।
২. Tamjid এখন React + Vite দিয়ে আসল web dashboard বানাবে। আগে `docs/DESIGN.md` লিখবে, প্রতিদিন screenshot review করবে। Streamlit থাকবে শুধু backup।
৩. Alif-এর কাজ এখন পুরোটাই autonomous Codex agent করবে (`AGENTS.md` → "Alif's agent loop", `docs/tasks/alif.md` A0–A15)। প্রতিটা কাজের পর এখানে ৩ লাইন লিখবে।
৪. প্রতি রাত ১টায় (BST) nightly CI পুরো test, E2E/chaos আর benchmark চালাবে। কিছু ভাঙলে `nightly` label দিয়ে issue খুলবে।
৫. নতুন session বা নতুন মানুষ শুরু করবে `docs/HANDOFF.md` থেকে। group chat-এর জন্য ছোট brief আছে `docs/TEAM_BRIEF_BN.md`-এ।

### 2026-11-04 · A0 Contract-request inbox
- করা হয়েছে: Fojle-র ৩টা contract request main-এ: ৪টা নতুন ROGUE_KINDS, `schema_migrations` table, CloudWatch-এর ২টা setting (সব additive, test সহ)।
- এরপর: A10 Nightly integration check (`brain/nightly.py`)।
- কেউ আটকে আছে?: না। Fojle এখন F6, F9, F10 শুরু করতে পারবে।

### 2026-11-08 · A1 Judge evaluation on labeled incidents
- করা হয়েছে: ৬৪টা labeled incident (৩১টা সমস্যা, ৩৩টা সুস্থ) + scorer `brain/judge_eval.py` + ২৪টা test। Fallback judge: precision 0.929, recall 0.839, F1 0.881; busy-healthy agent-কে ভুল করে থামায় না (০ false positive)।
- এরপর: A2 Judge tuning — slow budget leak ও token bomb এখনো WARN (recall 0.839 < 0.90), আর stable-high-memory-কে ভুল করে PAUSE হয় (memory trend signal নেই)।
- কেউ আটকে আছে?: হ্যাঁ — Taseen, `ANTHROPIC_API_KEY` দরকার (H3)। Claude judge-এর live run (latency/cost/accuracy) ছাড়া A1-এর অর্ধেক অংশ বাকি; `.env`-এ key বসিয়ে `python -m brain.judge_eval --judge claude --runs 3 --write` চালাতে হবে।

### 2026-11-08 · A2 Judge prompt + threshold tuning
- করা হয়েছে: `brain/tuning.py` দিয়ে ৩৪টা combination grid-search করে সেরা threshold `brain/tuning.json`-এ লেখা হয়েছে (loop_score 0.6, kill_confidence 0.6)। ফলাফল: precision 1.000, recall 0.806, F1 0.893, **০টা false positive**। বাকি ৬টা miss (slow money leak, token bomb) `KNOWN_GAPS`-এ চিহ্নিত — test-এ আটকে রাখা হয়েছে যাতে ভুলে না যায়। PR #27 merge হয়েছে।
- এরপর: A3 Auto-heal — judge patch প্রস্তাব করবে, confident হলে নিজে থেকে ঠিক করবে, নইলে human-এর কাছে পাঠাবে।
- কেউ আটকে আছে?: না।

### 2026-11-08 · A3 Auto-heal (judge নিজে patch করে)
- করা হয়েছে: `brain/heal.py` — patch validate (শুধু memory-র key, budget key নয়, instruction-মতো লেখা নয়), confident patch সরাসরি memory-তে লেখা হয় আর agent probation-এ ফিরে যায়, অন্য সব proposal হয়ে human-এর approvals inbox-এ যায়। Re-trip হলে agent kill না করে pause হয় (human-এর জন্য state বাঁচে)। ৩৮টা acceptance test (`brain/tests/test_heal.py`)। Contract PR #28 merge হয়েছে। `tamjid.md` আর `orin.md`-তে note লেখা হয়েছে।
- এরপর: A4 Adaptive per-agent baseline, তারপর A5 Policy-as-code hot reload।
- কেউ আটকে আছে?: না — Tamjid ও Orin এখন heal proposal দেখতে/পরীক্ষা করতে পারে।

### 2026-11-08 · A4 Adaptive per-agent baseline (প্রতি agent-এর নিজস্ব সীমা)
- করা হয়েছে: `brain/baseline.py` — প্রতি agent-এর **সুস্থ** আচরণ থেকে rolling median + MAD শিখে নিজস্ব soft limit বানায় (`median + 4 × 1.4826 × MAD`)। Suspicious/paused/probation agent থেকে কখনো শেখা হয় না, নইলে brain ভুল করে "runaway = normal" শিখে নিত। Hard limit একদম অপরিবর্তিত। Finding-এ এখন লেখা থাকে "3.4× above this agent's normal"। Baseline `agents.baseline` JSON কলামে সেভ হয় (contract PR #30), তাই brain restart করলেও ভুলে যায় না। ১৮টা acceptance test + API test। Harness এখনো সব ✅।
- এরপর: A5 Policy-as-code hot reload, তারপর A6 Prompt-injection detection।
- কেউ আটকে আছে?: না — Tamjid ড্যাশবোর্ডে প্রতি agent-এর "normal" দেখাতে পারে (`AgentView.baseline` এসে গেছে, `baseline` field ইতিমধ্যে আসে — শুধু দেখানো বাকি)।

### 2026-11-08 · A5 Policy-as-code hot reload (নিয়ম বদলালেই চলবে, restart লাগবে না)
- করা হয়েছে: `brain/policy_schema.py` — policy ফাইলের যেকোনো ভুলের জন্য error-এ **exact path** লেখা থাকে ("tools[2].when.op: must be one of gt, gte, lt, lte, eq, ne, contains")। `brain/policy_reload.py` প্রতি tick-এ ফাইলের mtime দেখে; ফাইল বদলালে সেটিকে validate করে। ভালো ফাইল হলে এক ধাপে (atomically) বদলে যায়, `version = sha256[:12]` পায়, আর এক লাইনের diff summary-সহ `POLICY_RELOAD` action লেখা হয়। **ভাঙা ফাইল হলে reject** — শেষ ভালো policy-ই চালু থাকে, আর critical `policy_invalid` alert-এ ভুলগুলো লেখা থাকে। ফাইল delete করলেও reject হয় (নিয়ম সরিয়ে দিলে fleet খোলা থেকে যায়, তাই সেটা human-এর কাজ)। Engine প্রতি tick-এ ফাইল দেখে আর নতুন `on_trip` / `on_hard_limit` চলমান breaker-এ ঢোকায়, তাই বদলানো নিয়ম পরের trip-এই কাজ করে। API: `GET /v1/policy`, `POST /v1/policy/reload`, `POST /v1/policy/validate`; MCP-তে `get_policy` আর `validate_policy` (দুটোই read-only, তাই MCP tool এখন ১৬টা)। Contract PR #32 merge হয়েছে (`b6f7f49`)। ৩৪টা acceptance test।
- এরপর: A6 Prompt-injection detection, তারপর A7 MCP hardening + packaging।
- কেউ আটকে আছে?: না — Tamjid ড্যাশবোর্ডে "policy দেখা / reload / validate" বাটন বসাতে পারে (`GET /v1/policy`), আর Orin harness-এর প্রতিটা scenario নতুন policy-তে যাচাই করতে পারে।
