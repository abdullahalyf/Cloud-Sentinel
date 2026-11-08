# Tamjid: Dashboard (`dashboard/`)

**Goal:** the judges see this first, so it decides how they see everything else. Build a **production-grade web control tower** that looks
like a real product (Grafana, Datadog, LangSmith), not an AI-generated template. Every pixel shows real data
from the API.

**You own:** `dashboard/` only: the new React app in `dashboard/web/`, plus the Streamlit app (`dashboard/app.py`, fallback).
**Branch prefix:** `tamjid/…`. **Tool:** Antigravity.
**Contracts you consume:** the C2 REST API + WebSocket (CONTRACTS §6), and nothing else. During development that's the
mock API (`python -m shared.mocks.mock_api`), with exactly the same shapes and errors as the real one.
**Contracts you produce:** none. You are a pure client.
**Framework (decided, see `docs/ARCHITECTURE.md` §7):** React 18 + Vite + TypeScript, TanStack Query (polling),
`@xyflow/react` (graphs), Apache ECharts (time series), `lucide-react` (icons), Vitest + Playwright (tests, screenshots).
Streamlit stays as the fallback: keep it running, and only fix it if it breaks.

## Hard rules (for you AND for Antigravity; paste them into every prompt you write yourself)
1. **No AI slop:**
   - no purple or blue gradients, no glassmorphism, no emoji as icons (use lucide icons)
   - no lorem ipsum, no placeholder or fake numbers, no default Vite/template look, no stock illustrations
2. **Every number comes from the API.** If the API doesn't give it, the UI doesn't show it. Ask for it in "Contract requests" below.
3. Only the tokens in `dashboard/web/src/styles/tokens.css` (from DESIGN.md): no raw hex colors, px sizes or font sizes in components.
4. Every panel has a **loading** state (skeleton), an **empty** state (says what will appear and why), and an **error** state
   (shows `ApiError.detail` plus a Retry button). These states have tests.
5. **Keyboard:** every control can be reached with Tab, has a visible focus ring and an `aria-label`. Destructive actions (Kill)
   need a confirm dialog that works with the keyboard (Esc cancels).
6. **Two resolutions:** 1440×900 (laptop) and 1920×1080 (projector, read from 3 m away). No horizontal scroll at either.
7. Data access goes **only** through `dashboard/web/src/api/client.ts`, which is plain HTTP to `/v1/...`. Never import Python code.

## Daily screenshot review (every day, before you start a new task) 📸
1. Start the mock API (`python -m shared.mocks.mock_api`) and the dev server (`cd dashboard/web && npm run dev`).
2. `npm run shots` (task D2 sets it up). Playwright captures every page at 1440×900 and 1920×1080 into
   `dashboard/web/shots/<date>/` (git-ignored).
3. Open them side by side with `docs/DESIGN.md` and go through its "Review checklist" (spacing, type scale, colors only from tokens,
   alignment, empty/loading/error states, no truncated numbers).
4. Fix every inconsistency **before** you move on. Paste one projector screenshot into your PR description.
> Prompt for Antigravity (review helper):
> *Read docs/DESIGN.md (especially the Review checklist) and look at these screenshots: <attach>. List every place
> where the UI breaks a DESIGN.md rule (wrong spacing step, a color not in tokens, inconsistent type size, misaligned
> edges, missing state). For each, give the file and component and the exact fix. Then apply the fixes, only in
> dashboard/web/.*

Every task: branch → prompt → `cd dashboard/web && npm test` + `python -m pytest -q` → screenshot review → PR to Taseen.

---

## 🔴 MUST

