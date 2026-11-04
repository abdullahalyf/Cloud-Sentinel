# Hackathon research: International AI Builders Congress 2026

> **How this was collected (2026-11-04).** `cloudcampbd.com` and `millionxbangladesh.org` are
> **blocked by this cloud session's network policy**, so the live site could not be crawled.
> Everything below comes from:
> 1. A public, MIT-licensed snapshot of the official site at
>    [github.com/abumusasakib/cloudcamp-bd-mcp](https://github.com/abumusasakib/cloudcamp-bd-mcp)
>    (`knowledge-base-ai-builders-congress.md`). It was scraped from the live
>    `cloudcampbd.com/ai-builders-congress` page with a headless browser on **2026-08-23**,
>    including all 11 domain tabs and all 281 FAQ answers.
> 2. A web search on 2026-11-04 (event date, venue, sponsors).
> 3. The track brief that the team was given (the AgentOps example prompts).
>
> **Action for Taseen (team lead):** log in to the platform and check the three items marked
> ⚠️ VERIFY against your team dashboard. The snapshot is 2.5 months old.

## 1. Event basics

| Item | Value |
|---|---|
| Name | International AI Builders Congress 2026 |
| Organizer | CloudCamp Bangladesh (co-organizer: Daffodil International University) |
| Tagline | "Build What Matters. Scale What Works. Shape What Comes Next." |
| Format | A 6-month builder journey (started 1 Jul 2026) that ends on **Congress Day, 26 Dec 2026**, DIU Ashulia Campus, Dhaka, 7:00 AM–7:30 PM |
| Scale | 11 domains, 55 challenges. ~1,500 participants and 280 teams on 23 Aug |
| Sponsors | Platinum: **Anwar Group**. Silver: **RRAD**. Creative partner: Sceneborn |
| Technology partners | **AWS**, **Lovable.dev**, Career Canvas, Astronus Tech |
| Contact | Secretariat@cloudcampbd.com · +880 16708 42356 |

## 2. Our track

**Domain: InfraSphere AI.** "The foundational layer: secure AI, agent operations, knowledge
systems, and human+AI work." It has five challenges: SecureAI, WorkforceOS, Knowledge Grid,
**AgentOps**, and Human+AI.

**Challenge: AgentOps.** "Build, deploy, monitor, and govern AI agents at scale."
The brief we were given asks for reliable, governable agent systems, with **MCP + observability +
evaluation**. Its example prompts:

| # | Example prompt | What it really asks for |
|---|---|---|
| P1 | Recursive-loop token-flow dashboard | Live view of tokens moving through an agent, with loops made visible |
| P2 | Circuit breaker | Automatically stop a runaway agent (cost, loop, resources) |
| P3 | Command & Control API | A human can **edit agent memory** and **override tool calls** at runtime |
| P4 | OTel telemetry library | A drop-in SDK that emits OpenTelemetry (GenAI semantic conventions) |
| P5 | ROI attribution engine | Cost per agent/task, and the value of interventions |

The FAQ says each challenge lists "what to build, the AI capabilities to demonstrate and the
**winning signal** judges look for". The Solution section of the submission must explain
"how it maps to the challenge's Winning Signal". ⚠️ VERIFY: copy the exact AgentOps "winning
signal" text from the platform into `docs/DECISION.md` §6.

## 3. Competitions and deadlines

There are two competitions inside the Congress. Ours is the **team** one: **Idea to Unicorn (I2U)**.

| Competition | Who | Window (from the official "Phases & Stages" widget) |
|---|---|---|
| **Idea to Unicorn** | Teams of 3–6 (we are 5 ✅) | Preliminary: Jul 1–Oct 31 2026 on the widget. The FAQ also says "mid-November", "1–20 Nov", and a **Final Submission on 24 Dec 2026, 24:00 BST** |
| Zero to Launch | Individuals only, one prompt, one hour, live on Congress Day | Preliminary Oct 15–Nov 15 2026 |

⚠️ VERIFY: the team works to a **15 Nov** submission deadline. The site's dates disagree with each
other (the snapshot author noted FAQ dates were reused from older events). Treat **15 Nov 23:59 BST**
as the hard deadline. If the platform says 20 Nov, use the extra days as buffer only.

Things that matter for planning:
- Deadlines are in **BST (UTC+6)**. Locking happens server-side, with **no grace period**.
- A submission goes **Draft → Submitted → Locked**. Only the **team leader (Taseen)** can submit.
  Before the deadline, the leader can revert to Draft and resubmit as often as needed.
  **Submit a complete draft early (Nov 13)** and keep improving it.
- Teams lock when the preliminary window opens. You cannot change members after that.
- Shortlisted teams build further for the **Final (24 Dec)** and pitch live on **26 Dec**
  (1 min transition + **3 min pitch** + 1 min scoring).

## 4. Required deliverables

**Preliminary (mandatory fields):** project name, one-line pitch, domain, challenge, structured
problem statement, proposed solution, target user, **prototype link or repo**, team roles,
initial mentor engagement notes. Video is optional at this stage. We make one anyway.

**Final adds:** a working demo link, a GitHub repo link, a **public or unlisted YouTube demo**
(3–5 minutes, with a thumbnail; judges stop watching at 7 minutes), a tooling and IDE disclosure,
an **MCP usage disclosure**, a **prompt library**, and a **Data & AI provenance** section.

**The 8 submission sections:**
1. Basics: name, pitch, domain, challenge, public summary, team language.
2. Problem statement: who the user is, today's pain, why existing tools fail, the measurable outcome.
3. Solution: product, AI architecture, features, user journey, and how it maps to the Winning Signal.
4. Demo & links: every link is checked as PASS, RESTRICTED, or FAIL. **Keep the repo public** so it passes.
5. Data & AI provenance: datasets, licences, personal data handling, and which foundation models.
   *Scored under "AI & Data Use".* We use **synthetic data only**.
6. Tooling + IDE + memory/context files: Claude Code, Codex, Antigravity, `AGENTS.md`,
   `.agents/rules/`, `CLAUDE.md`. *Supports "AI-native workflow" scoring.*
7. MCP usage disclosure. **"This affects AgentOps/architecture scoring."** Our MCP server is a
   core feature (see `docs/CONTRACTS.md` §6).
8. Prompt library: the prompts behind the product (judge prompt, coding prompts, eval prompts).
   Each prompt can be toggled proprietary. We already have ready-to-paste prompts in `docs/tasks/`.

**Common mistakes the FAQ warns about:** a Private YouTube video, a private repo with no Judge
Access Note, an empty prompt library, a missing MCP disclosure, or a broken demo link at the deadline.

**Demo video content the judges expect:** problem → solution walkthrough → **live demo of the
product actually running with real inputs and outputs** → team intro → call to action.

## 5. Judging

Each submission gets at least 5 judges. With 4 or more judges, the highest and lowest scores are
dropped (trimmed mean). If judges disagree by 25 points or more, an extra judge is added.

**Official rubric (shown on the Congress page, 100 points):**

| Criterion | Weight | Top band (what "max score" means) | How we score high |
|---|---|---|---|
| Innovation | 20 | "breakthrough" | Enforcement **outside** the agent + AI judge for gray zones + heal instead of kill (memory edit). Nobody else ships the full observe → decide → act loop |
| Technical Execution | 20 | "production-grade" | Works end-to-end live, OTel-native, tests, CI, Docker + K8s, fails safe when the LLM is down |
| Business Model + Global Readiness | 20 | "scalable / globally adaptable" | Open-core: free OSS SDK, paid hosted control plane per agent. "Pays for itself": the ROI engine shows dollars saved |
| Real-World Impact + Ethical AI | 20 | "high social return + **documented safeguards**" | Protects BD startups and SMEs from surprise bills. Human-in-the-loop, audit log, prompt-injection defence, synthetic data. Write `docs/ETHICS.md` |
| Scalability + NRB Collaboration | 10 | "clear pathway + strong global collaboration" | K8s executor, 10-agent scale demo. ⚠️ Find **one real NRB mentor or reviewer**. Even one documented design review counts. Do not fake this: faking it is a policy violation |
| Presentation | 10 | "compelling / investor-ready" | 3-minute pitch with a live kill on stage and a big "$ saved" counter |

The FAQ also contains a second, template rubric (Impact 25, Technical 25, **AI & Data Use 20**,
Innovation 15, Execution 15). We cover both. AI & Data Use rewards "evaluation methodology,
guardrails, agents, memory": that is our `/eval` harness and our guardrails.

**Ties are broken by** Innovation, then Technical, then Impact, then **earlier submission time**.
That is another reason to submit early.

**Score bands:** 0–39 Emerging · 40–59 Promising · 60–74 Strong · 75–89 Excellent · 90–100 World-Class.
Only Strong (60+) and above usually win named awards.

## 6. Awards and prizes

- Per-domain **Domain Champion** for each domain (for us: InfraSphere AI). Example prize from the FAQ:
  E-Commerce Champion 50,000 BDT, Runner-up 30,000 BDT. The full prize sheet was not public at scrape time.
- Overall awards: **Congress Champion** (best I2U team), Prompt Master (Z2L), **Impact Award**,
  Emerging Nation Builder, People's Choice (public vote on Congress Day), **NRB Collaboration Award**.
- **Sponsor awards** such as "Cloud Innovation" and "Security" are directly relevant to us. AWS is a
  technology partner: an optional AWS deploy (ECS or EKS, with CloudWatch export) could make us
  eligible for a cloud award.
- Non-cash: investor and hiring introductions, incubation, **cloud and API credits**.
- Past winners: none published for this event, since it is the first Congress. The earlier CloudCamp
  event "Zero to Agent: Bangladesh" (Apr 24 – May 3 2026) ended with no public winner list in our sources.

## 7. Rules that affect how we build

- **AI-assisted coding is allowed and encouraged**, but it must be disclosed.
  Keep a running `docs/PROMPTS.md` (prompt library) and `docs/TOOLING.md`.
- Original work only. Open-source libraries are allowed if we attribute them in the provenance section.
- **No real personal data** in demos. Our agents are simulated, and prompts are synthetic.
- Mentors may give feedback but **may not write code**.
- Disqualification reasons include a **fake demo** or a broken demo link. The live demo must be real:
  real containers, real kills, real Claude verdicts.
- "Prohibited security activity": our rogue agents must only attack themselves. Never point them at
  anything outside our sandbox.

## 8. Links

- Congress page: https://cloudcampbd.com/ai-builders-congress (blocked in this session)
- Participants Guide: https://docs.google.com/document/d/1R5IxFg4Xm2NfHThx9e1H1fKrWzus63fJx7i05VfNuDE
- Participant "Ask Anything" NotebookLM: https://notebooklm.google.com/notebook/86f3660f-4d2c-4ff2-a170-60a21ee1d0b1
- Policies: cloudcampbd.com/events/ai-builders-congress/policies
- Snapshot source: https://github.com/abumusasakib/cloudcamp-bd-mcp
- Daily Sangram news item: https://dailysangram.com/bangladesh/education-campus/PtZkezTeEEit/
