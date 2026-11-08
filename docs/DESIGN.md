# CloudSentinel Web Control Tower: Design System (DESIGN.md)

This document defines the visual direction, design tokens, layout hierarchy, component anatomy, data formatting rules, motion constraints, and review criteria for CloudSentinel's web dashboard (`dashboard/web/`). It is the binding design contract for all dashboard implementation tasks.

---

## 1. Visual Direction & Mission Statement

> CloudSentinel is an operations control room for AI agents, built for high-stakes monitoring and instant legibility on a hackathon judge's projector. Modeled after high-precision dark telemetry platforms like AgentOps.ai and Grafana, it combines dense observability with strict visual restraint. Every pixel represents live ground-truth data streaming from the C2 engine and OpenTelemetry spans, rejecting decorative gradients and synthetic AI templates. A single focused cyan accent signals required human intervention, while semantic status colors indicate circuit-breaker states without distraction. The interface prioritizes calm control under incident pressure, enabling operators to observe, decide, act, and prove return on investment within seconds.

### Core Visual Principles
- **AgentOps-Grade Precision:** Dense telemetry layouts structured into clean bento-grid hierarchies with crisp 1px borders, subtle surface elevations, and high-luminance status indicators.
- **Projector-First Legibility:** High-contrast text hierarchy (WCAG AAA on primary text) tested to remain sharp, uncluttered, and readable from 3 meters away at 1920×1080 resolution.
- **Zero Decorative Slop:** No decorative background gradients, no glowing or glassmorphism panels, no cartoonish emojis as icons, no placeholder text, and no synthetic numbers.
- **Semantic Color Discipline:** Color carries operational meaning only. Color is never used as background decoration.

---

## 2. Design Tokens

All CSS variables are declared on `:root` in `dashboard/web/src/styles/tokens.css`. Components must consume only these variables; hardcoded hex codes, raw pixel sizes, or arbitrary font declarations are strictly forbidden.

### 2.1 Surfaces & Canvas Tokens
| CSS Variable | Value | Purpose / Semantics |
|---|---|---|
| `--color-canvas` | `#07090E` | Main application background canvas (deep dark slate) |
| `--color-surface` | `#0E131F` | Default card, panel, and table surface background |
| `--color-surface-elevated` | `#161E2E` | Hovered cards, active rows, dropdowns, and modal dialogs |
| `--color-header-glass` | `rgba(14, 19, 31, 0.88)` | Sticky Top Telemetry Bar background (with `backdrop-filter: blur(12px)`) |

### 2.2 Borders & Hairline Tokens
| CSS Variable | Value | Purpose / Semantics |
|---|---|---|
| `--color-border` | `rgba(255, 255, 255, 0.08)` | Default 1px subtle hairline for panels, cards, and table dividers |
| `--color-border-accent` | `rgba(6, 182, 212, 0.45)` | Active selection, focused control border, highlighted card border |
| `--color-focus-ring` | `#06B6D4` | 2px solid focus outline with 2px offset for keyboard navigation |

### 2.3 Projector-Safe Text Hierarchy (WCAG AAA)
| CSS Variable | Value | Contrast Ratio | Purpose / Semantics |
|---|---|---|---|
| `--color-text-primary` | `#F8FAFC` | 17.5:1 on surface | Primary metric numbers, card titles, table cell primary values |
| `--color-text-secondary` | `#CBD5E1` | 11.8:1 on surface | Descriptive text, table cell secondary values, section headers |
| `--color-text-muted` | `#94A3B8` | 7.2:1 on surface | Metadata labels, units, uppercase table column headers, helper hints |

### 2.4 Semantic Status & Telemetry Tokens
Each state token provides an authoritative text/icon color, a low-opacity background tint, and a defined border.

