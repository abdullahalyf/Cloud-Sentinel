"""
A REAL agent powered by Claude, instrumented with the cloudsentinel SDK.   Owner: Fojle (Day 5).
Proves CloudSentinel governs real LLM traffic, not only simulators.

    ANTHROPIC_API_KEY=... CS_AGENT_ID=delta python telemetry/simulators/real_agent.py
"""
from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk"))
import cloudsentinel as cs  # noqa: E402

MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
CUSTOMER_MESSAGES = [  # synthetic data only
    "My parcel from Chattogram is 3 days late, where is it?",
    "Can I return a shirt I bought last week?",
    "The bKash payment went through but the order shows unpaid.",
    "Do you deliver to Sylhet?",
]


def main() -> None:
    cs.init(agent_id=os.getenv("CS_AGENT_ID", "delta"), runtime="local")
    import anthropic

    client = anthropic.Anthropic()
    while True:
        message = random.choice(CUSTOMER_MESSAGES)
        with cs.task("answer customer") as t:
            # TODO(Fojle Day 5): wrap this call in `with cs.llm_call(model=MODEL, provider="anthropic",
            #   prompt=message) as call:` and call call.record(...) with response.usage.input_tokens /
            #   response.usage.output_tokens. Do not send temperature.
            response = client.messages.create(model=MODEL, max_tokens=200,
                                              messages=[{"role": "user", "content": f"Reply in one sentence: {message}"}])
            print(next((b.text for b in response.content if b.type == "text"), ""), flush=True)
            t.success()
        time.sleep(10)


if __name__ == "__main__":
    main()
