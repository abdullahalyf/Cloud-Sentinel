"""
ShopBD support crew built with CrewAI, monitored by CloudSentinel with ONE instrument() call.   Owner: Fojle.

    # in the AGENT's own venv (crewai pins mcp<2, the brain needs mcp>=2 → keep them apart):
    pip install -e "telemetry/sdk[crewai]"
    CS_AGENT_ID=crew-support python telemetry/examples/crewai_support_crew.py

Two agents, two tasks:  triage (reads the ticket)  →  refunds (calls the issue_refund tool).
Every 3rd ticket asks for a 50,000 BDT refund: the CloudSentinel tool gate holds it for a human
(dashboard approval card); deny → the crew is told the tool was blocked and answers without refunding.
A small refund (800 BDT) goes straight through.

LLM: an offline scripted model by default (no key, costs nothing) that speaks CrewAI's ReAct format and
reports token usage, so you see real chat spans. --claude uses Claude via the anthropic SDK.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Optional

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")   # no CrewAI phone-home in demos (synthetic data only)
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))
import cloudsentinel as cs  # noqa: E402
from cloudsentinel.adapters.crewai import flush, instrument  # noqa: E402
from crewai import Agent, Crew, Process, Task  # noqa: E402
from crewai.events.types.llm_events import LLMCallType  # noqa: E402
from crewai.llms.base_llm import BaseLLM, llm_call_context  # noqa: E402
from crewai.tools import tool  # noqa: E402

BDT_PER_USD = 122
TICKETS = ["Order {order} arrived broken, please refund {amount} BDT", "My parcel {order} never came. I want {amount} BDT back",
           "Wrong size delivered for #{order}; refund {amount} BDT please", "Refund {amount} BDT for order {order}, item damaged"]


class ScriptedLLM(BaseLLM):
    """Offline LLM: triage answers directly; refunds first calls issue_refund, then gives a final answer."""

    def call(self, messages: Any, tools: Any = None, callbacks: Any = None, available_functions: Any = None,
             from_task: Any = None, from_agent: Any = None, response_model: Any = None) -> str:
        msgs = messages if isinstance(messages, list) else [{"role": "user", "content": str(messages)}]
        with llm_call_context():  # one call_id shared by the started/completed events
            return self._answer(msgs, from_task, from_agent)

    def _answer(self, msgs: list, from_task: Any, from_agent: Any) -> str:
        self._emit_call_started_event(messages=msgs, from_task=from_task, from_agent=from_agent)
        text = "\n".join(str(m.get("content", "")) for m in msgs)
        role = str(getattr(from_agent, "role", "") or ("Refunds" if "You are Refunds" in text else ""))
        acted = any(m.get("role") == "assistant" and "Action: issue_refund" in str(m.get("content", "")) for m in msgs)
        if "Refund" in role and not acted and "issue_refund" in text:
            amount = next((a for a in (50000, 1200, 800, 300) if f"{a} BDT" in text), 800)
            order = next((int(w.strip("#;,.")) for w in text.split() if w.strip("#;,.").isdigit()
                          and 4000 <= int(w.strip("#;,.")) < 5000), 4471)
            reply = ('Thought: The customer is owed a refund, I will issue it.\nAction: issue_refund\n'
                     f'Action Input: {{"order_id": {order}, "amount": {amount}}}')
        else:
            reply = "Thought: I now know the final answer\nFinal Answer: " + (
                "Refund handled as the tool allowed." if "Refund" in role else "Ticket is a refund request.")
        usage = {"prompt_tokens": 250 + len(text) // 4, "completion_tokens": random.randint(40, 120)}
        self._emit_call_completed_event(response=reply, call_type=LLMCallType.LLM_CALL, from_task=from_task,
                                        from_agent=from_agent, messages=msgs, usage=usage)
        return reply


def claude_llm() -> Any:
    from crewai import LLM

    return LLM(model=f"anthropic/{os.getenv('CLAUDE_MODEL', 'claude-haiku-5-5')}", max_tokens=300)


@tool("issue_refund")
def issue_refund(order_id: int, amount: int) -> str:
    """Refund a customer order. amount is in BDT."""
    return f"refunded {amount} BDT for order {order_id}"


def build_crew(llm: Any) -> Crew:
    triage = Agent(role="Triage", goal="Understand the customer's ticket", backstory="ShopBD support desk",
                   llm=llm, allow_delegation=False, verbose=False)
    refunds = Agent(role="Refunds", goal="Refund customers who are owed money", backstory="ShopBD refunds desk",
                    tools=[issue_refund], llm=llm, allow_delegation=False, verbose=False, max_iter=3)
    t1 = Task(description="Read this ticket and say what the customer wants: {ticket}",
              expected_output="one sentence", agent=triage)
    t2 = Task(description="Issue the refund the ticket asks for using the issue_refund tool. Ticket: {ticket}",
              expected_output="what was refunded", agent=refunds)
    return Crew(agents=[triage, refunds], tasks=[t1, t2], process=Process.sequential, verbose=False)


def setup(agent_id: Optional[str] = None) -> None:
    cs.init(agent_id=agent_id or os.getenv("CS_AGENT_ID", "crew-support"), runtime=os.getenv("CS_RUNTIME", "local"))
    instrument(value_usd={"issue_refund": lambda a: round(float(a.get("amount", 0)) / BDT_PER_USD, 2)},
               fail_closed=("issue_refund",))   # money moves → never run it if CloudSentinel is unreachable


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--claude", action="store_true", help="use Claude instead of the offline scripted LLM")
    p.add_argument("--tickets", type=int, default=0, help="stop after N tickets (0 = run forever)")
    args = p.parse_args()
    setup()
    crew = build_crew(claude_llm() if args.claude else ScriptedLLM(model="sim"))
    n = 0
    while not args.tickets or n < args.tickets:
        n += 1
        amount = 50000 if n % 3 == 0 else random.choice([300, 800, 1200])
        order = 4471 if amount == 50000 else random.randint(4400, 4600)   # real tickets differ (see brain/loops.py)
        ticket = random.choice(TICKETS).format(order=order, amount=amount)
        try:
            out = crew.kickoff(inputs={"ticket": ticket})
            print(f"[{cs._s.agent_id}] ticket {n}: {out.raw}", flush=True)
        except Exception as exc:  # a blocked/killed crew raises: log and continue with the next ticket
            print(f"[{cs._s.agent_id}] ticket {n} failed: {exc}", flush=True)
        flush()   # wait for CrewAI's event handlers, then export
        time.sleep(3.0)


if __name__ == "__main__":
    main()
