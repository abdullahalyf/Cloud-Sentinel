from brain.breaker import Breaker
from brain.detectors import Finding, Level


def f(level):
    x = Finding()
    if level:
        x.add(level, "rule", "reason")
    return x


def test_soft_finding_asks_judge_then_confident_verdict_pauses():
    b = Breaker("a")
    effect, ask = b.on_finding(f(Level.SUSPICIOUS), 0)
    assert effect is None and ask and b.state == "suspicious"
    e = b.on_verdict("KILL", 0.9, "claude", "loop")
    assert e.action == "PAUSE" and b.state == "paused"  # on_trip=pause by default


def test_on_trip_kill_policy():
    b = Breaker("a", on_trip="kill")
    b.on_finding(f(Level.SUSPICIOUS), 0)
    assert b.on_verdict("KILL", 0.9, "claude", "x").action == "KILL"


def test_low_confidence_warns_once():
    b = Breaker("a")
    b.on_finding(f(Level.SUSPICIOUS), 0)
    assert b.on_verdict("PAUSE", 0.3, "claude", "unsure").action == "WARN"
    assert b.on_verdict("WARN", 0.5, "claude", "still unsure") is None and b.state == "suspicious"


def test_ignore_returns_to_healthy_and_quiet_period_clears():
    b = Breaker("a")
    b.on_finding(f(Level.SUSPICIOUS), 0)
    b.on_verdict("IGNORE", 0.9, "claude", "legit")
    assert b.state == "healthy"
    b.on_finding(f(Level.SUSPICIOUS), 10)
    b.on_finding(f(Level.OK), 45)
    assert b.state == "healthy"


def test_hard_limit_kills_immediately():
    b = Breaker("a")
    effect, _ = b.on_finding(f(Level.CRITICAL), 0)
    assert effect.action == "KILL" and effect.actor == "rules" and b.state == "killed"
    assert b.on_finding(f(Level.CRITICAL), 1) == (None, False)


def test_resume_probation_then_healthy_or_killed():
    b = Breaker("a", probation_seconds=30)
    b.on_command("PAUSE", "human", "", 0)
    assert b.on_command("RESUME", "human", "", 0).action == "RESUME" and b.state == "probation"
    b.on_finding(f(Level.OK), 31)
    assert b.state == "healthy"
    b.on_command("PAUSE", "human", "", 40)
    b.on_command("RESUME", "human", "", 40)
    effect, _ = b.on_finding(f(Level.SUSPICIOUS), 41)
    assert effect.action == "KILL" and b.state == "killed"


def test_resume_when_not_paused_is_noop_and_restart_only_when_killed():
    b = Breaker("a")
    assert b.on_command("RESUME", "human", "", 0) is None
    assert b.on_command("RESTART", "human", "", 0) is None
    b.on_command("KILL", "mcp", "", 0)
    assert b.on_command("RESTART", "human", "", 0).action == "RESTART" and b.state == "probation"


def test_runtime_status_sync():
    b = Breaker("a")
    b.on_runtime_status("exited")
    assert b.state == "killed"
