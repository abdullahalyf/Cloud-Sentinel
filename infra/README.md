# infra/ — runtime, executors, CI (owner: Taseen)

| Path | What |
|---|---|
| `executor/docker_exec.py` | pause / unpause / kill / start containers labelled `cloudsentinel.monitor=true` |
| `executor/k8s_exec.py` | Kubernetes executor (Day 6 stretch, skeleton) |
| `docker/app.Dockerfile` | one image for brain, collector, dashboard |
| `docker/agent.Dockerfile` | simulated agent image (SDK + simulator only) |
| `docker-compose.scale.yml` | 10-agent scale demo — **still v1, update on Day 7** (new image + `cloudsentinel.agent_id` labels) |
| `../docker-compose.yml` | the whole stack |
| `../.github/workflows/ci.yml` | tests + offline smoke test + compose validation |

## Checkpoints (run by Taseen at 21:00 on CP days, screen shared)

**CP1 (Day 2) — offline, real dashboard**
```bash
python telemetry/db/reset.py --yes
python -m brain --fake                 # T1
streamlit run dashboard/app.py         # T2
```
✅ beta → 🟡 PAUSED within ~15 s of going rogue, verdict card shows the reason · ✅ alpha/gamma/delta stay 🟢 ·
✅ memory edit + Resume → 🔵 → 🟢 · ✅ Supabase mode works (`SUPABASE_*` set) for the same steps.

**CP2 (Day 4) — Docker end-to-end**
```bash
docker compose up -d --build
python scripts/demo.py rogue beta paraphrase_loop     # → docker ps shows agent-beta (Paused)
python scripts/demo.py fix beta && python scripts/demo.py resume beta
python scripts/demo.py rogue gamma token_bomb         # → agent-gamma Exited, actor = rules
python scripts/demo.py rogue delta bad_tool_call      # → approval card on the dashboard
python -m brain.mcp_server                            # (Claude Desktop) "pause alpha" → actor mcp
```

**CP3 (Day 6) — full demo script** (`docs/DECISION.md` §5) read aloud by Orin, timed. Every glitch → issue.

**CP4 (Day 8) — release candidate**: fresh clone on a second laptop, README only, `python -m pytest -q`,
full demo ×3 live + ×1 with Wi-Fi off. Tag `v1.0-rc`.
