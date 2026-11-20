# Submission-ready report: CloudSentinel · Team HECTORS

Branch: `taseen/submission-ready` (based on `taseen/t4-docker-proxy`, which already contains the latest upstream `main`, `c9cbc4b`).
Date: 20 Nov 2026. Deadline: 11:59 PM Bangladesh time.

## 1. What changed

| File | Why |
|---|---|
| `render.yaml` (new) | Render Blueprint: free Docker web service `cloudsentinel-api` running `python -m brain --fake --no-auto-rogue` (no shell; port 10000 set through `CS_API_PORT`), health check `/v1/health`, Gemini judge, $0.50/h judge spend cap, no Supabase |
| `dashboard/web/vercel.json` (new) | Vercel rewrites: `/v1/*` → Render API, everything else → `index.html` (deep links work on refresh) |
| `.github/workflows/keepalive.yml` (new) | Pings `/v1/health` every 10 min so the free backend does not sleep; never fails |
| `LICENSE` (new) | MIT, © 2026 Team HECTORS |
| `README.md` | Rewritten for judges; every claim checked against the code; all relative links verified |
| `brain/judge.py` | **Bug fix:** the Gemini client now uses API version `v1beta`. google-genai 3.x defaults to `v1`, which rejects the system instruction (HTTP 400), so every Gemini verdict silently became a fallback verdict |
| `brain/tests/test_judge_gemini_client.py` (new) | Test for the fix (no network) |
| `requirements.txt` | `google-genai>=1.0` is now a normal dependency, so local runs no longer drop to the fallback judge |
| `shared/config.py` | New setting `cors_origins` ← `CS_CORS_ORIGINS` (comma-separated); default empty = no change |
| `brain/api.py` | `CORSMiddleware` only when `CS_CORS_ORIGINS` is set (safety net for a direct `VITE_API_URL` setup) |
| `brain/tests/test_api_cors.py` (new) | 4 tests: off by default, listed origin allowed (incl. preflight), other origin refused, env parsing |
| `.env.example` | Documents `CS_CORS_ORIGINS` |
| `.dockerignore` | Excludes `node_modules`, `dashboard/web/dist`, `.demo_logs` from the API image context |
| `dashboard/web/src/api/client.ts` | Optional `VITE_API_URL` base URL (default `''` = same as before) |
| `dashboard/web/src/utils/live.ts` | `VITE_WS_URL` / `VITE_API_URL` for the socket URL; if the socket never opens after 5 tries it stops retrying quietly and the UI keeps polling every 1 s |
| `dashboard/web/src/components/ConnectionBanner.tsx` | On 502/503/504 it says "The demo API is waking up…" instead of a scary error |
| `dashboard/web/src/vite-env.d.ts` | Types for `VITE_API_URL`, `VITE_WS_URL`, `VITE_DEMO` |
| `dashboard/web/src/utils/__tests__/live.test.ts` | 2 new tests (quiet give-up, socket URL order) |
| `docs/research/submission-draft.md` | Team HECTORS; status/date; Jaccard loop detector (not cosine); judge = Claude Haiku 5.5 / Gemini 2.5 Flash + fallback; 17 MCP tools with real names; real judge prompt excerpt; MIT license; live demo and API links; video placeholder; scale number corrected |
| `docs/research/pitch-deck-and-script.md` | 16 → 17 MCP tools; scale number corrected; "Team HECTORS". Script otherwise untouched |
| `scripts/demo.py` | Docstring lists all 9 rogue kinds |

**Scale number correction:** README, submission draft and pitch all said "12.9 ms p95 (1.3% of budget) at 1,000 agents". The measured number in `docs/research/pitch-numbers.md` is **129 ms p95 (12.9%)**. All three now say 129 ms.

**Folder ownership:** this branch edits `brain/` (Alif), `shared/` (contract), `dashboard/web/` (Tamjid) and `scripts/`. AGENTS.md's table says to stop at other people's folders, but `.github/folder_guard.py` allows `taseen/` branches to edit any folder, and you asked for these exact changes. Please tell Alif and Tamjid what changed (the list above).

Not committed: `CONTEXT_FOR_SUBMISSION.md` (working notes; its verbatim copies are now out of date). A local `brain/tuning.json` timestamp change from test runs was stashed (`git stash list`).

