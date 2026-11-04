# Tamjid: Dashboard (`dashboard/`)

**Goal:** the judges' first impression. Build a live "control tower" with token flow, an agent
graph that shows loops, and a C2 UI (kill/pause/resume, memory editor, tool approvals) plus a big
"$ saved" number.

**You own:** `dashboard/` only. **Branch prefix:** `tamjid/…`. **Tool:** Antigravity.
**Contracts you consume:** the C2 REST API (CONTRACTS §6) through `dashboard/api_client.py`, and nothing else.
**Contracts you produce:** none. You are a pure client.
**Hard rules:** never import `shared.store`, `docker`, or `brain`. Every read and write goes through `api_client.py`.

## How to develop with no other layer running
```bash
python -m shared.mocks.mock_api        # terminal 1: fake API on :8000 with moving data
streamlit run dashboard/app.py         # terminal 2
```
Then try it against the real system: stop the mock and run `python -m brain --fake` instead.
Nothing in your code should change between the two.

Every task: branch → prompt → `python -m pytest -q` → check it by hand → PR to Taseen.

---

## Day 1 (Thu 5 Nov): design system + agent cards
> Prompt for Antigravity:
> *Read AGENTS.md, docs/CONTRACTS.md section 6 (AgentView) and dashboard/app.py. Only edit files in
> dashboard/. Make a dark "control tower" theme by injecting CSS with
> st.markdown(unsafe_allow_html=True) from a new file dashboard/theme.py (do not create a
> .streamlit/ folder at the repo root). Show one large card per agent from api_client.fleet(): agent id, a colored
> state badge (healthy green, suspicious orange, paused yellow, probation blue, killed grey with a
> skull), $/min, spend vs budget progress bar, loop score as a small bar. Keep the
> @st.fragment(run_every="1s") refresh. Put each component in its own function in
> dashboard/components.py.*

✅ **Done when:** with the mock API running, 4 cards update every second, and states change color.

## Day 2 (Fri 6 Nov): token flow
> Prompt for Antigravity:
> *Only edit dashboard/. Using plotly, add a "Token flow" section: a line chart of usd_per_min per
> agent over the last 5 minutes from api_client.metrics(minutes=5), and a second small chart of
> tokens_per_min. Mark the moments when an action happened (api_client.actions()) with vertical
> lines labelled with the action name (PAUSE/KILL). Use one consistent color per agent across all
> charts (define the palette once in theme.py).*

✅ **Done when:** you can see the moment beta gets paused as a line on the chart.

## Day 3 (Sat 7 Nov): verdict card + activity feed
> Prompt for Antigravity:
> *Only edit dashboard/. Add a highlighted "🧠 Claude verdict" panel showing the newest verdict from
> api_client.verdicts(): agent, action, confidence as %, pattern, reason in large text, and
> suggested_fix if present. Below it, an activity feed merging actions and alerts sorted by time,
> newest first, with icons per action type. Keep it readable from 3 meters away (big fonts).*

✅ **Done when:** a PAUSE verdict shows up in under 2 s after it happens.

## Day 4 (Sun 8 Nov): agent detail drawer + memory editor + buttons
> Prompt for Antigravity:
> *Only edit dashboard/. Clicking "Open" on an agent card opens a detail view (st.dialog or a
> selected-agent section) with: buttons Pause / Resume / Kill / Restart (each calls
> api_client.command(agent_id, COMMAND, reason=...); Kill asks for confirmation first), the last 20
> spans as a table, and a MEMORY EDITOR: show api_client.memory(agent_id) content as editable JSON
> in st.text_area, a "reason" text box, and a Save button that calls api_client.save_memory(...,
> base_version=current_version). Show a clear error if the JSON is invalid or if the API returns 409
> conflict. If the latest verdict has a suggested_fix, show an "Apply suggestion" button that
> pre-fills the editor.*

✅ **Done when:** the demo beat works by hand: pause beta → edit memory → Resume → beta goes blue (probation) → green.

## Day 5 (Mon 9 Nov): tool approvals
> Prompt for Antigravity:
> *Only edit dashboard/. Add a "✋ Approvals" section at the top of the page that appears only when
> api_client.tool_calls(status="pending") is not empty. One card per pending call: agent, tool name,
> args as pretty JSON, value_usd, the policy reason. Buttons: Approve, Deny, and Rewrite (shows an
> editable JSON box for final_args, then calls api_client.decide(call_id, "rewrite", final_args)).
> Make the card orange with a pulsing border so it draws attention.*

✅ **Done when:** the refund approval from the `bad_tool_call` simulator can be approved, denied and rewritten.

## Day 6 (Tue 10 Nov): agent graph + ROI panel
> Prompt for Antigravity:
> *Only edit dashboard/. (1) Agent graph: from api_client.graph(), draw nodes (agents = circles,
> tools = squares, models = diamonds) and edges with width by count, using plotly (network layout
> with a fixed circular layout is fine). Edges with in_cycle=true are red and thicker. (2) ROI panel
> at the top: a huge "$ saved" number from api_client.roi()["saved_usd"], total spend, interventions,
> cost per successful task, and an expander showing roi["formula"] and each saved_by_action
> sentence.*

✅ **Done when:** during the paraphrase loop, the beta → tool edge is red.

## Day 7 (Wed 11 Nov): polish for the stage
Make it look good on the projector: 1920×1080 with no scrolling for the main view, a red flash/toast
on KILL, a yellow one on PAUSE, the header shows "mode" from `/v1/health` (FAKE / DOCKER), and an
empty-state message when the API is down ("Start the brain: python -m brain --fake").
✅ **Done when:** Orin runs the full demo script on your dashboard without asking you anything.

## Day 8 (Thu 12 Nov): bug fixes only (issues labelled `dashboard`)
## Buffer: take the screenshots for the deck (1080p, dark mode) and send them to Orin.

---

## ⚠️ Notes from the lead review (Wed 4 Nov), read before Day 1
1. **The mock API got more realistic** (see `shared/mocks/README.md`):
   - Pause/Kill/Resume buttons now visibly change that agent's state for 20 s.
   - Any `issue_refund` over 5,000 comes back `pending`.
   - Memory keeps every version (the history works).
   - `WS /v1/stream` exists.
   - `POST /v1/mock/reset` brings back the seeded data: the pending refund and beta's bad memory.
2. Client errors from both APIs are now **400 with a plain `detail` string** (the real API used to send
   FastAPI's 422 list). `api_client.ApiError.detail` can go straight to the screen.
3. **Mock state is shared between tests** (module globals). If a dashboard test changes the mock, call
   `from shared.mocks import mock_api; mock_api.seed()` at the start of the test, or it may pass alone and
   fail in the full run.
4. Rewrite in the approvals card **must send `final_args`**. A rewrite without it is now rejected with 400.
