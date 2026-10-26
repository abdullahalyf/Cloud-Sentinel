"""Fojle's real agents/agent.py as subprocesses (no Docker): every ROGUE_TYPE dies, healthy agents live."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("verify_agents", ROOT / "scripts" / "verify_agents.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc for memory")
def test_all_four_rogue_types_are_killed_and_healthy_agents_survive():
    result = verify.run(timeout=70)
    rows = result["rows"]
    assert result["healthy_survived"], verify.table(result)
    for rogue_type, row in rows.items():
        assert row["killed_after"] is not None, (rogue_type, verify.table(result))
    assert rows["paraphrase_loop"]["flagged_after"] <= 10          # was 23s
    assert rows["token_bomb"]["killed_by"] == "rules"              # hard limit, no AI
    assert {"memory_high", "memory_hard"} & set(rows["memory_leak"]["rules"])   # caught by memory…
    assert "call_spike" not in rows["memory_leak"]["rules"]        # …not by call rate
