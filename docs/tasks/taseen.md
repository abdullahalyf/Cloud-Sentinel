# Taseen: infra, integration and shipping (`infra/`, `.github/`, `docker-compose.yml`)

**Goal:** CloudSentinel runs anywhere with one command: laptop, Docker, Kubernetes (kind + Helm), several
nodes, or a public cloud VM with a live demo URL. CI/CD keeps `main` green and cuts releases. You merge
everyone's work at every checkpoint, and you submit on time.

**You own:** `infra/`, `.github/`, `docker-compose.yml`, `docs/` (except CONTRACTS/ARCHITECTURE, which you
co-own with Alif), `README.md`, `AGENTS.md`, `.agents/`, `pytest.ini`. **Branch prefix:** `taseen/…`. **Tool:** Antigravity.
**Contracts you produce:** the `Executor` implementations (CONTRACTS §9), the ports (§2), and compose service names.
**Contracts you consume:** `shared/contracts.py` (`Executor`, `RuntimeInfo`, `ExecResult`), `shared/config.py`,
and the C2 API (§6) for monitoring and load tests.
**Your load:** the heaviest after Alif. Do 🔴 MUST in order, then 🟡 SHOULD, and 🟢 STRETCH only if CP3 is green.

Every task: `git checkout main && git pull` → `git checkout -b taseen/<task>` → paste the prompt into
Antigravity → `python -m pytest -q` → do the "Done when" check → PR → squash-merge once CI is green.

---

## 🧑 Human-only items: only you can do these (Alif's agent can't, and Alif won't)
Alif's work is run by an autonomous Codex agent. Anything that needs an account, a key or a GitHub setting
lands here. Check the section **"Requests from Alif's agent"** at the bottom of this file every morning.
- [ ] **H1 (Day 1, first thing): revoke the leaked Gemini key** (aistudio.google.com → API keys). It's in git history.
- [ ] **H2 (Day 1): branch protection that still lets Alif's agent merge.** GitHub → Settings → Rules → Rulesets →
      New ruleset for `main`:
      - Require a pull request, require 1 approval, require the status checks `test`, `adapters` and `compose`, and block force pushes.
      - Bypass list: add **Alif's GitHub account** with mode **"For pull requests only"**. That lets his agent squash-merge its own green PRs without a human review.
      - Never let anyone push directly.
- [ ] **H3 (Day 1): API keys.**
      - Create an Anthropic API key with a $10 spend limit.
      - Put it in GitHub → Settings → Secrets and variables → Actions as `ANTHROPIC_API_KEY`, so the nightly job runs the real judge.
      - On a call, put it in Alif's laptop `.env` and in the Claude Code cloud environment's secrets.
      - Never paste it in chat.
- [ ] **H4 (Day 1): Alif's laptop runs the agent loop.**
      - Install the GitHub CLI and run `gh auth login`. Install Codex in VS Code.
      - Set Codex to **Agent (full access)** mode, so it can run `pip`, `pytest` and `gh`.
      - Open the repo folder and check that `gh pr list` works inside the VS Code terminal.
- [ ] **H5 (Day 1): platform check.** Open the hackathon dashboard on cloudcampbd.com.
      - Copy the AgentOps **Winning Signal** text into `docs/DECISION.md` §6.
      - Confirm the real deadline. If it differs from PLAN.md, update PLAN.md and tell the group.
      - The cloud session couldn't reach the site.
- [ ] **H6 (Day 3): cloud account** for the public demo (T9). AWS Lightsail, GCP, Hetzner or DigitalOcean is fine; pick the
      one with free credit. Add a budget alarm at $20. Buy or borrow a domain, or use the VM's IP with `sslip.io`.
- [ ] **H7 (Day 6): NRB reviewer** (risk R7). Find one NRB engineer for a 30-minute architecture review and record it honestly in `docs/NRB.md`.
- [ ] **H8 (buffer): submit.** Fill the 8 submission sections, submit the draft on Fri 13, and submit the final by Sun 15, 18:00 BST.

## Lead duties (every day)
- 10:00 stand-up. 22:00: squash-merge green PRs in the order `contract/*` → `fojle/*` → `alif/*` → `taseen/*` → `tamjid/*` → `orin/*`.
- Alif's agent merges its own green PRs (H2). You **read** its PRs after the fact, and revert one (`git revert <sha>`) if it's wrong.
- For each PR, check: CI is green · only the owner's folder is touched · no `.env` or keys · it is small.
- Keep `docs/PLAN.md` up to date. Move cut-list items when the team is behind.

---

## 🔴 MUST

