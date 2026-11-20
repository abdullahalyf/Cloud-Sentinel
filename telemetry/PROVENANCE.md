# Provenance

What data CloudSentinel uses, which models it calls, and under which licences its dependencies come.
Checked on 16 Nov 2026 against the installed packages (`importlib.metadata`) and the source files named below.

## Data

- The simulated agents (`telemetry/simulators/agent.py`), the demo agents in `telemetry/examples/` and
  `telemetry/simulators/real_agent.py` use **synthetic data only**: made-up customers, order numbers
  (for example 4471) and messages. No real customer data.
- This file does not make a claim about the evaluation datasets under `brain/eval_data/` or about data other
  team members added. Check those separately.

## Models

| Where | Model | Needs a key? | Notes |
|---|---|---|---|
| `telemetry/simulators/agent.py` | `sim-model` | no | A name only. No LLM is called; tokens and cost are made up (priced like a mid-size model in `shared/pricing.py`). |
| `telemetry/simulators/real_agent.py` | `claude-haiku-5-5` (env `CLAUDE_MODEL`) | `ANTHROPIC_API_KEY` | One real Claude call per customer question; no `temperature` is sent. |
| Brain judge (`brain/judge.py`) | Claude: `CLAUDE_MODEL`, default `claude-haiku-5-5`; Gemini: `GEMINI_MODEL`, default `gemini-3.8-flash` | `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` | `JUDGE_PROVIDER=auto` picks Claude, else Gemini, else the rule-based `fallback`, which calls no model. |
| OpenAI Agents demo (`telemetry/examples/openai_agents_refund.py`) | `fake-model` | no | An offline fake model with fixed answers. |

Without any API key the whole system runs on the `fallback` judge and the simulators.

## Open-source dependencies (`requirements.txt`)

Licences as reported by the installed package metadata.

| Package | Version | Licence |
|---|---|---|
| python-dotenv | 1.2.4 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| fastapi | 0.162.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| mcp | 2.3.0 | MIT |
| anthropic | 2.5.0 | Apache-2.0 |
| opentelemetry-sdk | 1.45.2 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-http | 1.45.2 | Apache-2.0 |
| opentelemetry-proto | 1.45.2 | Apache-2.0 |
| docker | 7.2.0 | Apache-2.0 |
| supabase | 2.34.0 | MIT |
| streamlit | 1.66.1 | Apache-2.0 |
| pandas | 3.1.1 | BSD-3-Clause |
| plotly | 7.1.0 | MIT |
| pytest | 9.2.0 | MIT |

Optional packages mentioned in `requirements.txt` (`google-genai`, `kubernetes`) and the dashboard's
npm packages (`dashboard/web/package.json`) are not covered here.
Not legal advice: the table copies what each package declares.
