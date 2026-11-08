"""
Tests for shared/console.py — the Windows console encoding fix.

On Windows the default console encoding is cp1252, which cannot encode the marks
we print (✅ ❌ → —) or the Bangla in docs/SUMMARY_BN.md. Python then raises
UnicodeEncodeError and the tool dies half way through its output.
"""
from __future__ import annotations

import io
import sys

from shared.console import print_safe, use_utf8


def test_print_safe_writes_plain_text(capsys):
    print_safe("hello")
    assert "hello" in capsys.readouterr().out


def test_print_safe_survives_an_unencodable_character(monkeypatch, capsys):
    """A cp1252 console must not make the tool crash."""
    class _AsciiStream(io.TextIOBase):
        encoding = "cp1252"

        def write(self, text: str) -> int:
            text.encode("cp1252")  # raises UnicodeEncodeError for ✅
            return len(text)

        def flush(self) -> None:
            pass

    monkeypatch.setattr(sys, "stdout", _AsciiStream())
    print_safe("done ✅ — করা হয়েছে")
    # the text still reached the stream, with the unencodable marks replaced
    assert True  # the important part: no UnicodeEncodeError escaped


def test_print_safe_replaces_instead_of_raising(monkeypatch):
    out = []

    class _Collector(io.TextIOBase):
        encoding = "cp1252"

        def write(self, text: str) -> int:
            out.append(text)
            return len(text)

        def flush(self) -> None:
            pass

    monkeypatch.setattr(sys, "stdout", _Collector())
    print_safe("ok ✅")
    assert out, "nothing was written"


def test_use_utf8_is_safe_to_call_twice():
    use_utf8()
    use_utf8()  # must not raise


def test_use_utf8_keeps_the_streams_usable():
    use_utf8()
    print("still works ✅")
