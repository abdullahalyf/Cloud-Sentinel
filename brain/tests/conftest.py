from dataclasses import replace

import pytest

from brain import service
from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from shared.config import settings
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore


@pytest.fixture
def cfg():
    return replace(settings, judge_provider="fallback", anthropic_api_key="", gemini_api_key="")


class Sim:
    """Brain + fake fleet on a virtual clock."""

    def __init__(self, cfg):
        self.store = LocalStore(":memory:")
        self.policy = Policy.load("brain/policies.yaml")
        self.fleet = FakeFleet(self.store, auto_rogue=None, start=1000.0)
        self.fleet.gate = lambda a, t, args, v: service.request_tool_call(self.store, self.policy, a, t, args, v)
        self.engine = Engine(self.store, self.fleet, Judge(cfg), self.policy, cfg, sync_judge=True)
        self.now = 1000.0

    def run(self, seconds: int) -> None:
        for _ in range(seconds):
            self.now += 1
            self.fleet.step(self.now)
            self.engine.tick(self.now)

    def state(self, agent: str) -> str:
        return self.engine.breakers[agent].state

    def command(self, agent: str, command: str, **params) -> None:
        service.post_command(self.store, agent, command, params, "dashboard", "test")


@pytest.fixture
def sim(cfg):
    return Sim(cfg)


# ── the E2E and chaos harness ──────────────────────────────────────────────
# It lives here, in the one conftest that pytest already loads, because a second
# `conftest.py` in `brain/tests/e2e/` would have the same module name as this one and
# pytest would not load it (the directories are not packages).
from brain.tests.e2e_harness import Harness  # noqa: E402


@pytest.fixture
def harness(tmp_path):
    """The real processes of one test: a brain, a collector, an agent.

    Every process is killed at the end, however the test ended.
    """
    h = Harness(tmp=tmp_path)
    try:
        yield h
    finally:
        h.stop_all()