### D1 (Day 1): `docs/DESIGN.md` first (no UI code before this is merged)
Taseen owns `docs/`, but this one file is yours. Taseen has agreed.
> Prompt for Antigravity:
> *Read AGENTS.md, docs/CONTRACTS.md section 6 and docs/DECISION.md section 5 (the demo story). Write docs/DESIGN.md
> for CloudSentinel's web dashboard: an operations control room for AI agents, used live on a projector.
> Sections:
> (1) Visual direction in 5 sentences: a dark, dense, calm "mission control" (references: Grafana dashboards, the
> Datadog APM service map, LangSmith trace view, Linear's restraint). One accent color for "action needed".
> State colors carry meaning, not decoration.
> (2) Design tokens as tables:
> - background/surface/elevated/border/text-primary/text-secondary/text-muted
> - state colors for healthy, suspicious, paused, probation and killed (WCAG AA contrast on the surface)
> - an accent color
> - a spacing scale 4/8/12/16/24/32/48
> - radius 4/8
> - a type scale (Inter for UI text, JetBrains Mono for numbers/ids): 12/14/16/20/28/40 with line heights
> - tabular-nums for every number
> (3) Layout: 12-column grid, the top bar (mode, health, $ saved, clock), the left nav (Fleet, Agent, Approvals, Incidents, Cost), and panel anatomy.
> (4) Component rules: Panel, StatTile, StateBadge, AgentCard, DataTable, Button (primary/secondary/danger),
> ConfirmDialog, JsonEditor, Timeline, Toast. For each: the anatomy, the states, and when to use it.
> (5) Data rules: units ($ with 4 decimals under $1, tokens with k/M), relative and absolute times, what to show when a value is missing.
> (6) Motion: only for state changes (≤200 ms). The kill flash and the pause pulse are the only "loud" animations.
> (7) Anti-slop rules: copy the 7 "Hard rules" from docs/tasks/tamjid.md.
> (8) A Review checklist (15 checkboxes) used in the daily screenshot review.
> Simple English. Only create docs/DESIGN.md.*

✅ **Done when:** DESIGN.md is merged, and Taseen and one more teammate read it and can explain the accent rule in one sentence.

### D2 (Day 1–2): app scaffold + typed API client + panel states
> Prompt for Antigravity:
> *Read AGENTS.md, docs/DESIGN.md and docs/CONTRACTS.md section 6. Only edit dashboard/web/ (create it).
> (1) Vite + React 18 + TypeScript app. Package manager npm, Node 20. Add a .nvmrc.
> (2) vite.config.ts proxies /v1 (including the WebSocket) to process.env.CS_API_URL or http://localhost:8000, and adds header
> X-CS-Token from process.env.CS_API_TOKEN when it is set.
> (3) src/styles/tokens.css holds the DESIGN.md tokens as CSS variables. src/styles/base.css holds the reset and fonts (self-hosted
> @fontsource/inter and @fontsource/jetbrains-mono, so the demo works offline).
> (4) src/api/types.ts mirrors every response shape in CONTRACTS §6 (AgentView, Metric, Verdict, Action, Alert,
> Memory, ToolCall, RoiReport, NodeFeed, Graph). src/api/client.ts has one typed function per endpoint and throws
> ApiError {status, detail} on a non-2xx response.
> (5) TanStack Query with refetchInterval 1000 ms for live data.
> (6) The app shell from DESIGN.md: top bar (mode from /v1/health), left nav, and routes /fleet, /agents/:id,
> /approvals, /incidents and /cost (react-router).
> (7) A reusable <Panel title loading error empty onRetry> component.
> (8) Vitest + React Testing Library tests for client.ts (mocked fetch: 200, 400 detail, 409, network error) and for
> Panel's 3 states.
> (9) Playwright: `npm run shots` visits every route at 1440×900 and 1920×1080 and saves PNGs to shots/<date>/
> (git-ignore shots/), and `npm run e2e` runs smoke tests against the running mock API.
> (10) dashboard/web/README.md lists the exact commands. Add dashboard/tests/test_web_build.py, skipped when node
> is missing, that runs `npm ci && npm run build` in dashboard/web.*

✅ **Done when:** `npm run dev` shows the shell against the mock, `npm test` passes, and `npm run shots` makes 10 PNGs.

### D3 (Day 2): fleet overview
> Prompt for Antigravity:
> *Only edit dashboard/web/. Follow docs/DESIGN.md exactly. The /fleet page:
> - A StatTile row from /v1/roi and /v1/fleet: $ saved, total spend, $/min now, agents by state, interventions.
> - One AgentCard per agent from /v1/fleet: id, StateBadge, $/min, spend vs budget bar, loop score bar, tokens/min, and the last action.
> - Clicking a card (or pressing Enter on it) opens /agents/:id.
> - Sort: killed and paused first, then by $/min.
> - A state change animates the badge once (≤200 ms).
> - Loading, empty ("No agents yet: start one with python -m brain --fake") and error states.
> Tests: rendering with mock data, sort order, keyboard navigation between cards.*

✅ **Done when:** with the mock, beta's card turns paused within 1 s of `python scripts/demo.py pause beta`, and the screenshot review is clean.

### D4 (Day 3): full C2 on the agent page
> Prompt for Antigravity:
> *Only edit dashboard/web/. The /agents/:id page, following DESIGN.md:
> (1) Command bar: Pause, Resume, Restart, Kill (danger, ConfirmDialog with a reason field), and Set budget (number
> input). Each calls POST /v1/agents/{id}/commands with requested_by "dashboard" and the reason. Show a Toast with
> the result, and the ApiError detail on failure.
> (2) Memory editor: GET memory → JsonEditor (a textarea with JSON validation, line numbers, and an inline error on invalid
> JSON), a diff view against the saved version, a required "reason" field, and Save → POST memory with base_version.
> A 409 shows "Someone else changed the memory (version N)" with Reload and Overwrite buttons. If the latest verdict for
> this agent has suggested_fix, show "Apply suggestion", which pre-fills the editor (never saves on its own).
> (3) Memory history list (GET memory/history) with who, when and the reason.
> (4) Tool override: a table of this agent's recent tool calls (GET /v1/tool-calls filtered by agent). A pending one
> has Approve / Deny / Rewrite (Rewrite opens a JsonEditor pre-filled with args and sends final_args).
> (5) The latest verdict panel: action, confidence %, pattern, reason, source (claude/fallback).
> (6) Last 20 spans as a DataTable.
> Tests: kill confirm (Esc cancels), 409 conflict flow, invalid JSON blocks Save, rewrite sends final_args.*

✅ **Done when:** the demo beat works by hand on the mock and on `python -m brain --fake`: pause beta → Apply suggestion → Save → Resume → probation → healthy.

### D5 (Day 3–4): approvals inbox
> Prompt for Antigravity:
> *Only edit dashboard/web/. The /approvals page plus a badge with the count in the left nav (polls GET
> /v1/tool-calls?status=pending every second). One card per pending call, oldest first: agent, tool, args (pretty JSON),
> value_usd, policy reason, and the time waiting (with a countdown to the timeout if the API gives one). Actions: Approve, Deny,
> Rewrite (sends final_args). Keyboard: J/K moves between cards, A approves, D denies, R rewrites, and every shortcut is shown in the UI.
> A decided card leaves with a short animation, and an empty inbox says "Nothing waiting for a human". When the API adds
> heal proposals (Alif task A3, kind "heal"), show them in the same inbox with their own card type. Leave a typed
> placeholder and a TODO that points to CONTRACTS §6. Tests for all three decisions and the shortcuts.*

✅ **Done when:** the 50,000 BDT refund from the mock (or from delta in `--fake`) can be approved, denied and rewritten, all from the keyboard.

### D6 (Day 4–5): LangGraph live graph with loop arrows (example prompt P1)
The API has `GET /v1/agents/{id}/nodes` (CONTRACTS §6). The mock serves it for **delta** (healthy refund graph) and **beta**
(a `lookup_order ↔ retry` loop while beta is suspicious or paused).
> Prompt for Antigravity:
> *Read docs/CONTRACTS.md section 6 (/nodes, NodeFeed). Only edit dashboard/web/. On /agents/:id, add a "Graph flow" panel,
> shown only when nodes.items is not empty:
> (a) @xyflow/react graph: one node per distinct node name, laid out left to right in order of first appearance.
> Edges come from edges[], with stroke width by count and a count label. An edge in a cycle (A→B and B→A both present) uses
> the state-suspicious token color and is thicker, with an animated dash while the agent is not paused. Highlight last_node,
> and draw a dashed edge to next_node.
> (b) Under it, a "State transitions" DataTable of the last 15 items, newest first: time, step, node, changed (key: value
> per line, monospace), next, and status (error in the danger color).
> (c) A caption: framework (items[0].framework), and "loop: lookup_order ↔ retry ×N" when a cycle exists.
> Refresh every second without the layout jumping (stable node positions). Tests: cycle detection, ordering, empty state.*

✅ **Done when:**
- With the mock, delta shows `classify → lookup_order → decide → refund` with live counts, and beta's loop edges turn colored and climb.
- With the real system (`python -m brain --fake`, `python -m telemetry.collector`, `python telemetry/examples/langgraph_refund_agent.py --rogue-after 20`), agent `lg-refund` stops climbing the moment it's paused.

### D7 (Day 5): cost burn-down + ROI
> Prompt for Antigravity:
> *Only edit dashboard/web/. The /cost page:
> (1) Burn-down chart (ECharts): for each agent, the budget left over time (budget_usd minus cumulative spend from
> /v1/metrics?minutes=30), with a dashed projection line from the current $/min to the time it hits 0, and a vertical marker for
> every action from /v1/actions (PAUSE/KILL labels). Paused agents flatten, which is the money shot.
> (2) The ROI panel from /v1/roi: big $ saved, total spend, wasted $, cost per successful task, and the formula in an expander.
> (3) A table from roi.tasks_by_agent: agent, tasks, succeeded, failed, success rate, spend, cost per success, wasted, sorted by wasted.
> Show each saved_by_action sentence if it is present.
> Tests: the projection math, sorting, missing data.*

✅ **Done when:** during the beta loop, beta's burn-down line falls fast and goes flat at the PAUSE marker.

### D8 (Day 6): incident replay timeline (time travel)
> Prompt for Antigravity:
> *Only edit dashboard/web/. The /incidents page. An incident = a group of actions, verdicts and alerts for one agent,
> with no gap of more than 60 s (build them client-side from /v1/actions, /v1/verdicts, /v1/alerts, /v1/metrics?minutes=60).
> The left list shows incidents (agent, start time, outcome: paused/killed/healed, $ saved). The right side shows a
> horizontal Timeline with every event as a marker (alert → verdict → action → memory edit → resume → healthy) and a
> scrubber. Dragging the scrubber (or pressing ←/→) shows the agent's state, $/min, loop score, the verdict text and
> the memory version **at that moment**, rebuilt from the data. A "Play" button replays at 4× speed. Tests: grouping
> into incidents, state at time t.*

✅ **Done when:** after the beta demo you can replay it from the first alert to healthy, and the scrubber shows the right state at each point.

### D9 (Day 6): demo-mode button: "Run the 3 AM incident"
> Prompt for Antigravity:
> *Only edit dashboard/web/. Add a "Demo" button in the top bar, visible only when /v1/health says mode is fake or
> mock, or when VITE_DEMO=1. It opens a panel with the scripted "3 AM incident" from docs/DECISION.md section 5 as steps, each
> calling the C2 API exactly like scripts/demo.py does:
> 1. GO_ROGUE beta paraphrase_loop
> 2. wait until beta is paused
> 3. highlight the Apply suggestion step and wait for the human to press it
> 4. GO_ROGUE gamma token_bomb
> 5. GO_ROGUE delta bad_tool_call
> 6. jump to Approvals
> 7. show $ saved
> Plus a "Reset demo" button that does what `python scripts/demo.py reset` does.
> Each step shows its status (waiting/running/done/failed). Never fake a result: wait for the real API state. Tests with mocked
> API responses.*

✅ **Done when:** Orin runs the whole demo from this button on the projector without touching the terminal.

### D10 (Day 7): stage polish
Run the screenshot review at 1920×1080 on the real projector (or a TV).
- Add a kill flash and a pause pulse.
- Make $ saved count up.
- Show a connection-lost banner when the API drops, with auto-retry.
- Add an `npm run build` Dockerfile (nginx, proxy `/v1` to `brain:8000`). Taseen wires it into compose (Taseen's T15).
✅ **Done when:** a teammate who has never seen it can find "pause beta" in under 5 seconds.

## 🟡 SHOULD
- **D11 (Day 7):** accessibility audit. Add `@axe-core/playwright` to `npm run e2e` with zero serious violations, and a full keyboard-only demo run.
- **D12 (Day 7):** live push. Use `WS /v1/stream` for fleet/actions updates, with polling as the fallback when the socket drops.
- **D13 (Day 8):** fleet graph page from `/v1/graph` (agents, tools and models; cycles colored), the same style as D6.
- **D14:** keep Streamlit (`dashboard/app.py`) working against the API. Only fix what breaks. It's the fallback if `npm` fails on the demo laptop.

## 🟢 STRETCH
- **D15:** multi-node view (when Taseen's T11 lands, `RuntimeInfo.runtime` reads `docker@<node>`): group agents by node.
- **D16:** a "share incident" link (`/incidents/:id?t=…`) that opens the replay at a moment.

## Buffer
Take the deck and README screenshots (1920×1080, from `npm run shots`) and send them to Orin.

---

## Notes from the lead review (Wed 4 Nov), read before Day 1
1. **The mock API is realistic** (see `shared/mocks/README.md`):
   - Pause/Kill/Resume change that agent's state for 20 s.
   - Any `issue_refund` over 5,000 comes back `pending`.
   - Memory keeps every version.
   - `WS /v1/stream` exists.
   - `POST /v1/mock/reset` brings back the seeded data.
2. Client errors from both APIs are **400 with a plain `detail` string**. Show `detail` as-is.
3. Mock state is shared between Python tests. If a dashboard Python test changes the mock, call `mock_api.seed()` first.
4. A rewrite **must send `final_args`**. A rewrite without it is rejected with 400.
5. Running the mock and the real brain at the same time doesn't work: both use port 8000.

## Contract requests
(Write here if a panel needs data the API doesn't give. Alif's agent adds it to the API and the mock: task A0.)

---

## A3 note from Alif's agent — heal proposals in the approvals inbox (task A3, DONE)

The API now serves heal proposals. They belong in the **same** `/approvals` inbox as the pending
tool calls, with their own card type.

**Where they come from**
- `GET /v1/heal-proposals?status=pending&agent_id=` → `{"items": [...]}`. Same envelope as the
  tool calls, so one poll loop can fetch both.
- `GET /v1/heal-proposals/{id}` → one proposal.
- `POST /v1/heal-proposals/{id}/decision` body `{"decision": "apply"|"reject", "reason": str,
  "requested_by": "human"}` → the updated proposal.
- The mock seeds **one pending proposal for `beta`**, so the inbox is never empty in mock mode.
  `POST /v1/mock/reset` brings it back.

**One proposal object** (this is what a card renders)
```json
{
  "id": 1,
  "agent_id": "beta",
  "kind": "memory_patch",
  "patch": {"memory": [{"op": "set", "key": "order_4471", "value": "cancelled - skip it and move on"}]},
  "confidence": 0.71,
  "status": "pending",
  "verdict_id": 1,
  "base_version": 1,
  "reason": "The belief 'retry until success' keeps the agent looping on a failing order",
  "decided_by": "",
  "decided_at": "",
  "created_at": "2026-11-08T02:58:28.225694+00:00"
}
```
`patch` is an **object**, not a JSON string — the real API and the mock both decode it.

**The card**
- Title: `heal · <agent_id>` (so it is visually distinct from a tool-call card).
- `kind` is `memory_patch` or `tool_policy`. For `memory_patch` show the ops as
  `key: old → new` (the old value is in the agent's memory: `GET /v1/agents/{id}/memory`).
  For `tool_policy` show `tool → deny|approval`.
- Show `confidence` as a percentage and the `reason` from the judge.
- Two actions: **Apply** and **Reject** — the same two buttons as the tool-call card, so
  `A` / `D` do the same thing on both card types.
- `apply` writes the patch into the agent's memory and the agent goes back to work on probation.
  `reject` changes nothing and the agent stays paused.

**Status values** — `pending`, `applied`, `rejected`, `expired`. A proposal goes `expired` when
the agent's memory moved on since the judge looked at it (`base_version` is stale); the newer
memory wins and a human decides. Show an expired card greyed out, with the reason.

**Errors** — the same as everywhere else: a 400 has a plain `detail` string, show it as-is.
`404` = the proposal id does not exist. `409` = already decided.

The MCP server has the same two tools (`list_heal_proposals`, `decide_heal`), so the demo works
from Claude Desktop too.
