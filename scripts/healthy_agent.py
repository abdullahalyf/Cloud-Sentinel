"""
A well-behaved test agent for scripts/healthy_agents.py. Never goes rogue. STYLE picks the prompts:

  names   one template, different customer names, no numbers
  year    every prompt contains the year 2026
  jobs    "Process job <n>" with a new job number every call
"""
from __future__ import annotations

import itertools
import os
import random
import time

from shared.contracts import emit

NAME = os.getenv("AGENT_NAME", "healthy")
STYLE = os.getenv("STYLE", "names")
RATE = float(os.getenv("CALLS_PER_SEC", "2"))
FIRST = ["Alice", "Bob", "Carla", "Dev", "Emma", "Farid", "Grace", "Hana", "Ivan", "Jin", "Kofi", "Lena", "Mateo",
         "Nadia", "Omar", "Priya", "Quinn", "Rosa", "Sven", "Tara", "Uma", "Viktor", "Wen", "Xavi", "Yara", "Zane"]
LAST = ["Rahman", "Chowdhury", "Mendes", "Patel", "Larsen", "Khan", "Okafor", "Sato", "Petrov", "Park", "Nguyen",
        "Silva", "Berg", "Haddad", "Ito", "Costa", "Novak", "Reyes", "Ali", "Dubois", "Eriksen", "Fofana"]


def customer() -> str:
    return f"{random.choice(FIRST)} {random.choice(LAST)}"   # ~570 different customers


def prompts():
    for n in itertools.count(1000):
        who = customer()
        if STYLE == "year":
            yield f"Summarize the 2026 support tickets of customer {who}"
        elif STYLE == "jobs":
            yield f"Process job {n} from the nightly queue"
        else:
            yield f"Draft a polite reply to customer {who} about the delayed shipment"


def main() -> None:
    emit(NAME, "heartbeat", message="agent started")
    for prompt in prompts():
        emit(NAME, "llm_call", tokens_in=random.randint(100, 160), tokens_out=random.randint(40, 90),
             model="sim-model", prompt=prompt)
        time.sleep(random.uniform(0.7, 1.3) / RATE)


if __name__ == "__main__":
    main()
