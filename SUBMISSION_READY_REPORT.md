# Submission-ready report: CloudSentinel · Team HECTORS

Branch: `taseen/submission-ready` (based on `taseen/t4-docker-proxy`, which already contains the latest upstream `main`, `c9cbc4b`).
Date: 20 Nov 2026. Deadline: 11:59 PM Bangladesh time.

## 1. What changed

| File | Why |
|---|---|
| `render.yaml` (new) | Render Blueprint: free Docker web service `cloudsentinel-api` running `python -m brain --fake --no-auto-rogue` on `$PORT`, health check `/v1/health`, Gemini judge, $0.50/h judge spend cap, no Supabase |
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
| `docs/research/submission-draft.md` | Team HECTORS; status/date; Jaccard loop detector (not cosine); judge = Claude Haiku 5.5 / Gemini 2.5 Flash + fallback; 17 MCP tools with real names; real judge prompt excerpt; MIT license; live demo/video placeholders; scale number corrected |
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
| Render start command, simulated locally with `PORT=10000` | ✅ healthy on :10000; CORS header returned for the listed origin; `GO_ROGUE beta` → **`PAUSE beta by gemini` (95%)**, Gemini HTTP 200, about 1 s after the loop was flagged |
| Startup imports | No streamlit / pandas / plotly / supabase / docker imported by `python -m brain --fake` |
| `docker build -f infra/docker/app.Dockerfile` | ❌ **not run: Docker Desktop is not running on this machine** |
| `render.yaml`, `keepalive.yml`, `docker-compose.yml` | valid YAML |
| `dashboard/web/vercel.json` | valid JSON |

## 3. What you must click (in this order)

**First: push and merge** (I will do it after you confirm; see the end of this file).

### a. Render (backend)
1. Go to https://dashboard.render.com → **Sign in with GitHub** (the account that owns the fork `irfanulhoquetaseen/Cloud-Sentinel`).
2. **New +** → **Blueprint**.
3. Connect the repo **irfanulhoquetaseen/Cloud-Sentinel**, branch **main**. Render reads `render.yaml` and shows the service `cloudsentinel-api`.
4. When it asks for **GEMINI_API_KEY**, paste the key (`<SET_IN_DASHBOARD>`). Leave the other values as they are.
5. **Apply** / **Deploy Blueprint**. The first Docker build takes about 5–10 minutes.
6. When it says **Live**, copy the service URL at the top of the service page.
   - If it is **exactly** `https://cloudsentinel-api.onrender.com`, you're done.
   - If it is different (e.g. `https://cloudsentinel-api-xxxx.onrender.com`), replace the URL in:
     - `dashboard/web/vercel.json` (the `destination` of the `/v1/:path*` rewrite)
     - `.github/workflows/keepalive.yml` (`API_URL`)
     - optionally `README.md` / submission draft placeholders.
     Then commit and push to the fork's `main` (Vercel redeploys on its own).
7. Check: open `<RENDER_URL>/v1/health`. You should see `"mode":"fake","judge":"gemini"`.
8. Optional: in the service's **Environment**, set `CS_CORS_ORIGINS` to your real Vercel URL (it is a placeholder now; it only matters if you ever use `VITE_API_URL`).

### b. Vercel (frontend)
1. https://vercel.com → project **cloud-sentinel** → **Settings → General → Root Directory** = `dashboard/web` (confirm; Framework Preset = Vite, Build Command `npm run build`, Output `dist`).
2. **Settings → Environment Variables** → add `VITE_DEMO` = `1` (Production + Preview). Optional: `VITE_WS_URL` = `wss://<RENDER_HOST>/v1/stream` for live push.
3. **Deployments** → latest → **⋯ → Redeploy** (env vars need a rebuild).
4. Note your real production domain (Settings → Domains). **`cloud-sentinel.vercel.app` is NOT yours**: it belongs to someone else ("AWS Management Dashboard").

### c. Verify
1. `<VERCEL_URL>/v1/health` → JSON with `"ok":true,"mode":"fake","judge":"gemini"`. (If it takes ~1 min, the backend was waking up.)
2. `<VERCEL_URL>/approvals` → the Approvals page loads (no 404) on refresh.
3. `<VERCEL_URL>/` → sidebar **Run the 3 AM demo** → **Start** → `beta` becomes PAUSED, `gamma` KILLED, delta's refund appears in Approvals. Use **Reset demo** afterwards.
4. GitHub → fork → **Actions** → enable workflows if asked → run **keepalive** once by hand (workflow_dispatch). Scheduled workflows only run from the default branch, so `main` is required.

## 4. Submission readiness

| Item | Status |
|---|---|
| LICENSE (MIT) | ✅ |
| README accurate (models, 17 MCP tools, Jaccard, numbers labelled simulated, links checked) | ✅ |
| Docs consistent (submission draft, pitch deck, demo.py) | ✅ (pitch script still says "Claude confirms"; true when Claude is the judge, but the live demo uses Gemini) |
| Tests passing | ✅ 1183 Python + 116 web |
| Gemini judge actually working | ✅ (was broken by the API-version bug, now fixed and verified live) |
| Live demo working | ⏳ pending your Render + Vercel steps above |
| Demo video | ❌ pending: must be **≤ 3:01** per the portal rule. The script in `pitch-deck-and-script.md` is timed for 4:00, so cut it (for example drop the token-bomb segment 02:30–03:00 and shorten the intro) |
| Placeholders to fill | `<VERCEL_URL>`, `<RENDER_URL>`, `<YOUTUBE_URL>` in README.md and submission-draft.md |

## 5. URLs for the cloudcampbd.com form

- **GitHub repo:** https://github.com/abdullahalyf/Cloud-Sentinel (upstream, after the PR is merged), or the fork https://github.com/irfanulhoquetaseen/Cloud-Sentinel (has this work as soon as I push)
- **Live demo:** `<VERCEL_URL>`, your Vercel production domain
- **API docs:** `<RENDER_URL>/docs` (e.g. https://cloudsentinel-api.onrender.com/docs)

## 6. Risks / not finished

- **Docker image not built locally** (Docker Desktop off). The Dockerfile is unchanged except `.dockerignore`; the exact start command was tested outside Docker. Render's first build is the real test; check its logs.
- **Render free tier:** cold start ~1 min. Keepalive helps, but GitHub may delay or skip scheduled runs. The disk is temporary, so the demo DB resets on restart (that is fine for a demo).
- **Shared demo state:** all judges see the same fleet; one judge can leave agents paused. **Reset demo** fixes it.
- **Gemini key on a public demo:** protected by the $0.50/hour cap (then the fallback judge takes over) and by gray-zone-only calls. Watch usage in Google AI Studio.
- **Polling load:** without a WebSocket the dashboard polls about once a second per open tab through Vercel. That is fine for a handful of judges.
- `npm ci` could not be checked locally because of your running dev server; Vercel runs its own clean install.
- The upstream PR from `taseen/submission-ready` passes the folder guard (taseen/ = any path); CI also runs gitleaks and the full test suite.
