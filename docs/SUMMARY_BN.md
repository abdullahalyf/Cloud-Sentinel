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
