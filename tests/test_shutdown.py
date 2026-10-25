"""Ctrl+C stops the sentinel cleanly with a summary, and logs go to LOG_FILE."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from tests.test_engine import make

ROOT = Path(__file__).resolve().parent.parent


def test_ctrl_c_in_the_loop_shuts_down_and_summarises(tmp_path, monkeypatch, caplog):
    s, source, store = make(tmp_path, None)
    h = {x.name: x for x in source.list_agents()}
    s.tick()
    s.kill(h["beta"], actor="human", reason="test")

    def interrupt(now=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(s, "tick", interrupt)
    caplog.set_level("INFO")
    s.run_forever()                                   # returns instead of raising
    assert s.pool._shutdown
    assert "watched 3 agent(s) (alpha, beta, gamma), 1 kill(s)" in caplog.text


def test_sigint_on_the_real_process(tmp_path):
    log_file = tmp_path / "logs" / "sentinel.log"
    env = {**os.environ, "ANTHROPIC_API_KEY": "", "SUPABASE_URL": "", "SUPABASE_KEY": "",
           "WEBHOOK_URL": "", "LOCAL_DB_PATH": str(tmp_path / "t.db"), "LOG_FILE": str(log_file)}
    child = subprocess.Popen([sys.executable, "-m", "sentinel", "--fake", "--no-auto-rogue"],
                             cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(3)
    child.send_signal(signal.SIGINT)
    out, _ = child.communicate(timeout=15)
    assert child.returncode == 0, out
    assert "Traceback" not in out
    assert "Summary: watched 3 agent(s)" in out and "Sentinel stopped." in out
    text = log_file.read_text()
    assert "Now watching alpha" in text and "Summary:" in text
