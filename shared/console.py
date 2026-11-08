"""
Console helpers that work on Windows too.   Owner: Alif (shared/).

Windows consoles default to cp1252, which cannot encode the characters we print
(the ✅/❌/→/— marks in the eval tables, the Bangla in docs/SUMMARY_BN.md). Python
raises UnicodeEncodeError and the tool dies half way through its output.

`use_utf8()` switches the stdout/stderr streams to UTF-8 with replacement, so a
tool never crashes because of a mark it could not encode.
"""
from __future__ import annotations

import sys


def use_utf8() -> None:
    """Make stdout/stderr able to print any character. Safe to call more than once."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # a stream that was already closed or replaced
            pass


def print_safe(text: str = "") -> None:
    """print() that never dies on a character the console cannot encode."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
        sys.stdout.write("\n")
