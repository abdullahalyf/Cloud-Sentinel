# Fojle: Telemetry (`telemetry/`)

**Your goal in one line:** make sure every AI agent's activity (tokens, prompts, tool calls)
reaches our database, in the OpenTelemetry standard format, and build the "bad" demo agents.

**You own (only edit these):** `telemetry/` (sdk, collector, simulators, db, tests) and the
`SupabaseStore` class inside `shared/store.py` (only that class!).
**Your branch prefix:** `fojle/…` (example: `fojle/supabase-writes`)
**Your AI tool:** Codex.

**Contracts you produce:** spans in the `spans` table (CONTRACTS §4, §5), the SDK API (§10),
and `SupabaseStore` (§5 Store protocol).
**Contracts you consume:** `shared/contracts.py` (`SpanRow`), `shared/pricing.py`, `shared/config.py`.

---

## How to work (every task)
1. `git checkout main && git pull`
2. `git checkout -b fojle/<task-name>`
3. Paste the task's **prompt** into Codex. Read what it changed.
4. Run `python -m pytest -q`. Everything must pass.
5. Do the **"Done when"** check yourself, by hand.
6. `git add telemetry shared/store.py` → `git commit -m "<what you did>"` → `git push -u origin fojle/<task-name>`
7. On GitHub: **Compare & pull request** → reviewer: Taseen.

If Codex edits a file outside `telemetry/` (or outside `SupabaseStore`), undo it with
`git checkout -- <file>`. Stuck for more than 30 minutes? Message Alif, and include the error text.

---

## Day 1 (Thu 5 Nov): setup + Supabase

**Task 1.1: machine setup.** Follow `docs/TEAM.md` steps 1–2, then run:
```bash
python scripts/check_setup.py
python -m brain --fake
```
In a second terminal: `streamlit run dashboard/app.py`. Your browser opens. After about 20 s, one agent turns yellow (PAUSED).
✅ **Done when:** you see the dashboard with 4 agents and one gets paused.

**Task 1.2: Supabase.**
1. Go to supabase.com → New project (free). Name: `cloudsentinel`. Region: Singapore.
2. Left menu → **SQL Editor** → New query → paste ALL of `telemetry/db/schema.sql` → **Run**.
3. **Project Settings → API**: copy the "Project URL" and the `service_role` key into your `.env`:
   `SUPABASE_URL=...` and `SUPABASE_KEY=...`
4. Send both values to Alif and Taseen **privately on WhatsApp**. Never put them on GitHub.

✅ **Done when:** Supabase → Table Editor shows 9 tables: agents, spans, agent_metrics, alerts,
verdicts, actions, commands, agent_memory, tool_calls.

---

## Day 2 (Fri 6 Nov): SupabaseStore writes

**Task 2.1: implement the write methods of `SupabaseStore`.**
> Prompt for Codex:
> *Read AGENTS.md and docs/CONTRACTS.md section 5. In shared/store.py, edit ONLY the class
> SupabaseStore. Some methods raise NotImplementedError. Implement these write methods using the
> supabase client already stored in self._db, copying the style of the methods that already work:
> upsert_agent (use .upsert(row, on_conflict="agent_id")), insert_spans (insert a list in one call;
> do nothing if the list is empty), insert_verdict, insert_action, insert_alert, insert_metric.
> Every row comes from the dataclass's .to_row() method. Do not change LocalStore, the Store
> protocol, or any other file. Explain each method to me in one simple sentence.*

✅ **Done when:** with your Supabase values in `.env`, `python -m brain --fake` runs for 1 minute
with no red errors, and Supabase → Table Editor → `agent_metrics` keeps getting new rows.

---

## Day 3 (Sat 7 Nov): test the collector

The collector (`telemetry/collector/`) receives OpenTelemetry data and turns it into `SpanRow`s.
Alif wrote it. Your job is to prove it works with tests.

**Task 3.1: collector tests.**
> Prompt for Codex:
> *Read AGENTS.md and telemetry/collector/normalize.py. Write a new test file
> telemetry/tests/test_normalize_more.py with 5 small pytest tests for normalize_otlp_json():
> (1) a chat span gives operation "chat", the right model and token counts;
> (2) an execute_tool span gives tool_name; (3) a span with status code 2 gives status "error";
> (4) agent_id falls back to service.name when cloudsentinel.agent.id is missing;
> (5) cost_usd is greater than 0 for model "claude-haiku-5-5". Build the input dicts by hand in the
> test, using the helper make_span() that already exists in telemetry/tests/test_normalize.py as an
> example. Only create this one file.*

