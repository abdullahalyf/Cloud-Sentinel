"""
Pydantic AI demo, offline (no API key): a fake model asks for a 50,000 BDT refund; issue_refund goes
through the CloudSentinel tool gate (fail_closed), so the refund waits for approval.

    CS_AGENT_ID=pai-refund python telemetry/examples/pydantic_ai_refund.py

Needs: pip install -e "telemetry/sdk[pydantic-ai]"   (own venv, see telemetry/sdk/README.md)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

import cloudsentinel as cs  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402

from cloudsentinel.adapters.pydanticai import guard, instrument  # noqa: E402


def fake_llm(messages, info) -> ModelResponse:
    """First turn: call the tool. After the tool result: answer."""
    returned = any(getattr(p, "part_kind", "") == "tool-return" for m in messages for p in m.parts)
    if returned:
        return ModelResponse(parts=[TextPart("done")])
    return ModelResponse(parts=[ToolCallPart("issue_refund", {"order_id": 4471, "amount": 50000})])


def build_agent() -> Agent:
    agent = Agent(FunctionModel(fake_llm), name="refunds")

    @agent.tool_plain
    @guard(value_usd=410.0, fail_closed=True)
    def issue_refund(order_id: int, amount: int) -> str:
        """Refund an order (amount in BDT)."""
        return f"refunded {amount} BDT on order {order_id}"

    return agent


def main() -> None:
    cs.init(agent_id=os.getenv("CS_AGENT_ID", "pai-refund"))
    instrument()
    try:
        print("answer:", build_agent().run_sync("refund order 4471").output)
    except cs.ToolDenied:
        print("refund blocked")
    cs.flush()


if __name__ == "__main__":
    main()