| State / Meaning | Text & Indicator | Background Tint | Border Hairline | Circuit Breaker Role |
|---|---|---|---|---|
| **Healthy / Normal** | `--color-state-healthy`: `#10B981` | `rgba(16, 185, 129, 0.14)` | `rgba(16, 185, 129, 0.35)` | Agent nominal, budget normal, closed breaker |
| **Suspicious / Warning** | `--color-state-suspicious`: `#F59E0B` | `rgba(245, 158, 11, 0.14)` | `rgba(245, 158, 11, 0.35)` | Semantic loop detected, soft limits breached |
| **Paused** | `--color-state-paused`: `#6366F1` | `rgba(99, 102, 241, 0.14)` | `rgba(99, 102, 241, 0.35)` | Quarantined agent; awaiting memory edit or human decision |
| **Probation** | `--color-state-probation`: `#06B6D4` | `rgba(6, 182, 212, 0.14)` | `rgba(6, 182, 212, 0.35)` | Resumed agent under probationary monitoring window |
| **Killed / Critical** | `--color-state-killed`: `#F43F5E` | `rgba(244, 63, 94, 0.16)` | `rgba(244, 63, 94, 0.40)` | Terminated agent; hard limit breached or human kill |

#### Live Telemetry Accents
- `--color-telemetry-cyan`: `#06B6D4` (Active live trace nodes, live span indicators)
- `--color-telemetry-indigo`: `#6366F1` (Secondary trace channels, graph edges)

### 2.5 The Accent Color Rule
| CSS Variable | Value | Strict Usage Rule |
|---|---|---|
| `--color-accent` | `#06B6D4` | **"Action Needed" Only.** Cyan is reserved exclusively for controls and indicators that require human intervention: approvals waiting in the inbox, interactive primary buttons, live input focus rings, and action badges. It is NEVER used for decorative backgrounds or arbitrary icons. |

### 2.6 Spacing Scale
A strict 7-step spacing scale. Margins, paddings, and gap dimensions must draw only from these tokens:

| Token | Pixels | Rem Equivalent | Primary Application |
|---|---|---|---|
| `--space-1` | `4px` | `0.25rem` | Icon-to-text spacing, status dot margin, tight button padding |
| `--space-2` | `8px` | `0.5rem` | Badge padding, button horizontal padding, compact gap |
| `--space-3` | `12px` | `0.75rem` | Standard input padding, card header gap, list item vertical padding |
| `--space-4` | `16px` | `1.0rem` | Default panel interior padding, card layout gap, table cell padding |
| `--space-6` | `24px` | `1.5rem` | Section spacing, bento grid row gap, large panel padding |
| `--space-8` | `32px` | `2.0rem` | Major dashboard grid divisions, page section separators |
| `--space-12` | `48px` | `3.0rem` | Page bottom clearance, modal header spacing |

### 2.7 Border Radii
| Token | Value | Applied To |
|---|---|---|
| `--radius-sm` | `4px` | Badges, buttons, chips, status pills, table row focus rings |
| `--radius-md` | `8px` | Bento cards, panels, dialog modals, toast notifications |

### 2.8 Typography Scale & Numeric Discipline
Fonts are self-hosted via `@fontsource/inter` and `@fontsource/jetbrains-mono` to ensure 100% offline functionality.

| Token | Size | Line Height | Weight | Font Family | Applied To |
|---|---|---|---|---|---|
| `--type-micro` | `12px` | `16px` | `600` | Inter (Uppercase, `tracking: 0.05em`) | Column headers, status badge text, micro tags |
| `--type-body-sm` | `14px` | `20px` | `400` / `500` | Inter | Table cells, body text, form inputs, secondary descriptions |
| `--type-body` | `16px` | `24px` | `400` / `500` | Inter | Prominent descriptions, card subheadings, list titles |
| `--type-title-sm` | `20px` | `28px` | `600` | Inter | Panel titles, section headers, dialog titles |
| `--type-title-md` | `28px` | `36px` | `700` | JetBrains Mono (`tabular-nums`) | Bento secondary KPI numerals, agent burn rates |
| `--type-title-lg` | `40px` | `48px` | `700` | JetBrains Mono (`tabular-nums`) | Hero KPI figures ($ Saved, Total Fleet Spend) |

#### Numeric Discipline Rule
> **Every number, counter, timestamp, ID, and monetary value MUST use font family JetBrains Mono with `font-variant-numeric: tabular-nums`.** Monospace alignment prevents visual jitter during live 1 Hz polling and preserves vertical column alignment in tables.

---

## 3. Layout & Grid Architecture

### 3.1 Two Target Resolutions
The dashboard layout is designed specifically for two target environments without horizontal scrollbars:
1. **1440×900 (Laptop):** Standard 12-column grid, compact gutters (`16px`), dense table rows.
2. **1920×1080 (Projector):** Expansive 12-column grid, generous gutters (`24px`), large KPI numerals readable from 3 meters away.

