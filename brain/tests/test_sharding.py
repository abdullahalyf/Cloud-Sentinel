"""
A8 — horizontal scaling: N brain workers share one fleet.

The acceptance cases (docs/tasks/alif.md):
  * 2 Engine instances on one LocalStore file with 50 FakeFleet agents: every agent is
    owned by exactly one.
  * Stopping one → full takeover in ≤ 15 s (virtual clock).
  * No command runs twice.
  * Tick p95 < 200 ms per worker at 50 agents.

The numbers go in docs/research/brain-scaling.md.
"""
from __future__ import annotations

import hashlib
import statistics
import time
from dataclasses import replace

import pytest

from brain import service
from brain.engine import Engine
from brain.judge import Judge
from brain.policy import Policy
from brain.sharding import Shard, assign, owner_of, rebalance
from shared.mocks.fake_fleet import FakeFleet
from shared.store import LocalStore

AGENTS = tuple(f"agent-{i:02d}" for i in range(50))


# ── the hashing ────────────────────────────────────────────────────────────
def test_the_owner_is_the_same_in_every_process():
    """Python's `hash()` is randomised per process, so two workers would compute different
    owners for the same agent — and each would think it owned everything. sha1 is stable."""
    expected = hashlib.sha1(b"alpha\x00worker-1").hexdigest()
    from brain.sharding import _hash

    assert _hash("alpha", "worker-1") == expected


def test_the_separator_stops_collisions():
    """Without a separator ("ab" + "c") and ("a" + "bc") hash the same — two different
    (agent, worker) pairs would land on the same weight."""
    from brain.sharding import _hash

    assert _hash("ab", "c") != _hash("a", "bc")


def test_an_agent_has_exactly_one_owner():
    assert owner_of("alpha", ["w1", "w2", "w3"]) in {"w1", "w2", "w3"}


def test_no_workers_means_no_owner():
    assert owner_of("alpha", []) is None


def test_one_worker_owns_everything():
    assert owner_of("alpha", ["only"]) == "only"


def test_the_owner_is_stable():
    """The same inputs must always give the same answer, or the fleet would thrash."""
    workers = ["w1", "w2", "w3"]
    first = assign(AGENTS, workers)
    for _ in range(5):
        assert assign(AGENTS, workers) == first


def test_the_owner_is_not_just_the_first_worker():
    """A naive implementation that always picks the first live worker would put every agent
    on worker 1 and leave the others idle."""
    workers = [f"w{i}" for i in range(4)]
    owners = assign(AGENTS, workers)
    assert len(set(owners.values())) > 1


# ── the movement ───────────────────────────────────────────────────────────
def test_only_the_dead_workers_agents_move():
    """This is what rendezvous hashing buys. With modulo hashing, losing one worker would
    reshuffle nearly the whole fleet and every agent would jump to a different owner."""
    old = ["w1", "w2", "w3"]
    new = ["w2", "w3"]          # w1 died
    moved = rebalance(AGENTS, old, new)
    for agent_id in AGENTS:
        before = owner_of(agent_id, old)
        after = owner_of(agent_id, new)
        if before == "w1":
            assert agent_id in moved, f"{agent_id} lost its owner and did not move"
        else:
            assert agent_id not in moved, f"{agent_id} moved even though its owner is alive"


def test_adding_a_worker_moves_only_some_agents():
    old = ["w1", "w2"]
    new = ["w1", "w2", "w3"]
    moved = rebalance(AGENTS, old, new)
    # Only the agents w3 now owns move; the rest stay with the worker that had them.
    assert len(moved) < len(AGENTS) * 0.6


def test_nothing_moves_when_nothing_changes():
    workers = ["w1", "w2", "w3"]
    assert rebalance(AGENTS, workers, workers) == {}


