"""
Simulated AI agent that runs inside a Docker container.   Owner: Fojle.

It pretends to call an LLM (no real API calls → costs nothing) and reports every
"call" on stdout using the log protocol in shared/contracts.py. The sentinel reads that.

Modes:
  normal – a few calls per minute, different prompts each time (a healthy agent)
  rogue  – a broken agent. HOW it breaks is chosen with env ROGUE_TYPE:

      loop         the same prompt over and over, faster and faster, RAM grows too  (default)
      token_bomb   different prompts, but every call burns 5,000–15,000 tokens
      memory_leak  calls look normal, but RAM grows fast

An agent switches to rogue when ANY of these happens:
  • env AGENT_MODE=rogue
  • env ROGUE_AFTER=<seconds> and that many seconds have passed
  • the file /tmp/go_rogue appears  (the dashboard's "Simulate rogue" button does this)

Safety: leaked RAM is capped at env LEAK_CAP_MB (default 400) so a demo can never freeze
your laptop. Keep it BELOW the container memory limit in docker-compose.yml.
"""
from __future__ import annotations

import os
import random
import time

from shared.contracts import emit

NAME = os.getenv("AGENT_NAME", "agent")
MODE = os.getenv("AGENT_MODE", "normal").lower()
ROGUE_TYPE = os.getenv("ROGUE_TYPE", "loop").lower()
ROGUE_AFTER = float(os.getenv("ROGUE_AFTER", "0") or 0)
LEAK_CAP_MB = int(os.getenv("LEAK_CAP_MB", "400") or 400)
FLAG_FILE = "/tmp/go_rogue"

ROGUE_TYPES = ("loop", "token_bomb", "memory_leak")

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


def leak_ram(leak: list[bytearray], mb: int) -> None:
    """Grab `mb` MB of REAL memory (filled, so the OS can't skip it), up to LEAK_CAP_MB."""
    if sum(len(b) for b in leak) < LEAK_CAP_MB * 1024 * 1024:
        leak.append(bytearray(b"x") * (mb * 1024 * 1024))


def healthy_call() -> None:
    task = random.choice(TASKS)
    emit(NAME, "llm_call", tokens_in=random.randint(100, 450), tokens_out=random.randint(50, 250),
         model="sim-model", prompt=f"{task} (job {random.randint(1000, 9999)})")


def rogue_loop(seconds: float, leak: list[bytearray]) -> None:
    """Same prompt again and again, faster every second. (Original behaviour.)"""
    emit(NAME, "llm_call", tokens_in=random.randint(300, 340), tokens_out=random.randint(60, 90),
         model="sim-model", prompt=LOOP_PROMPT)
    leak_ram(leak, 8)
    time.sleep(1.0 / (1.0 + 0.05 * seconds))


def rogue_token_bomb(seconds: float) -> None:
    """Prompts are all different (so it is NOT a loop), but each call is gigantic."""
    total = random.randint(5000, 15000)
    tokens_in = int(total * 0.8)                      # whole history dumped into the context
    emit(NAME, "llm_call", tokens_in=tokens_in, tokens_out=total - tokens_in, model="sim-model",
         prompt=f"{random.choice(TASKS)} + full conversation history (job {random.randint(1000, 9999)})")
    time.sleep(max(0.5, 1.5 - 0.05 * seconds))        # starts at ~1 call/1.5s, speeds up to 2/s


def rogue_memory_leak(seconds: float, leak: list[bytearray]) -> None:
    """Calls look perfectly healthy. The only symptom is RAM climbing."""
    healthy_call()
    leak_ram(leak, 16)
    time.sleep(random.uniform(0.7, 1.1))


def main() -> None:
    rogue_type = ROGUE_TYPE if ROGUE_TYPE in ROGUE_TYPES else "loop"
    if rogue_type != ROGUE_TYPE:
        print(f"[{NAME}] unknown ROGUE_TYPE '{ROGUE_TYPE}', using 'loop'", flush=True)

    started = time.time()
    rogue_since: float | None = None
    leak: list[bytearray] = []      # rogue modes keep adding to this → memory grows
    emit(NAME, "heartbeat", message="agent started")

    while True:
        if rogue_since is None and is_rogue(started):
            rogue_since = time.time()
            print(f"[{NAME}] something went wrong... entering {rogue_type} mode", flush=True)

        if rogue_since is None:
            healthy_call()
            time.sleep(random.uniform(2.0, 5.0))
            continue

        seconds = time.time() - rogue_since
        if rogue_type == "token_bomb":
            rogue_token_bomb(seconds)
        elif rogue_type == "memory_leak":
            rogue_memory_leak(seconds, leak)
        else:
            rogue_loop(seconds, leak)


if __name__ == "__main__":
    main()