```
+--------------------------------------------------------------------------------------------------+
| Top Telemetry Bar (56px) - Mode | Judge | $ Saved | Total Agents | Demo Trigger | Live Clock      |
+-------------------+------------------------------------------------------------------------------+
| Left Nav (240px)  | Main View Canvas (12-Column Responsive Bento Grid)                           |
|                   |                                                                              |
|  [LayoutDashboard]|  +-----------------------+ +-----------------------+ +---------------------+ |
|  Fleet            |  | Bento StatTile (4 col)| | Bento StatTile (4 col)| | Bento Stat (4 col) | |
|                   |  +-----------------------+ +-----------------------+ +---------------------+ |
|  [Cpu]            |                                                                              |
|  Agent Details    |  +-------------------------------------------------------------------------+ |
|                   |  | Main Content Panel / Fleet Grid (12 col)                                | |
|  [ShieldAlert] (2)|  |                                                                         | |
|  Approvals        |  |  [AgentCard: alpha]   [AgentCard: beta]   [AgentCard: delta]            | |
|                   |  |                                                                         | |
|  [Activity]       |  +-------------------------------------------------------------------------+ |
|  Incidents        |                                                                              |
|                   |  +--------------------------------------+ +--------------------------------+ |
|  [DollarSign]     |  | LangGraph Flow / Node Graph (7 col)  | | Event Feed / Transitions (5 col| |
|  Cost & ROI       |  +--------------------------------------+ +--------------------------------+ |
+-------------------+------------------------------------------------------------------------------+
```

### 3.2 Top Telemetry Bar (56px Height, Sticky)
The top bar is permanently visible (`position: sticky; top: 0; z-index: 100`) with glass styling (`background: rgba(14, 19, 31, 0.88); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255, 255, 255, 0.08)`):
- **Logo & Title:** `CloudSentinel` wordmark with version chip `v2`.
- **System Mode Badge:** Sourced from `/v1/health` (`fake` | `docker` | `k8s` | `mock`).
- **Judge & Engine Indicator:** Current judge engine (`claude` | `gemini` | `fallback`) with a live pulse dot.
- **Hero Fleet Metric Chip:** Real-time `$ Saved` from `/v1/roi` in bold green mono.
- **Workers & Fleet Chip:** Live active workers count and total agents from `/v1/health`.
- **Demo Mode Trigger Button:** Visible when mode is `fake` or `mock`, or `VITE_DEMO=1`. Triggers scripted demo sequence.
- **Live UTC Clock:** Monospace `HH:mm:ss UTC` ticking in real time.

### 3.3 Left Navigation Bar (240px Width, Fixed)
Fixed dark sidebar providing clean routing and pending count indicators:
1. **Fleet (`/fleet`):** Overview of all monitored agents, burn rates, and circuit status.
2. **Agent Detail (`/agents/:id`):** Deep inspection, live LangGraph flow, memory editor, and command bar.
3. **Approvals (`/approvals`):** Human-in-the-loop tool gate and heal proposal inbox with an **accent count badge** (`--color-accent`) showing pending requests.
4. **Incidents (`/incidents`):** Incident replay timeline with time scrubber and postmortem summaries.
5. **Cost & ROI (`/cost`):** Burn-down projection charts, per-agent task success economics, and ROI breakdown.

### 3.4 Bento-Grid Metric Hierarchy
Dashboard overview pages arrange high-level stats into asymmetric Bento tiles:
- **Hero Tile (4 columns):** Total Dollar Savings & Intervention Count (`$ Saved` in 40px mono).
- **Burn Rate Tile (2 columns):** Current fleet $/min burn rate with projection arrow.
- **Fleet State Distribution (3 columns):** Breakdown of agents by state (`healthy`, `suspicious`, `paused`, `probation`, `killed`).
- **Tool Interventions Tile (3 columns):** Total tool calls held, denied, and auto-approved.

---

## 4. Component Rules & Mandatory UI States

### 4.1 Component Specifications

#### 1. `Panel`
- **Anatomy:** Header container with title (16px bold sans), optional Lucide icon, right-side action slot, 1px bottom border, and padded interior body (`--space-4`).
- **Styling:** Surface background (`#0E131F`), 1px border (`rgba(255, 255, 255, 0.08)`), radius 8px.
- **When to Use:** Standard structural container for all dashboard panels, data tables, and graphs.