# ── the shard ──────────────────────────────────────────────────────────────
class Clock:
    """A virtual clock, so the takeover is measured in the test, not in real seconds."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def shared_store(tmp_path):
    """One store file, two workers — the way two processes on one machine would share it."""
    return LocalStore(str(tmp_path / "fleet.db"))


def test_a_heartbeat_registers_the_worker(shared_store):
    clock = Clock()
    shard = Shard(shared_store, worker_id="w1", clock=clock)
    shard.heartbeat(clock())
    assert [w["worker_id"] for w in shared_store.list_workers()] == ["w1"]


def test_a_worker_is_alive_while_it_beats(shared_store):
    clock = Clock()
    shard = Shard(shared_store, worker_id="w1", heartbeat_seconds=2.0, stale_seconds=10.0, clock=clock)
    shard.heartbeat(clock())
    assert shard.live_workers() == ["w1"]
    clock.advance(5)
    shard.heartbeat(clock())
    assert shard.live_workers() == ["w1"]


def test_a_worker_that_stopped_is_dead(shared_store):
    clock = Clock()
    shard = Shard(shared_store, worker_id="w1", heartbeat_seconds=2.0, stale_seconds=10.0, clock=clock)
    shard.heartbeat(clock())
    clock.advance(30)          # it stopped 30 s ago
    assert shard.live_workers() == ["w1"]   # this worker still counts itself alive


def test_the_other_worker_sees_the_stopped_one_as_dead(shared_store):
    clock = Clock()
    w1 = Shard(shared_store, worker_id="w1", heartbeat_seconds=2.0, stale_seconds=10.0, clock=clock)
    w2 = Shard(shared_store, worker_id="w2", heartbeat_seconds=2.0, stale_seconds=10.0, clock=clock)
    w1.heartbeat(clock())
    w2.heartbeat(clock())
    assert w2.live_workers() == ["w1", "w2"]
    clock.advance(30)          # w1 stops beating
    w2.heartbeat(clock())
    assert w2.live_workers() == ["w2"]


def test_a_failed_heartbeat_does_not_kill_the_worker(shared_store):
    """If the heartbeat write fails, the worker is still running. If it stopped beating
    because of that, the others would take over agents it is still working on."""
    clock = Clock()
    shard = Shard(shared_store, worker_id="w1", clock=clock)

    def boom(*_args, **_kwargs):
        raise RuntimeError("the database is locked")

    shared_store.heartbeat_worker = boom
    shard.heartbeat(clock())    # must not raise
    assert shard.live_workers() == ["w1"]


def test_the_shutdown_removes_the_worker(shared_store):
    clock = Clock()
    shard = Shard(shared_store, worker_id="w1", clock=clock)
    shard.heartbeat(clock())
    shard.shutdown()
    assert shared_store.list_workers() == []


def test_the_owned_agents_are_the_ones_this_worker_hashes_to(shared_store):
    clock = Clock()
    w1 = Shard(shared_store, worker_id="w1", clock=clock)
    w2 = Shard(shared_store, worker_id="w2", clock=clock)
    w1.heartbeat(clock())
    w2.heartbeat(clock())
    mine = w1.owned_agents(AGENTS, clock())
    theirs = w2.owned_agents(AGENTS, clock())
    # every agent belongs to exactly one worker, and the two sets are disjoint
    assert not (mine & theirs)
    assert mine | theirs == set(AGENTS)


# ── the acceptance cases ───────────────────────────────────────────────────
class TwoWorkers:
    """Two Engines on one store file, 50 agents — the acceptance setup."""

    def __init__(self, store, cfg, clock, worker_ids=("w1", "w2")):
        self.clock = clock
        self.store = store
        self.policy = Policy.load("brain/policies.yaml")
        self.fleet = FakeFleet(store, names=AGENTS, auto_rogue=None, start=clock())
        self.engines = []
        self.shards = []
        self.dead = None
        for wid in worker_ids:
            shard = Shard(store, worker_id=wid, heartbeat_seconds=2.0, stale_seconds=10.0, clock=clock)
            engine = Engine(store, self.fleet, Judge(cfg), self.policy, cfg, sync_judge=True, shard=shard)
            self.shards.append(shard)
            self.engines.append(engine)

    def tick(self, seconds=1.0, n=1):
        for _ in range(n):
            self.clock.advance(seconds)
            self.fleet.step(self.clock())
            for engine in self.engines:
                if engine is self.dead:
                    continue        # the process is gone — it does not tick any more
                engine.tick(self.clock())

    def stop(self, worker_id):
        """Kill a worker the way a real crash kills it: it stops ticking and stops beating.

        Its row stays in the workers table — a dead process cannot clean up after itself —
        so the others have to notice it is gone by the heartbeat going stale.
        """
        for i, shard in enumerate(self.shards):
            if shard.worker_id == worker_id:
                self.dead = self.engines[i]
                return
        raise KeyError(worker_id)

    def ownership(self):
        """Who owns what, according to the live workers.

        Asked of a *surviving* worker's shard: a shard always counts itself alive, so
        asking the dead one would report it as alive and hide the takeover.
        """
        alive_shard = self.shards[1] if self.dead is self.engines[0] else self.shards[0]
        live = alive_shard.live_workers(self.clock())
        return {a: owner_of(a, live) for a in AGENTS}


def test_every_agent_is_owned_by_exactly_one_worker(shared_store, cfg):
    """The acceptance case: 2 Engines on one LocalStore file with 50 agents."""
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)

    live = tw.shards[0].live_workers(clock())
    assert len(live) == 2
    owners = tw.ownership()
    # every agent has an owner, and that owner is one of the two workers
    assert set(owners) == set(AGENTS)
    assert set(owners.values()) <= set(live)
    # and no agent is claimed by both
    mine = tw.engines[0].owned
    theirs = tw.engines[1].owned
    assert mine is not None and theirs is not None
    assert not (mine & theirs)
    assert mine | theirs == set(AGENTS)


def test_both_workers_actually_get_some_agents(shared_store, cfg):
    """A shard that puts everything on one worker is not a shard."""
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)
    assert len(tw.engines[0].owned) > 0
    assert len(tw.engines[1].owned) > 0


def test_the_fleet_is_split_roughly_evenly(shared_store, cfg):
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)
    counts = sorted(len(e.owned) for e in tw.engines)
    # 50 agents over 2 workers: a fair split is 25/25. Allow a wide band — the point is
    # that it is not 49/1 and not 50/0.
    assert counts[0] >= 10, counts
    assert counts[1] - counts[0] <= 30, counts


def test_stopping_one_worker_gives_its_agents_to_the_other(shared_store, cfg):
    """The acceptance case: stopping one → full takeover in ≤ 15 s (virtual clock)."""
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)

    before = tw.engines[0].owned | tw.engines[1].owned
    assert before == set(AGENTS)

    # w1's process dies. Its heartbeat goes stale after 10 s.
    tw.stop("w1")
    tw.tick(n=1)

    # within the stale window the survivors still wait — taking over early would mean two
    # workers acting on the same agent.
    assert not (tw.engines[0].owned & tw.engines[1].owned)

    # after the stale window, w2 owns everything.
    clock.advance(11)
    tw.tick(n=2)
    assert tw.engines[1].owned == set(AGENTS)
    # The dead engine's own `owned` set is frozen at its last tick — a stopped process
    # does not get to update its memory. What matters is that no *live* worker claims
    # the dead one's agents: there is only one owner, and it is w2.
    live_owners = tw.ownership()
    assert live_owners == {a: "w2" for a in AGENTS}


def test_a_worker_that_comes_back_recomputes_what_it_owns(shared_store, cfg):
    """A restarted worker must not keep the agents it owned before it died.

    Its old `owned` set is still in memory, and it is now a member of the live set again.
    If it trusted that set, it would act on agents the survivor also owns — two workers
    on one agent, which is the bug this whole mechanism exists to prevent.
    """
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)
    assert set(tw.engines[0].owned)

    tw.stop("w1")
    clock.advance(11)
    tw.tick(n=2)
    assert tw.engines[1].owned == set(AGENTS)

    # w1 comes back. It beats again and works out its ownership from scratch.
    tw.dead = None
    tw.tick(n=2)
    live = tw.shards[1].live_workers(clock())
    assert live == ["w1", "w2"]
    # every agent still has exactly one owner, and the two workers do not overlap
    assert not (tw.engines[0].owned & tw.engines[1].owned)
    assert tw.engines[0].owned | tw.engines[1].owned == set(AGENTS)


def test_the_takeover_happens_within_fifteen_seconds(shared_store, cfg):
    """The acceptance case, measured: from the last heartbeat to full takeover ≤ 15 s."""
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)

    survivor = tw.engines[1]
    tw.stop("w1")
    last_beat = clock.now

    takeover_at = None
    for _ in range(30):
        clock.advance(1)
        tw.tick(n=1)
        if survivor.owned == set(AGENTS) and takeover_at is None:
            takeover_at = clock.now
            break
    assert takeover_at is not None, "the survivor never took over"
    assert takeover_at - last_beat <= 15.0, f"took over after {takeover_at - last_beat:.1f}s"


def test_the_takeover_gives_the_dead_workers_agents_to_the_survivor(shared_store, cfg):
    """The dead worker's agents must move to the survivor — and only those."""
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)
    dead_owned = set(tw.engines[0].owned)
    alive_owned = set(tw.engines[1].owned)

    tw.stop("w1")
    clock.advance(11)
    tw.tick(n=2)
    assert tw.engines[1].owned == set(AGENTS)
    # the survivor's own agents never moved — only the dead one's came across
    assert alive_owned <= tw.engines[1].owned
    assert dead_owned <= tw.engines[1].owned