### T1 (Day 1): secrets hygiene in CI
> Prompt for Antigravity:
> *Read AGENTS.md and .github/workflows/ci.yml. Only edit files in .github/. Add a job "secrets" that runs
> gitleaks/gitleaks-action@v2 on every push and pull request (fetch-depth: 0 so it scans history). Add a file
> .gitleaks.toml at the repo root that allowlists only the placeholder values in .env.example. Add a job
> "folder-guard" that runs on pull requests only: it reads the branch name (github.head_ref), runs
> git diff --name-only origin/main...HEAD, and fails if a branch starting with fojle/ changes files outside
> telemetry/ and shared/store.py; orin/ → eval/; tamjid/ → dashboard/; alif/ → brain/, docs/tasks/alif.md,
> docs/SUMMARY_BN.md, docs/research/; contract/ → shared/, docs/CONTRACTS.md, docs/ARCHITECTURE.md,
> telemetry/db/schema.sql, shared/mocks/, .env.example; taseen/ → anything. Any branch may also edit the "Notes" and
> "Contract requests" sections of docs/tasks/*.md, so allow docs/tasks/*.md for every prefix.*

✅ **Done when:**
- The secrets job is green on `main`, and it finds the old Gemini key when run with `--log-opts` on the old commit. That's expected, so note it in the PR.
- A test PR from `orin/test` that edits `brain/` goes red.

### T2 (Day 1): boot everything
Run `docker compose up -d --build` and check `docker compose ps` (all services up).
> Prompt for Antigravity (if something fails):
> *Read AGENTS.md and docker-compose.yml. This service fails: <paste docker compose logs>. Fix only files in
> infra/, docker-compose.yml or .github/. Do not change application code.*

✅ **Done when:** the dashboard at http://localhost:8501 shows the 4 Docker agents.

### T3 (Day 2): Docker executor, for real
> Prompt for Antigravity:
> *Read AGENTS.md, docs/CONTRACTS.md section 9 and infra/executor/docker_exec.py. Make sure DockerExecutor
> implements every Executor method against real containers: pause → container.pause(), resume →
> container.unpause(), kill → container.kill(), restart → container.start() (works for exited containers),
> list_agents reports status "paused" for paused containers and memory from container.stats(stream=False).
> Never raise for unknown agent ids — return ExecResult(False, msg). Extend infra/tests/test_docker_exec.py
> (skipped automatically when Docker is not available) so it pauses/resumes/kills a tiny "alpine sleep 60"
> container. Only edit infra/.*

✅ **Done when:** `python -m pytest infra -q` passes on your laptop with Docker running.

### T4 (Day 2): lock down the Docker socket
> Prompt for Antigravity:
> *Read docker-compose.yml. Only edit docker-compose.yml and infra/. Add a service "docker-proxy" using
> image tecnativa/docker-socket-proxy:0.3.0 with environment CONTAINERS=1, POST=1, INFO=1 and every other
> permission 0, mounting /var/run/docker.sock read-only. Remove the docker.sock mount from "brain" and set
> DOCKER_HOST=tcp://docker-proxy:2375 for brain instead. The docker Python SDK reads DOCKER_HOST
> automatically. Document why in a comment (the brain may only list/pause/unpause/kill/start containers).*

✅ **Done when:** after `docker compose up -d --build`, `python scripts/demo.py rogue beta paraphrase_loop` still pauses beta
(`docker ps` shows `(Paused)`), and `docker compose exec brain env | grep DOCKER_HOST` shows the proxy.

### T5 (Day 3): CI/CD + releases
> Prompt for Antigravity:
> *Only edit .github/. (1) Add a job "docker" to ci.yml that runs docker compose build (no push). (2) Add
> .github/workflows/release.yml: on push of a tag v*, build the images infra/docker/app.Dockerfile and
> infra/docker/agent.Dockerfile with docker/build-push-action@v6, push them to ghcr.io/${{ github.repository }}/app
> and /agent tagged with the git tag and "latest" (permissions: packages: write), then create a GitHub
> Release with softprops/action-gh-release@v2 and generate_release_notes: true. (3) In README.md, add a
> "Releases" line saying how to pull the images.*

✅ **Done when:** pushing tag `v0.1.0-test` creates a GitHub Release, and the two images show under the repo's Packages.
Delete the test release afterwards.

### T6 (Day 4): CP2 end-to-end in Docker
Run the CP2 script (infra/README.md → Checkpoints). File an issue for every failure, labelled with the folder name.
✅ **Done when:** the whole DECISION.md demo works in Docker mode once: beta pause → memory fix → resume → healthy, gamma killed, delta refund held.

### T7 (Day 4–5): Kubernetes executor on kind
> Prompt for Antigravity:
> *Read docs/CONTRACTS.md section 9 and infra/executor/k8s_exec.py (it is a skeleton). Using the official
> kubernetes Python client, implement K8sExecutor: agents are Deployments in namespace settings.k8s_namespace
> with labels cloudsentinel.monitor=true and cloudsentinel.agent_id=<id>; pause/kill = scale replicas to 0
> (kill also sets label cloudsentinel.state=killed), resume/restart = scale to 1, list_agents reads pod status,
> memory is 0 if metrics-server is absent, go_rogue sets env ROGUE_TYPE on the Deployment. Unknown agent →
> ExecResult(False, msg), never raise. Write infra/k8s/kind-config.yaml (1 control plane + 2 workers),
> infra/k8s/agents.yaml (4 Deployments, image cloudsentinel-agent:latest, imagePullPolicy Never),
> infra/k8s/rbac.yaml (a ServiceAccount allowed to get/list/patch deployments and pods in the namespace),
> and a step-by-step infra/k8s/README.md (kind create cluster, kind load docker-image, kubectl apply).
> Add infra/tests/test_k8s_exec.py that tests the executor against a fake AppsV1Api object (no cluster
> needed). Only edit infra/.*

✅ **Done when:** `EXECUTOR=k8s python -m brain` pauses beta in kind (`kubectl get deploy -n cloudsentinel` shows `0/0`), and the tests pass without a cluster.

### T8 (Day 5): Helm chart
> Prompt for Antigravity:
> *Only edit infra/. Create a Helm chart in infra/helm/cloudsentinel/ that deploys collector, brain (API +
> engine, EXECUTOR=k8s, using the ServiceAccount from infra/k8s/rbac.yaml as a template), the Streamlit
> dashboard, and N demo agents (values.agents: list of {id, rogueType, budgetUsd}). Secrets
> (ANTHROPIC_API_KEY, CS_API_TOKEN, SUPABASE_KEY) come from an existing Kubernetes Secret named in
> values.existingSecret, never from values.yaml. Add values-kind.yaml for local kind. Add a CI job
> "helm" in .github/workflows/ci.yml that runs helm lint and helm template (azure/setup-helm@v4).
> Update infra/k8s/README.md with "helm install cs infra/helm/cloudsentinel -f values-kind.yaml".*

✅ **Done when:** `helm install` on kind brings up all pods, and pausing beta from the dashboard scales its Deployment to 0.

### T9 (Day 6): one-command public deploy with a live demo URL
> Prompt for Antigravity:
> *Only edit infra/. Create infra/deploy/deploy.sh <ssh-host> that: copies the repo (rsync, excluding .env, data/,
> .git), installs Docker if missing, writes the remote .env from a local file passed as $2 (never commits it),
> and runs docker compose -f docker-compose.yml -f infra/deploy/compose.public.yml up -d --build.
> compose.public.yml adds a Caddy service (caddy:2.8) that serves HTTPS for $DEMO_DOMAIN and reverse-proxies
> /v1 → brain:8000 and / → the dashboard; it publishes only ports 80/443, and closes 4318/8000/8501 to the
> internet. It sets CS_API_TOKEN (required in public mode) and a DEMO_READONLY note. Add infra/deploy/README.md
> with the exact steps for a fresh Ubuntu 24.04 VM, and a "teardown" command.*

✅ **Done when:**
- `https://<your-domain>/v1/health` answers from a phone on mobile data.
- The demo runs there.
- A request without the token gets 401.
- Put the URL in README.md.

### T10 (every checkpoint): integration + merges
At CP1–CP4, follow PLAN.md "Integration checkpoint procedure". At each CP, also run `python -m eval.harness`
(Orin fills the results table), and tag `cp1`…`cp4`.
✅ **Done when:** each CP has a tag, a short "CP result" line in PLAN.md, and an issue for every failure.

## 🟡 SHOULD

### T11 (Day 6–7): distributed C2 across nodes
One brain controls agents on **several machines**. Each machine runs a small "node agent" that executes the brain's commands locally.
> Prompt for Antigravity:
> *Read docs/CONTRACTS.md section 9 and infra/executor/. Only edit infra/. (1) Create infra/node_agent/ — a
> tiny FastAPI app (python -m infra.node_agent, port 8770) that wraps the local DockerExecutor and exposes
> GET /agents, POST /agents/{id}/{pause|resume|kill|restart|rogue}; every request must carry header X-CS-Token
> equal to settings.api_token (reject with 401 otherwise). (2) Create infra/executor/http_exec.py: HttpExecutor(url)
> implements the Executor protocol by calling one node agent (timeout 3 s; any error → ExecResult(False, msg)).
> (3) Create infra/executor/multi.py: MultiExecutor reads infra/nodes.yaml ({nodes: [{name, url}]}), merges
> list_agents from all nodes (adds node name to RuntimeInfo.runtime as "docker@<name>"), and routes each
> command to the node that owns the agent; a node that is down is skipped and logged, never crashes.
> (4) In infra/executor/__init__.py, EXECUTOR=multi returns MultiExecutor. (5) Add
> infra/docker-compose.nodes.yml that starts 2 node agents with 2 agents each, to simulate 2 machines on one
> laptop. Tests in infra/tests/ with fake node agents (httpx MockTransport).*

✅ **Done when:** with `docker compose -f infra/docker-compose.nodes.yml up -d` and `EXECUTOR=multi python -m brain`, the dashboard
shows agents from both nodes, and pausing one on node 2 works.

### T12 (Day 7): Prometheus + Grafana
> Prompt for Antigravity:
> *Only edit infra/ and docker-compose.yml. Create infra/exporter/ (python -m infra.exporter, port 9108): every
> 5 s it reads GET /v1/fleet and GET /v1/roi from the C2 API (settings.api_url, header X-CS-Token) and exposes
> Prometheus text metrics with prometheus_client: cloudsentinel_agent_usd_per_min{agent},
> cloudsentinel_agent_tokens_per_min{agent}, cloudsentinel_agent_state{agent,state} (1/0),
> cloudsentinel_agent_loop_score{agent}, cloudsentinel_saved_usd_total, cloudsentinel_spend_usd_total,
> cloudsentinel_interventions_total. If the API is down, keep the last values and set cloudsentinel_up 0.
> Add compose services prometheus (prom/prometheus:v2.55.1) and grafana (grafana/grafana:11.3.0) under
> profile "monitoring", with provisioning files in infra/grafana/ (datasource + one dashboard JSON with: $/min
> per agent, fleet state, $ saved, interventions). Tests for the exporter with a fake API.*

✅ **Done when:** `docker compose --profile monitoring up -d` → Grafana at http://localhost:3000 shows beta's $/min drop to 0 when it's paused.

### T13 (Day 7): load test with 50+ agents
> Prompt for Antigravity:
> *Only edit infra/. Create infra/load/run.py: starts N (default 50) copies of telemetry/simulators/agent.py
> as subprocesses with CS_AGENT_ID=load-01..load-N (10% of them go rogue at random times, mixed kinds),
> pointing at the local collector, for M minutes. Every 5 s it records: the brain's tick time (from
> GET /v1/health if present, otherwise the time of a /v1/fleet call), collector accepted spans/s, how many rogue
> agents were caught and the seconds to catch each. At the end it writes infra/load/RESULTS.md with a table
> for N = 10, 25, 50 (and 100 if it holds). Stop every subprocess on Ctrl-C.*

✅ **Done when:** `RESULTS.md` shows 50 agents with every rogue caught and the API answering in < 500 ms.
If not, file an issue for `brain` with the numbers. Alif's agent picks it up in A8.

### T14 (Day 8): fresh-laptop test
On a laptop that has never run the project, follow `docs/HANDOFF.md` §4 and README.md exactly, and time it. Fix the docs.
✅ **Done when:** a fresh setup reaches the dashboard in under 15 minutes.

### T15 (Day 5): web dashboard in compose (for Tamjid)
Tamjid's React dashboard (`dashboard/web/`) ships a `Dockerfile` (nginx serving the build, proxying `/v1` to brain).
Add a `web` service on port 5173→80 to `docker-compose.yml` and to the Helm chart, and keep Streamlit as `dashboard`.
✅ **Done when:** `docker compose up -d --build` serves the React dashboard at http://localhost:5173, against the real brain.

## 🟢 STRETCH
- **T16:** K8s across 3 kind nodes with agents pinned to different nodes (nodeSelector), to show distributed C2 in Kubernetes on the same slide.
- **T17:** a nightly job that deploys `main` to the public VM after CI passes (GitHub Actions + SSH deploy key as a secret).
- **T18:** an Ingress plus a cert-manager example in the Helm chart.

---

## Notes from the lead (Wed 4 Nov), read before Day 1
1. **The cloud session couldn't reach `cloudcampbd.com` or see `ANTHROPIC_API_KEY`.** Both are now H3 and H5.
2. **If `docker pause` fails**, the brain still marks the agent paused, writes a critical `executor_failed` alert,
   and the tool gate denies all its tools. Check on Day 2 that the alert shows on the dashboard.
3. Agents without a container (LangGraph/CrewAI scripts) are paused **by the SDK** between steps. The brain records
   "no container: enforced by the SDK" instead of an alert. That's expected.
4. The nightly workflow (`.github/workflows/nightly.yml`) runs the full suite, the harness and the E2E/chaos tests
   at 01:00 BST, and opens an issue labelled `nightly` when it fails. Alif's agent reads those issues.

## Contract requests
(Write here if you need a new setting, field or endpoint. Alif's agent implements it on a `contract/` branch: task A0.)
- T9 public mode: none needed. `CS_API_TOKEN` already exists.

## Requests from Alif's agent
(Alif's agent writes here when it needs a human: a key, an account, a GitHub setting. Do these first each morning.)