#### 2. `StatTile` (Bento KPI Card)
- **Anatomy:** Label (12px uppercase muted mono), primary metric (28px–40px bold mono tabular-nums), sub-label / delta ratio (12px mono), optional micro-chart or progress indicator.
- **When to Use:** High-level metric highlights on Fleet, Cost, and ROI views.

#### 3. `StateBadge` (Status Pill)
- **Anatomy:** 24px height, 4px radius, padding `2px 8px`, 6px live status dot on the left, 12px uppercase tracked bold monospace text (`letter-spacing: 0.05em`).
- **Coloring:** Exactly matches the semantic token table (Section 2.4) based on `AgentState`.
- **Live Indicator Dot:** Includes a subtle 1.5s pulse animation for active states (`healthy`, `probation`).

#### 4. `AgentCard`
- **Anatomy:** 
  - Header: Agent ID (mono bold), runtime chip, `StateBadge`.
  - Body: Burn rate (`$/min`), spend vs. budget progress bar with numeric labels, loop score progress bar (turning amber/red over `0.6`), tokens/min with A4 adaptive baseline ratio ("3.0× its normal").
  - Footer: Last action summary and timestamp.
- **Keyboard & Focus:** Navigable via Tab key, highlighted with active accent border on focus, pressing `Enter` navigates to `/agents/:id`.

#### 5. `DataTable`
- **Anatomy:** Sticky header with uppercase muted labels (12px mono), alternating rows with 1px bottom borders, tabular monospace numbers, and hover elevation (`#161E2E`).
- **When to Use:** Listing spans, trace events, tool call histories, and memory audit logs.

#### 6. `Button` (Three Semantic Tiers)
- **Primary:** Background `--color-accent` (`#06B6D4`), dark text (`#07090E`), font-weight 600, radius 4px. Used for main affirmative actions (e.g., "Approve", "Save Memory").
- **Secondary:** Transparent background, 1px border (`rgba(255, 255, 255, 0.08)`), text `#F8FAFC`, hover elevated (`#161E2E`). Used for filters, cancel, and secondary actions.
- **Danger:** Background `rgba(244, 63, 94, 0.16)`, border `rgba(244, 63, 94, 0.40)`, text `#F43F5E`. Used exclusively for destructive actions (e.g., "Kill Agent", "Reject Proposal").

#### 7. `ConfirmDialog`
- **Anatomy:** Modal backdrop (`rgba(7, 9, 14, 0.85)` with blur), warning icon, critical red headline, explanation of consequences, mandatory text field for "Reason", "Confirm" danger button, and "Cancel" secondary button.
- **Accessibility:** Focus is trapped inside the dialog upon opening; pressing `Esc` cancels and closes immediately.

#### 8. `JsonEditor`
- **Anatomy:** Dark monospace text area (`#07090E` background), line numbers gutter, live syntax validation, inline error message box on invalid JSON, and a formatted "Prettify" helper.
- **Behavior:** The "Save" button is disabled whenever the editor contains invalid JSON.

#### 9. `Timeline`
- **Anatomy:** Horizontal event bar with timestamped markers representing alerts, verdicts, actions, heals, and memory edits. Includes an interactive scrubber handle and speed controls (1×, 4×).
- **When to Use:** Incident replay on `/incidents` view.

#### 10. `Toast`
- **Anatomy:** Fixed top-right notification (z-index 1000), 8px radius, surface elevated background (`#161E2E`), 1px status border, outcome icon, message, and auto-dismiss after 4 seconds.

---

### 4.2 Mandatory UI States

Every panel and interactive view must explicitly support and be tested for three fundamental states:

```
+--------------------------------------------------------------------------------------------------+
| LOADING STATE (Geometry-Matched Skeletons)                                                       |
| [==================] 20px bar (title)                                                            |
| [==============] [==============] [==============] 3x Bento Skeleton Cards                         |
| [==============================================================================================] |
+--------------------------------------------------------------------------------------------------+

+--------------------------------------------------------------------------------------------------+
| EMPTY STATE (Explanatory Notice)                                                                 |
| [ Lucide Icon: Inbox / Terminal ]                                                                |
| Title: "No Pending Tool Calls"                                                                   |
| Detail: "All agent actions have been resolved. Calls over threshold or matching policy rules    |
|          will appear here for human verification."                                               |
+--------------------------------------------------------------------------------------------------+

+--------------------------------------------------------------------------------------------------+
| ERROR STATE (Diagnostic & Retry)                                                                 |
| [ Lucide Icon: AlertTriangle in Critical Red ]                                                   |
| Headline: "Failed to connect to C2 API (HTTP 500 / Network Error)"                               |
| Endpoint: "GET http://localhost:8000/v1/fleet"                                                   |
| Detail: "ApiError: Connection refused. Ensure python -m shared.mocks.mock_api is running."       |
| [ Button: Retry Connection ]                                                                     |
+--------------------------------------------------------------------------------------------------+
```

1. **Loading State (Skeletons, No Spinners):**
   - High-contrast geometry-matched placeholder skeletons using background `#161E2E` with a subtle 1.5s pulse shimmer.
   - Skeletons must mirror the exact dimensions of the target content: rectangular blocks for StatTiles, line strips for table rows, and avatar blocks for agent badges.
   - Generic full-screen spinner wheels are prohibited.

2. **Empty State (Informative Ground Truth):**
   - Centered high-contrast display with a muted Lucide icon (32px), a clear headline (16px bold), and an explanatory paragraph (14px secondary text).
   - The message must state what data will appear and what command or event triggers it (e.g., *"No agents yet: start one with `python -m brain --fake`"* or *"Nothing waiting for a human: policy rules and tool approvals will appear here"*).

3. **Error State (Actionable Diagnostics):**
   - Prominent error banner displaying a red warning indicator, the target endpoint URL (e.g., `http://localhost:8000/v1/...`), the HTTP status code, and the raw `ApiError.detail` message.
   - Must provide an accessible **Retry** button that re-executes the failed query immediately.

---

## 5. Data Formatting & Telemetry Rules

| Data Type | Value Range | Formatted Output | Example |
|---|---|---|---|
| **Currency** | $\ge \$1.00$ | Standard 2 decimal places | `$12.50`, `$142.10` |
| **Currency** | $< \$1.00$ | Precision 4 decimal places | `$0.0216`, `$0.0005` |
| **Tokens** | $< 1,000$ | Exact integer count | `450 tokens` |
| **Tokens** | $1,000 \dots 999,999$ | One decimal with `k` | `16.1k tokens`, `80.8k tokens` |
| **Tokens** | $\ge 1,000,000$ | Two decimals with `M` | `1.25M tokens` |
| **Burn Rate** | Float | 4 decimal places with `$/min` | `$0.0140/min` |
| **Loop Score** | $0.0 \dots 1.0$ | 2 decimal places with gauge color | `0.85` (Amber/Red over 0.60) |
| **Timestamps (Relative)** | $< 60$ seconds | `"Xs ago"` | `"4s ago"` |
| **Timestamps (Relative)** | $1 \dots 59$ minutes | `"Xm ago"` | `"12m ago"` |
| **Timestamps (Absolute)** | Hover / Detailed | ISO-8601 UTC string | `2026-11-08 17:05:00 UTC` |
| **Missing Values** | Null / Undefined | Em-dash in muted text | `—` (Never `NaN`, `null`, or fake `0`) |

### Adaptive Baseline Ratio (A4 Contract Rule)
When rendering an agent card or metric row:
- If `baseline` is populated (`tokens_per_min`, `usd_per_min`, `calls_per_sec`), show the ratio of the current metric to the learned median:
  `16.1k tokens/min — 3.0× its normal`
- If `baseline` is empty `{}` (the agent is still in its 60-second warmup window), omit the ratio entirely and show the raw metric alone. Never display `0.0×` or missing tokens.

---

## 6. Motion & Micro-Interactions

Motion must be functional, minimal, and imperceptible except during critical state changes.

- **Duration Limit:** All UI transitions must complete in $\le 200$ ms using standard cubic-bezier easing (`cubic-bezier(0, 0, 0.2, 1)`).
- **The Two "Loud" State Change Animations:**
  1. **Kill Flash:** When an agent is killed, its card and status pill flash with a brief 150 ms critical red background pulse (`#F43F5E`) before locking into the dead state.
  2. **Pause Pulse:** When an agent is quarantined/paused, its badge exhibits a soft, rhythmic breathing glow in paused indigo (`#6366F1`) on a 2-second loop.