✅ **Done when:** `python -m pytest telemetry -q` shows all tests passing (including your 5 new ones).

**Task 3.2: see real OTel data arrive.**
```bash
python -m telemetry.collector          # terminal 1
CS_AGENT_ID=demo python telemetry/simulators/agent.py   # terminal 2 (sends spans to :4318)
# Windows PowerShell: $env:CS_AGENT_ID="demo"; python telemetry/simulators/agent.py
```
✅ **Done when:** terminal 1 prints lines like `stored 3 spans from demo`.

---

## Day 4 (Sun 8 Nov): SupabaseStore reads + contract tests

**Task 4.1: implement the read methods.**
> Prompt for Codex:
> *Read AGENTS.md and docs/CONTRACTS.md section 5. In shared/store.py, edit ONLY the class
> SupabaseStore. Implement every method that still raises NotImplementedError. The behaviour must
> match the LocalStore method with the same name exactly (same arguments, same return type, same
> ordering). For write_memory, copy the conflict logic from LocalStore.write_memory and raise
> MemoryConflict the same way. Then tell me how to run shared/tests/test_store_contract.py against
> Supabase (it uses the env var CS_TEST_SUPABASE=1).*

✅ **Done when:** `CS_TEST_SUPABASE=1 python -m pytest shared/tests/test_store_contract.py -q` passes.
On Windows PowerShell, first run `$env:CS_TEST_SUPABASE=1`, then `python -m pytest ...`.

---

## Day 5 (Mon 9 Nov): bad tool call agent + 1 real Claude agent

**Task 5.1: `bad_tool_call` rogue type.**
> Prompt for Codex:
> *Read AGENTS.md, docs/CONTRACTS.md section 10 and telemetry/simulators/agent.py. Add a new rogue
> type "bad_tool_call" to agent.py: in rogue mode, every 3 seconds the agent calls
> cs.tool("issue_refund", {"order_id": 4471, "amount": 50000}, fn=fake_refund, value_usd=410.0)
> where fake_refund just returns "refunded". Catch cs.ToolDenied and print "refund blocked".
> Add "bad_tool_call" to ROGUE_TYPES. Edit only agent.py.*

✅ **Done when:** with `python -m brain --fake` running, a dashboard approval card appears for the refund.

**Task 5.2: real Claude agent** (only if Task 5.1 is done).
> Prompt for Codex:
> *Read AGENTS.md and telemetry/simulators/real_agent.py (it has TODOs). Complete the TODOs: every
> 10 seconds, ask Claude (model from env CLAUDE_MODEL, default claude-haiku-5-5, max_tokens 200) to
> write a one-sentence reply to a random fake customer message from the CUSTOMER_MESSAGES list.
> Wrap the call in cs.llm_call(...) and record response.usage.input_tokens and
> response.usage.output_tokens. Do not send temperature. Edit only real_agent.py.*

✅ **Done when:** `python telemetry/simulators/real_agent.py` prints Claude's replies, and the agent
`delta` shows tokens on the dashboard.

---

## Day 6 (Tue 10 Nov): any OTel agent works

**Task 6.1: an "external agent" example.**
> Prompt for Codex:
> *Read AGENTS.md and docs/CONTRACTS.md section 4. Create telemetry/examples/plain_otel_agent.py:
> a script that uses ONLY the official opentelemetry-sdk and opentelemetry-exporter-otlp-proto-http
> packages (NOT our cloudsentinel SDK) to send 20 "chat" spans with the GenAI attributes from
> section 4 to http://localhost:4318/v1/traces, with resource attribute service.name="external".
> Add a comment block at the top explaining this proves any OTel-instrumented agent works with
> CloudSentinel. Only create this file.*

✅ **Done when:** with the collector running, agent `external` appears on the dashboard.

---

## Day 7 (Wed 11 Nov): reset + cleanup
**Task 7.1:** update `telemetry/db/reset.py` so it wipes all 9 tables (it already lists them; check
that it works on Supabase). **Task 7.2:** update `telemetry/db/cleanup.sql` to also delete `spans`
older than 1 day.
✅ **Done when:** `python telemetry/db/reset.py --yes` leaves every table empty in Supabase.

## Day 8 (Thu 12 Nov): bug fixes only
Fix the GitHub issues labelled `telemetry`. No new features.

## Buffer (13–15 Nov)
Write the **Data & AI provenance** text for the submission in `docs/PROVENANCE.md`: we use
synthetic data only, which models we call (Claude Haiku 5.5, optional Gemini), and which open-source
libraries we use (licences from `requirements.txt`).