## 2. Test and build results

| Check | Result |
|---|---|
| `python -m pytest -q` | **1183 passed, 5 skipped, 35 deselected, 0 failed** (68 s) |
| `npx vitest run` (dashboard/web) | **116 passed** (21 files) |
| `npm run build` (dashboard/web) | ✅ `tsc` + `vite build` pass (only a chunk-size warning) |
| `npm ci` | ⚠️ failed with EPERM: a running Vite/esbuild process on your machine locks `esbuild.exe`. `npm install` succeeded instead; `package-lock.json` is unchanged |
| `python -m eval.harness` | **5/5 scenarios ✅** |
| Local "production" run: `CS_API_PORT=8001 python -m brain --fake` with your real `.env` | `/v1/health` → `{"ok":true,"mode":"fake","judge":"gemini",...,"agents_total":4}`; `/v1/fleet` 200; `/docs` 200; RSS ≈ 80 MB (Render free = 512 MB) |
| Render start command, simulated locally on port 10000 (before the no-shell fix; the env-var form was verified live on Render) | ✅ healthy on :10000; CORS header returned for the listed origin; `GO_ROGUE beta` → **`PAUSE beta by gemini` (95%)**, Gemini HTTP 200, about 1 s after the loop was flagged |
| Startup imports | No streamlit / pandas / plotly / supabase / docker imported by `python -m brain --fake` |
| `docker build -f infra/docker/app.Dockerfile` | ❌ **not run: Docker Desktop is not running on this machine** |
| `render.yaml`, `keepalive.yml`, `docker-compose.yml` | valid YAML |
| `dashboard/web/vercel.json` | valid JSON |

## 3. What you must click (in this order)

**First: push and merge** (I will do it after you confirm; see the end of this file).

