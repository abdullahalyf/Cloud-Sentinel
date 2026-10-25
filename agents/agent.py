"""
Simulated AI agent that runs inside a Docker container.   Owner: Fojle.

It pretends to call an LLM (no real API calls → costs nothing) and reports every
"call" on stdout using the log protocol in shared/contracts.py. The sentinel reads that.

Modes:
  normal – a few calls per minute, different prompts each time (a healthy agent)
  rogue  – stuck in a loop: the same prompt over and over, faster and faster,
           and memory keeps growing (a broken agent)

An agent switches to rogue when ANY of these happens:
  • env AGENT_MODE=rogue
  • env ROGUE_AFTER=<seconds> and that many seconds have passed
  • the file /tmp/go_rogue appears  (the dashboard's "Simulate rogue" button does this)

Fojle: this is a working baseline. Make the rogue behaviour more realistic/dramatic.
"""
from __future__ import annotations

import os
import random
import time

from shared.contracts import emit

NAME = os.getenv("AGENT_NAME", "agent")
MODE = os.getenv("AGENT_MODE", "normal").lower()
ROGUE_AFTER = float(os.getenv("ROGUE_AFTER", "0") or 0)
FLAG_FILE = "/tmp/go_rogue"

TASKS = [
    "Summarize today's support tickets",
    "Draft a reply to customer about delayed shipment",
    "Classify invoice line items into categories",
    "Extract action items from the meeting notes",
    "Check inventory levels and flag low stock",
    "Write SQL to find top 10 customers by revenue",
]
LOOP_PROMPT = "Retry: fetch order #4471 status from API and summarize the result"


def is_rogue(started: float) -> bool:
    return (
        MODE == "rogue"
        or (ROGUE_AFTER > 0 and time.time() - started >= ROGUE_AFTER)
        or os.path.exists(FLAG_FILE)
    )


def main() -> None:
    started = time.time()
    rogue_since: float | None = None
    leak: list[bytearray] = []      # rogue mode keeps adding to this → memory grows
    emit(NAME, "heartbeat", message="agent started")

    while True:
        if rogue_since is None and is_rogue(started):
            rogue_since = time.time()
            print(f"[{NAME}] something went wrong... entering retry loop", flush=True)

        if rogue_since is None:
            task = random.choice(TASKS)
            emit(NAME, "llm_call", tokens_in=random.randint(100, 450), tokens_out=random.randint(50, 250),
                 model="sim-model", prompt=f"{task} (job {random.randint(1000, 9999)})")
            time.sleep(random.uniform(2.0, 5.0))
        else:
            seconds = time.time() - rogue_since
            emit(NAME, "llm_call", tokens_in=random.randint(300, 340), tokens_out=random.randint(60, 90),
                 model="sim-model", prompt=LOOP_PROMPT)
            leak.append(bytearray(b"x" * (8 * 1024 * 1024)))  # +8 MB per call (filled, so RAM really grows)
            time.sleep(1.0 / (1.0 + 0.05 * seconds))          # gets faster every second


if __name__ == "__main__":
    main()
