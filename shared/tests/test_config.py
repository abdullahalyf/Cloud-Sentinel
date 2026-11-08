"""
Tests for shared/config.py — the env parsing.

The bug these cover: `.env.example` writes `CS_API_TOKEN=                    # set to
require header X-CS-Token on the C2 API`. python-dotenv keeps that comment as the
VALUE, so an unset setting silently becomes the comment text. `CS_API_TOKEN` then
demanded a header equal to "# set to require header X-CS-Token on the C2 API",
which locked out every legitimate client — the whole API returned 401.
"""
from __future__ import annotations

import pytest

from shared.config import _bool, _float, _int, _strip_comment


# ── the comment stripper ───────────────────────────────────────────────────
def test_an_empty_value_with_a_comment_becomes_empty():
    assert _strip_comment("# set to require header X-CS-Token on the C2 API") == ""


def test_a_value_with_a_trailing_comment_keeps_the_value():
    assert _strip_comment("auto              # auto | claude | gemini | fallback") == "auto"


def test_a_value_without_a_comment_is_untouched():
    assert _strip_comment("http://localhost:8000") == "http://localhost:8000"


def test_a_hash_inside_a_value_survives():
    """`abc#def` is a value, not a value plus a comment."""
    assert _strip_comment("abc#def") == "abc#def"


def test_a_hash_after_whitespace_is_a_comment():
    assert _strip_comment("abc # def") == "abc"


# ── the typed getters ──────────────────────────────────────────────────────
def test_str_drops_an_inline_comment(monkeypatch):
    monkeypatch.setenv("CS_TEST_STR", "value   # a comment")
    assert _str_value("CS_TEST_STR") == "value"


def test_int_drops_an_inline_comment(monkeypatch):
    monkeypatch.setenv("CS_TEST_INT", "42   # a comment")
    assert _int("CS_TEST_INT", 0) == 42


def test_int_falls_back_when_the_value_is_garbage(monkeypatch):
    monkeypatch.setenv("CS_TEST_INT", "not a number")
    assert _int("CS_TEST_INT", 7) == 7


def test_float_drops_an_inline_comment(monkeypatch):
    monkeypatch.setenv("CS_TEST_FLOAT", "0.6   # a comment")
    assert _float("CS_TEST_FLOAT", 0.0) == 0.6


def test_bool_drops_an_inline_comment(monkeypatch):
    monkeypatch.setenv("CS_TEST_BOOL", "true   # a comment")
    assert _bool("CS_TEST_BOOL", False) is True


def test_bool_reads_the_usual_spellings(monkeypatch):
    for raw, want in (("1", True), ("yes", True), ("on", True), ("true", True),
                      ("0", False), ("no", False), ("off", False), ("false", False)):
        monkeypatch.setenv("CS_TEST_BOOL", raw)
        assert _bool("CS_TEST_BOOL", not want) is want


def _str_value(name: str) -> str:
    from shared.config import _str

    return _str(name)
