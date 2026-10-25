"""
CloudSentinel core engine (owner: Alif).

Pipeline, once per tick (~1 second):

    sources.py   → which agents exist, their log events, memory, kill()
    collector.py → turns raw events into numbers (tokens/min, calls/sec, loops)
    detector.py  → fast rules: OK / SUSPICIOUS / CRITICAL
    brain.py     → Claude judges SUSPICIOUS agents (KILL / WARN / IGNORE)
    engine.py    → glues it together, executes kills, writes to the database
"""