- **Live Indicator Pulse:** Status dots for live streaming agents pulse gently between opacity 0.6 and 1.0 on a 1.2-second cycle.
- **Strict Prohibitions:** No bouncy layout shifts, no sliding modal sheets, no decorative scrolling marquees, and no parallax scrolling.

---

## 7. Anti-Slop Rules

These 7 hard rules are copied verbatim from `docs/tasks/tamjid.md` and must be adhered to across all dashboard code and design implementations:

1. **No AI slop:**
   - No purple or blue gradients, no glassmorphism, no emoji as icons (use Lucide icons).
   - No lorem ipsum, no placeholder or fake numbers, no default Vite/template look, no stock illustrations.
2. **Every number comes from the API.** If the API doesn't give it, the UI doesn't show it. Ask for it in "Contract requests".
3. **Only the tokens in `dashboard/web/src/styles/tokens.css` (from DESIGN.md):** No raw hex colors, px sizes, or font sizes in components.
4. **Every panel has a loading state (skeleton), an empty state (says what will appear and why), and an error state (shows `ApiError.detail` plus a Retry button).** These states have tests.
5. **Keyboard:** Every control can be reached with Tab, has a visible focus ring, and has an `aria-label`. Destructive actions (Kill) need a confirm dialog that works with the keyboard (Esc cancels).
6. **Two resolutions:** 1440×900 (laptop) and 1920×1080 (projector, read from 3 m away). No horizontal scroll at either.
7. **Data access goes only through `dashboard/web/src/api/client.ts`**, which is plain HTTP to `/v1/...`. Never import Python code.

---

## 8. Daily Screenshot Review Checklist (15 Checkboxes)

Used every morning and before submitting PRs by comparing Playwright captures in `dashboard/web/shots/<date>/` against this specification:

- [ ] **1. Resolution Compliance:** Page renders cleanly at 1440×900 and 1920×1080 with zero horizontal scroll at either resolution.
- [ ] **2. 3-Meter Projector Readability:** All primary KPI numbers, table rows, and status badges are distinctly legible from 3 meters away at 1920×1080.
- [ ] **3. Strict Token Enforcement:** No raw hex color codes or ad-hoc RGB values exist in component styles; all colors reference CSS variables in `tokens.css`.
- [ ] **4. Zero AI Slop:** No decorative purple/blue gradients, no frosted glass cards, no stock illustrations, and no emojis used as icons.
- [ ] **5. Icon Consistency:** Every icon is sourced from `lucide-react` with a consistent 16px or 20px bounding box and 1.5px stroke width.
- [ ] **6. Numeric Discipline:** Every number, ID, timestamp, and monetary value is rendered in JetBrains Mono with `tabular-nums`.
- [ ] **7. Currency Formatting:** Amounts $\ge \$1.00$ have 2 decimal places; amounts $< \$1.00$ have exactly 4 decimal places.
- [ ] **8. Ground-Truth Data Only:** Every displayed figure corresponds directly to a field in `shared/contracts.py` and `docs/CONTRACTS.md` §6; no placeholders or synthetic mockup data.
- [ ] **9. Spacing Grid Alignment:** Every element margin, padding, and gap snaps strictly to the 4/8/12/16/24/32/48 spacing scale.
- [ ] **10. Accent Color Restraint:** The cyan accent color (`#06B6D4`) is visible only on controls requiring human action (approvals inbox, primary triggers, focus rings).
- [ ] **11. Loading State Verified:** Geometry-matched skeleton loaders appear without layout shift while data is fetching.
- [ ] **12. Empty State Verified:** When collections are empty, an explanatory panel indicates what will appear and why without blank space.
- [ ] **13. Error State Verified:** When API requests fail, a diagnostic panel displays the endpoint URL, error status code, `ApiError.detail`, and a Retry button.
- [ ] **14. Keyboard Accessibility:** Every button, input, and card can be focused via Tab, shows a 2px cyan focus ring, and has a valid `aria-label`.
- [ ] **15. Projector Screenshot Attached:** Exactly one 1920×1080 projector screenshot is captured and attached to the task PR description.
