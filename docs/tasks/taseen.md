# Taseen: Infra + team lead (`infra/`, `.github/`, `docker-compose.yml`)

**Goal:** everything runs with one command, the executor really pauses, kills and resumes
containers, CI keeps `main` green, and the submission goes in on time.

**You own:** `infra/`, `.github/`, `docker-compose.yml`, `docs/` (except CONTRACTS/ARCHITECTURE,
which you co-own with Alif), `README.md`, `AGENTS.md`, `.agents/`. **Branch prefix:** `taseen/…`. **Tool:** Antigravity.
**Contracts you produce:** the `Executor` implementations (CONTRACTS §9), the ports (§2), and compose service names.
**Contracts you consume:** `shared/contracts.py` (`Executor`, `RuntimeInfo`, `ExecResult`) and `shared/config.py`.

## Lead duties (every day)
- Run the 10:00 stand-up, merge green PRs at 22:00, and run the integration checkpoints (PLAN.md).
- For each PR, check: CI is green · only the owner's folder is touched · no `.env` or keys · it is small.
- Keep `docs/PLAN.md` up to date. Move cut-list items when the team is behind.

---

## Day 1 (Thu 5 Nov): protect main + CI + boot
1. GitHub → Settings → Branches → add a rule for `main`: require a PR, require 1 approval, require the
   status check `ci / test`, and include administrators.
2. **Revoke the leaked Gemini key** (aistudio.google.com → API keys), since it is in git history.
   Then make a new one and share it privately.
3. Check the platform: copy the AgentOps **Winning Signal** text into `docs/DECISION.md` §6 and
   confirm the real deadline (hackathon.md §3).
4. Run `docker compose up -d --build` and check `docker compose ps` (all services up).
> Prompt for Antigravity (if CI fails):
> *Read AGENTS.md and .github/workflows/ci.yml. The CI job fails with this error: <paste>. Fix only
> files in .github/ or infra/. Do not change application code.*

✅ **Done when:** CI is green on `main`, and the dashboard at http://localhost:8501 shows the 4 Docker agents.

## Day 2 (Fri 6 Nov): Docker executor, for real
> Prompt for Antigravity:
> *Read AGENTS.md, docs/CONTRACTS.md section 9 and infra/executor/docker_exec.py. Make sure
> DockerExecutor implements every Executor method against real containers: pause → container.pause(),
> resume → container.unpause(), kill → container.kill(), restart → container.start() (works for
> exited containers), list_agents reports status "paused" for paused containers and memory from
> container.stats(stream=False). Never raise for unknown agent ids — return ExecResult(False, msg).
> Add infra/tests/test_docker_exec.py that is skipped automatically when Docker is not available
> (pytest.importorskip + a ping check) and pauses/resumes/kills a tiny "alpine sleep 60" container.
> Only edit infra/.*

✅ **Done when:** `python -m pytest infra -q` passes on your laptop with Docker running.

## Day 3 (Sat 7 Nov): ShopBD agents in compose
Check that `docker-compose.yml` starts **alpha, beta, gamma, delta** (+ collector, brain, dashboard),
that the agents send OTLP to `http://collector:4318`, and that labels carry `cloudsentinel.agent_id`.
Add `mem_limit: 512m` and `restart: "no"` to every agent.
✅ **Done when:** `python scripts/demo.py rogue beta paraphrase_loop` makes beta go rogue, and it gets paused in Docker
(`docker ps` shows `(Paused)`).

## Day 4 (Sun 8 Nov): CP2 end-to-end in Docker
Run the CP2 script (infra/README.md → Checkpoints) and file an issue for every failure.
✅ **Done when:** the whole DECISION.md demo works in Docker mode once.

## Day 5 (Mon 9 Nov): CI builds images + demo scripts
> Prompt for Antigravity:
> *Only edit .github/ and infra/. Add a second CI job "docker" that runs docker compose build (no
> push). Add a gitleaks secret-scan job using gitleaks/gitleaks-action@v2. Add a job "folder-guard"
> that fails if a PR from a branch starting with fojle/ changes files outside telemetry/ or
> shared/store.py (and similarly orin/→eval/, tamjid/→dashboard/, alif/→brain/, taseen/→infra/
> .github/ docs/ docker-compose.yml README.md AGENTS.md .agents/), using git diff --name-only
> origin/main...HEAD.*

✅ **Done when:** a test PR that touches a wrong folder goes red.

## Day 6 (Tue 10 Nov): Kubernetes (stretch, cut if CP3 is red)
> Prompt for Antigravity:
> *Read docs/CONTRACTS.md section 9 and infra/executor/k8s_exec.py (it is a skeleton). Using the
> official kubernetes Python client, implement K8sExecutor: agents are Deployments in namespace
> K8S_NAMESPACE with label cloudsentinel.monitor=true and cloudsentinel.agent_id=<id>; pause/kill
> = scale replicas to 0 (kill also adds label cloudsentinel.state=killed), resume/restart = scale to
> 1, list_agents reads pod status and metrics are 0 if metrics-server is absent. Write
> infra/k8s/kind-config.yaml, infra/k8s/agents.yaml (4 Deployments using image
> cloudsentinel-agent:latest, imagePullPolicy Never), infra/k8s/rbac.yaml (a ServiceAccount allowed
> to get/list/patch deployments and pods), and step-by-step infra/k8s/README.md for kind.
> Only edit infra/.*

✅ **Done when:** `EXECUTOR=k8s python -m brain` pauses beta in kind (`kubectl get deploy` shows 0/0).

## Day 7 (Wed 11 Nov): scale demo + optional AWS
Get the 10-agent scale compose (`infra/docker-compose.scale.yml`) working on the new SDK. Optional: write
`infra/aws/README.md` (ECS Fargate or EC2 + compose) for the "Cloud Innovation" sponsor story.
**Also:** find one NRB reviewer (risk R7) and record their feedback in `docs/NRB.md`.

## Day 8 (Thu 12 Nov): fresh-laptop test
On a laptop that has never run the project, follow README.md exactly and time it. Fix the README.
✅ **Done when:** a fresh setup reaches the dashboard in under 15 minutes.

## Buffer: submission owner
Fill in the 8 sections (hackathon.md §4). Use `docs/PROMPTS.md` (prompt library), `docs/TOOLING.md`,
`docs/PROVENANCE.md`, and the MCP disclosure (CONTRACTS §7). **Submit the draft on Fri 13**, then re-submit
with the video on Sat/Sun. Final submit by **Sun 15, 18:00 BST**.