### a. Render (backend): ✅ DONE, live at https://cloudsentinel-api-s080.onrender.com
- Deployed as a Blueprint from the fork's `main`; `GEMINI_API_KEY` is set in the Render dashboard (`<SET_IN_DASHBOARD>`, never in git).
- **Gotcha (fixed in `render.yaml`):** Render does **not** run `dockerCommand` through a shell. The first version, `sh -c "CS_API_HOST=0.0.0.0 CS_API_PORT=${PORT:-10000} exec python -m brain --fake --no-auto-rogue"`, failed with exit 127 ("not found"). Now: `dockerCommand: python -m brain --fake --no-auto-rogue`, plus envVars `CS_API_HOST=0.0.0.0` and `CS_API_PORT=10000` (Render's default port). This matches the hand-fixed dashboard settings, so a Blueprint sync will not break the service.
- `CS_CORS_ORIGINS` = https://cloudsentinel-sigma.vercel.app.
- If the service URL ever changes, update `dashboard/web/vercel.json` (rewrite destination) and `.github/workflows/keepalive.yml` (`API_URL`).
- Check: https://cloudsentinel-api-s080.onrender.com/v1/health → `"mode":"fake","judge":"gemini"`.

### b. Vercel (frontend)
1. https://vercel.com → project **cloud-sentinel** → **Settings → General → Root Directory** = `dashboard/web` (confirm; Framework Preset = Vite, Build Command `npm run build`, Output `dist`).
2. **Settings → Environment Variables** → add `VITE_DEMO` = `1` (Production + Preview). Optional: `VITE_WS_URL` = `wss://cloudsentinel-api-s080.onrender.com/v1/stream` for live push.
3. **Deployments** → latest → **⋯ → Redeploy** (env vars need a rebuild).
4. Production domain: **https://cloudsentinel-sigma.vercel.app**. (`cloud-sentinel.vercel.app` belongs to someone else, so don't use it.)

### c. Verify
1. `https://cloudsentinel-sigma.vercel.app/v1/health` → JSON with `"ok":true,"mode":"fake","judge":"gemini"`. (If it takes ~1 min, the backend was waking up.)
2. `https://cloudsentinel-sigma.vercel.app/approvals` → the Approvals page loads (no 404) on refresh.
3. `https://cloudsentinel-sigma.vercel.app/` → sidebar **Run the 3 AM demo** → **Start** → `beta` becomes PAUSED, `gamma` KILLED, delta's refund appears in Approvals. Use **Reset demo** afterwards.
4. GitHub → fork → **Actions** → enable workflows if asked → run **keepalive** once by hand (workflow_dispatch). Scheduled workflows only run from the default branch, so `main` is required.

## 4. Submission readiness

| Item | Status |
|---|---|
| LICENSE (MIT) | ✅ |
| README accurate (models, 17 MCP tools, Jaccard, numbers labelled simulated, links checked) | ✅ |
| Docs consistent (submission draft, pitch deck, demo.py) | ✅ (pitch script still says "Claude confirms"; true when Claude is the judge, but the live demo uses Gemini) |
| Tests passing | ✅ 1183 Python + 116 web |
| Gemini judge actually working | ✅ (was broken by the API-version bug, now fixed and verified live) |
| Live demo working | ✅ backend live on Render; ⏳ Vercel needs the `VITE_DEMO=1` redeploy and a final click-through |
| Demo video | ❌ pending: must be **≤ 3:01** per the portal rule. The script in `pitch-deck-and-script.md` is timed for 4:00, so cut it (for example drop the token-bomb segment 02:30–03:00 and shorten the intro) |
| Placeholders to fill | only `<YOUTUBE_URL>` (README.md and submission-draft.md) |

## 5. URLs for the cloudcampbd.com form

- **GitHub repo:** https://github.com/abdullahalyf/Cloud-Sentinel (upstream, after the PR is merged), or the fork https://github.com/irfanulhoquetaseen/Cloud-Sentinel (has this work as soon as I push)
- **Live demo:** https://cloudsentinel-sigma.vercel.app
- **API docs:** https://cloudsentinel-api-s080.onrender.com/docs

## 6. Risks / not finished

- **Docker image not built locally** (Docker Desktop off). The Dockerfile is unchanged except `.dockerignore`; the exact start command was tested outside Docker. Render's first build is the real test; check its logs.
- **Render free tier:** cold start ~1 min. Keepalive helps, but GitHub may delay or skip scheduled runs. The disk is temporary, so the demo DB resets on restart (that is fine for a demo).
- **Shared demo state:** all judges see the same fleet; one judge can leave agents paused. **Reset demo** fixes it.
- **Gemini key on a public demo:** protected by the $0.50/hour cap (then the fallback judge takes over) and by gray-zone-only calls. Watch usage in Google AI Studio.
- **Polling load:** without a WebSocket the dashboard polls about once a second per open tab through Vercel. That is fine for a handful of judges.
- `npm ci` could not be checked locally because of your running dev server; Vercel runs its own clean install.
- The upstream PR from `taseen/submission-ready` passes the folder guard (taseen/ = any path); CI also runs gitleaks and the full test suite.

## Update (20 Nov, evening): demo hardening

- **Live demo judge = deterministic fallback** (`JUDGE_PROVIDER=fallback` in `render.yaml`) for reliability. Gemini is optional again: set `JUDGE_PROVIDER=gemini`.
- `gemini-2.5-flash` now returns 404 for new users, so the default model is **`gemini-3.8-flash`** everywhere (`shared/config.py`, `.env.example`, `render.yaml`, docs). Update your local `.env` line `GEMINI_MODEL` too.
- **Judge timeout:** `CS_JUDGE_TIMEOUT_SECONDS` (default 8) is used by the Claude and Gemini clients; Gemini makes one attempt with no retry, so an overloaded provider (a 503 after ~45 s) falls back within seconds.
- **Demo budgets:** `policies.yaml` gives $0.50 per agent ($1.00 gamma). That is why `DEFAULT_BUDGET_USD` alone did nothing: it is only used when the policy sets no budget. New `CS_DEMO_BUDGET_USD=100` raises every smaller policy budget (engine and `/v1/budgets`); an explicit `SET_BUDGET` still wins. "Reset demo" only sets a budget when less than $0.30 of headroom is left, so it no longer brings back the small budgets.
- `render.yaml` matches the live service: no-shell `dockerCommand`, `CS_API_HOST`, `CS_API_PORT=10000`, `DEFAULT_BUDGET_USD=100`, `CS_DEMO_BUDGET_USD=100`. **Add `CS_DEMO_BUDGET_USD=100` in the Render dashboard** if the Blueprint does not sync it, then click **Manual Deploy → Deploy latest commit**.
