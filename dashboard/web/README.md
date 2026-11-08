# CloudSentinel Web Control Tower (`dashboard/web/`)

Production-grade web operations control room for AI agents, built with React 18, Vite, TypeScript, and TanStack Query. Modeled after AgentOps.ai and Grafana for high-density observability and live projector presentations.

---

## Prerequisites
- Node.js 20+ (see `.nvmrc`)
- npm 10+
- Running C2 API or Mock API on port 8000:
  ```bash
  python -m shared.mocks.mock_api
  ```

---

## Commands

```bash
# Install dependencies
npm install

# Start development server on http://localhost:5173
npm run dev

# Run Vitest unit & component tests
npm test

# Build production bundle
npm run build

# Capture daily review screenshots (10 PNGs at 1440x900 and 1920x1080)
npm run shots

# Run Playwright end-to-end smoke tests against running API
npm run e2e
```

---

## Architecture & Conventions
- **Design Tokens:** Strict CSS variables defined in `src/styles/tokens.css` sourced directly from `docs/DESIGN.md`.
- **Offline Fonts:** Self-hosted Inter and JetBrains Mono via `@fontsource`.
- **Tabular Numbers:** All metrics, IDs, timestamps, and currency values use `tabular-nums` in monospace.
- **Typed API Client:** `src/api/client.ts` strictly maps all endpoints from `docs/CONTRACTS.md` §6 with zero `any` types.
- **Mandatory Panel States:** Every dashboard panel supports loading (geometry skeletons), empty (explanatory notes), and error (API diagnostics with Retry).
