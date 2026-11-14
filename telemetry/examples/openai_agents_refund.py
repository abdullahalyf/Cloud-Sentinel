"""
OpenAI Agents demo, offline (no API key): triage hands off to refunds, refunds calls issue_refund.
issue_refund goes through the CloudSentinel tool gate (fail_closed): a 50,000 BDT refund waits for approval.

    CS_AGENT_ID=oai-refund python telemetry/examples/openai_agents_refund.py

Needs: pip install -e "telemetry/sdk[openai-agents]"   (use its own venv, see telemetry/sdk/README.md)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

import cloudsentinel as cs  # noqa: E402
from agents import Agent, Model, ModelResponse, Runner, Usage, function_tool  # noqa: E402
from agents.tracing import generation_span  # noqa: E402
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText  # noqa: E402

from cloudsentinel.adapters.openai_agents import guard, instrument  # noqa: E402


class FakeModel(Model):
    """Fixed answers and fake token usage, so the demo runs without a key."""

    def __init__(self, script):
        self.script = list(script)

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                           tracing, *, previous_response_id=None, conversation_id=None, prompt=None):
        with generation_span(model="fake-model", usage={"input_tokens": 100, "output_tokens": 20}):
            out = self.script.pop(0)
        return ModelResponse(output=out, usage=Usage(requests=1, input_tokens=100, output_tokens=20,
                                                     total_tokens=120), response_id=None)

    def stream_response(self, *a, **k):
        raise NotImplementedError


def _call(name, args):
    return [ResponseFunctionToolCall(arguments=json.dumps(args), call_id="c-" + name, name=name, type="function_call")]


def _say(text):
    return [ResponseOutputMessage(id="m1", role="assistant", status="completed", type="message",
                                  content=[ResponseOutputText(text=text, type="output_text", annotations=[])])]


@function_tool
@guard(value_usd=410.0, fail_closed=True)
def issue_refund(order_id: int, amount: int) -> str:
    """Refund an order (amount in BDT)."""
    return f"refunded {amount} BDT on order {order_id}"


def main() -> None:
    cs.init(agent_id=os.getenv("CS_AGENT_ID", "oai-refund"))
    instrument()
    refunds = Agent(name="refunds", instructions="Refund orders.", tools=[issue_refund],
                    model=FakeModel([_call("issue_refund", {"order_id": 4471, "amount": 50000}), _say("done")]))
    triage = Agent(name="triage", instructions="Route the request.", handoffs=[refunds],
                   model=FakeModel([_call("transfer_to_refunds", {})]))
    try:
        result = Runner.run_sync(triage, "refund order 4471")
        print("answer:", result.final_output)
    except cs.ToolDenied:
        print("refund blocked")
    cs.flush()


if __name__ == "__main__":
    main()