# Mocks: build your layer without waiting for anyone

Every contract in `docs/CONTRACTS.md` has a stand-in that runs **offline** (no Docker, no keys, no
internet). If you are blocked by someone else's part, use the mock in this table.

| Contract | What you need | Mock / stand-in | How to run it | Kept honest by |
|---|---|---|---|---|
| §4 OTel spans | spans arriving | `telemetry/simulators/agent.py` → real collector, or `FakeFleet` (writes `SpanRow`s directly) | `python -m telemetry.collector` + `CS_AGENT_ID=demo python telemetry/simulators/agent.py` | `telemetry/tests/test_normalize.py` |
| §5 Store | a database | `LocalStore(":memory:")` (SQLite) | `from shared.store import LocalStore` | `shared/tests/test_store_contract.py` (also runs on Supabase with `CS_TEST_SUPABASE=1`) |
| §6 C2 REST + WS | the brain's API | `shared/mocks/mock_api.py`: moving fake data, same errors, policy-based tool gate, memory versions, `WS /v1/stream` | `python -m shared.mocks.mock_api` → :8000 | `shared/tests/test_api_parity.py` (same shapes **and** same status codes as the real API) |
| §7 MCP | Claude operating the fleet | the real `brain/mcp_server.py` pointed at the mock API | start the mock, then `python -m brain.mcp_server` (`CS_API_URL=http://localhost:8000`) | `brain/tests/test_mcp.py` (all 12 tools, mock + real) |
| §8 ROI | `/v1/roi` numbers | mock `/v1/roi`; `eval.roi.build_report()` is pure, so it can be fed any rows | `GET /v1/roi` on the mock | `eval/tests/test_roi.py` |
| §9 Executor | containers to pause/kill | `shared/mocks/fake_fleet.py: FakeFleet` (also generates spans, has 5 rogue kinds) | `python -m brain --fake` | `brain/tests/test_engine.py` |
| §10 SDK | an API for the tool gate + memory | the mock API (tool gate follows `brain/policies.yaml`) | start the mock, then use `cloudsentinel` with `CS_API_URL=http://localhost:8000` | `telemetry/tests/` |
| §11 Policy | rules | `brain/policies.yaml` (the mock loads the same file) | edit the YAML, restart | `brain/tests/test_policy.py` |
| Judge | a Claude verdict | `fallback_verdict()` (deterministic, no key) | default when `ANTHROPIC_API_KEY` is empty | `brain/tests/test_judge.py`, `brain/tests/test_hardening.py` |

## Mock API notes
- States cycle every 60 s: beta loops, then is paused, then probation, then healthy; gamma is killed at 30 s.
- A command (PAUSE/KILL/RESUME/RESTART) forces that agent's state for 20 s, so buttons visibly work.
- `issue_refund` with `amount > 5000` comes back `pending`, exactly like the real gate. Decide it with
  `POST /v1/tool-calls/{id}/decision`.
- `POST /v1/mock/reset` (mock only, not in the contract) brings back the seeded data: the pending
  50,000 refund and beta's bad memory. In tests call `shared.mocks.mock_api.seed()`.
