"""
Send a command to the sentinel from the terminal (same path the dashboard uses).

    python scripts/command.py rogue beta     # make agent "beta" go rogue (demo trigger)
    python scripts/command.py kill beta      # emergency kill "beta"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.contracts import CommandRow
from shared.store import get_store

COMMANDS = {"rogue": "GO_ROGUE", "kill": "KILL"}

if len(sys.argv) != 3 or sys.argv[1] not in COMMANDS:
    print(__doc__)
    sys.exit(1)

action, agent = sys.argv[1], sys.argv[2]
get_store().insert_command(CommandRow(agent, COMMANDS[action], "terminal", f"{action} from terminal"))
print(f"Sent {COMMANDS[action]} → {agent}. The sentinel will run it within ~1 second.")
