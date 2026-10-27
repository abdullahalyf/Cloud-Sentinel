"""Offline rehearsal integration tests; included in python -m pytest -q."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_offline_demo_timeline_and_database_isolation(tmp_path):
    existing_db = tmp_path / 'existing.db'
    existing_db.write_bytes(b'do not touch this database')
    environment = {**os.environ, 'ANTHROPIC_API_KEY': 'unused-test-key',
                   'SUPABASE_URL': 'https://invalid.example', 'SUPABASE_KEY': 'unused-test-key',
                   'LOCAL_DB_PATH': str(existing_db), 'DRY_RUN': 'true'}
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/demo.py')],
                            cwd=tmp_path, env=environment, text=True, encoding="utf-8", capture_output=True, timeout=75)
    assert result.returncode == 0, result.stderr
    match = re.fullmatch(r'rogue at ([\d.]+)s \u2192 flagged at ([\d.]+)s \u2192 '
                         r'killed at ([\d.]+)s by (fallback|rules)\r?\n', result.stdout)
    assert match, result.stdout
    rogue, flagged, killed = map(float, match.groups()[:3])
    assert 10 <= rogue < 12
    assert rogue <= flagged <= killed < 60
    assert existing_db.read_bytes() == b'do not touch this database'


def test_demo_timeout_returns_failure():
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/demo.py'), '--timeout', '0.1'],
                            cwd=ROOT, text=True, capture_output=True, timeout=10)
    assert result.returncode == 1
    assert 'timed out' in result.stderr
    assert 'killed at' not in result.stdout


def test_demo_all_runs_every_rogue_type_and_healthy_agents_survive(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/demo.py'), '--all'],
                            cwd=tmp_path, text=True, capture_output=True, timeout=170)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = {}
    for line in result.stdout.splitlines():
        cells = [c.strip() for c in line.split('|')]
        if cells[0] in ('loop', 'token_bomb', 'memory_leak', 'paraphrase_loop'):
            rows[cells[0]] = cells
    assert set(rows) == {'loop', 'token_bomb', 'memory_leak', 'paraphrase_loop'}, result.stdout
    for cells in rows.values():
        assert float(cells[1].rstrip('s')) <= float(cells[2].rstrip('s')) <= 15
        assert cells[3] in ('rules', 'fallback') and cells[4] == 'yes'
    assert result.stdout.rstrip().endswith('PASS')


def test_demo_all_cannot_be_combined_with_docker():
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/demo.py'), '--all', '--docker'],
                            cwd=ROOT, text=True, capture_output=True, timeout=20)
    assert result.returncode == 2 and 'fake mode' in result.stderr