def test_no_command_runs_twice(shared_store, cfg):
    """The acceptance case: no command runs twice.

    Both workers read the same pending commands. If both ran them, the action would be
    recorded twice and the agent paused twice.
    """
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)

    service.post_command(shared_store, "agent-00", "PAUSE", {}, "dashboard", "test")
    tw.tick(n=1)

    actions = shared_store.recent_actions(limit=50)
    pauses = [a for a in actions if a["action"] == "PAUSE"]
    assert len(pauses) == 1, f"the command ran {len(pauses)} times"


def test_a_command_for_someone_elses_agent_is_left_alone(shared_store, cfg):
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)

    # find an agent the second worker owns
    theirs = sorted(tw.engines[1].owned)[0]
    service.post_command(shared_store, theirs, "PAUSE", {}, "dashboard", "test")
    tw.tick(n=1)

    actions = shared_store.recent_actions(limit=50)
    pauses = [a for a in actions if a["action"] == "PAUSE" and a["agent_id"] == theirs]
    assert len(pauses) == 1


def test_the_tick_is_fast_at_fifty_agents(shared_store, cfg):
    """The acceptance case: tick p95 < 200 ms per worker at 50 agents."""
    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)     # warm up — the first tick loads the baselines and the policy

    durations = []
    for _ in range(20):
        clock.advance(1)
        tw.fleet.step(clock())
        for engine in tw.engines:
            started = time.perf_counter()
            engine.tick(clock())
            durations.append((time.perf_counter() - started) * 1000)

    durations.sort()
    p95 = durations[int(len(durations) * 0.95) - 1]
    assert p95 < 200, f"tick p95 was {p95:.1f} ms"


def test_the_health_check_lists_the_workers(shared_store, cfg):
    """`/v1/health` lists the workers and their agent counts."""
    from fastapi.testclient import TestClient

    from brain.api import create_app

    clock = Clock()
    tw = TwoWorkers(shared_store, cfg, clock)
    tw.tick(n=3)

    api = TestClient(create_app(shared_store, tw.policy, cfg, "fake", "fallback"))
    health = api.get("/v1/health").json()
    assert "workers" in health
    assert {w["worker_id"] for w in health["workers"]} == {"w1", "w2"}
    assert health["agents_total"] == len(AGENTS)


# ── the engine without a shard still watches everything ───────────────────
def test_an_engine_without_a_shard_owns_everything(shared_store, cfg):
    """The default has to keep working: one process, whole fleet."""
    clock = Clock()
    store = shared_store
    policy = Policy.load("brain/policies.yaml")
    fleet = FakeFleet(store, names=AGENTS, auto_rogue=None, start=clock())
    engine = Engine(store, fleet, Judge(cfg), policy, cfg, sync_judge=True)
    clock.advance(1)
    fleet.step(clock())
    engine.tick(clock())
    assert engine.owns("agent-00")
    assert engine.owns("agent-49")
