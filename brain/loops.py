"""
Loop detectors that need NO LLM call (ARCHITECTURE §5, layers L3–L5). Pure functions → easy to test.

  semantic_loop_score(prompts)  0..1  share of recent prompts that say "the same thing" in different words
  tool_cycle(tool_names)        True  if the recent tool calls repeat a short pattern (A,A,A… or A,B,A,B…)
  injection_hits(prompts)       int   prompts that talk to the monitor ("do not terminate", …)
"""
from __future__ import annotations

import re

_STOP = {"a", "an", "the", "and", "or", "to", "of", "for", "from", "on", "in", "is", "it", "its", "me",
         "please", "then", "and", "what", "where", "if", "has", "yet", "once", "more", "again", "still",
         "need", "try", "tell", "find", "out", "see", "with", "this", "that", "be", "you", "i", "short",
         "answer", "report", "back", "result", "summarize", "up", "job"}
# very small synonym map: paraphrase loops reuse a handful of verbs
_SYN = {"get": "fetch", "retrieve": "fetch", "pull": "fetch", "query": "fetch", "request": "fetch",
        "look": "fetch", "check": "fetch", "lookup": "fetch", "re": "", "recheck": "fetch",
        "state": "status", "stands": "status", "info": "status", "details": "status", "shipped": "status",
        "latest": "current", "retry": ""}
_INJECTION = re.compile(r"(monitor(ing)? system|do not (terminate|kill|stop)|ignore (all|previous) "
                        r"instructions|you are (now )?(the )?(judge|monitor)|system override)", re.I)


def tokens(text: str) -> frozenset[str]:
    """Normalize a prompt to a set of meaningful words (numbers kept: '#4471' → '4471')."""
    words = re.findall(r"[a-z]+|\d+", text.lower())
    out = set()
    for w in words:
        w = _SYN.get(w, w)
        if w and w not in _STOP and not (w.isdigit() and len(w) < 3):
            out.add(w)
    return frozenset(out)


MIN_ID_DIGITS = 4   # order/ticket ids (4471). Shorter numbers (amounts like "300 BDT") don't decide "different work"


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """
    Jaccard similarity of two word sets. Prompts about DIFFERENT ids (order 1234 vs order 5678)
    are different work, not a loop — so if both mention ids and share none, similarity is 0.
    """
    if not a or not b:
        return 0.0
    ids_a = {w for w in a if w.isdigit() and len(w) >= MIN_ID_DIGITS}
    ids_b = {w for w in b if w.isdigit() and len(w) >= MIN_ID_DIGITS}
    if ids_a and ids_b and not ids_a & ids_b:
        return 0.0
    return len(a & b) / len(a | b)


def semantic_loop_score(prompts: list[str], min_prompts: int = 6, threshold: float = 0.4,
                        window: int = 16) -> float:
    """
    Greedy clustering of the last `window` prompts: two prompts are "the same intent" when their
    word sets have Jaccard ≥ threshold. Score = size of the biggest cluster / number of prompts.
    Healthy agents doing varied work score low (< 0.4); a paraphrase loop scores high (> 0.7).
    """
    recent = [tokens(p) for p in prompts[-window:] if p]
    if len(recent) < min_prompts:
        return 0.0
    clusters: list[list[frozenset[str]]] = []
    for t in recent:
        for c in clusters:
            if similarity(t, c[0]) >= threshold:
                c.append(t)
                break
        else:
            clusters.append([t])
    return round(max(len(c) for c in clusters) / len(recent), 2)


def tool_cycle(tool_names: list[str], min_repeats: int = 4, max_period: int = 3) -> bool:
    """True if the last calls are one short pattern repeated ≥ min_repeats times."""
    for period in range(1, max_period + 1):
        need = period * min_repeats
        if len(tool_names) < need:
            continue
        tail = tool_names[-need:]
        pattern = tail[:period]
        if all(tail[i] == pattern[i % period] for i in range(need)):
            return True
    return False


def injection_hits(prompts: list[str]) -> int:
    """
    How many of the recent prompts carry an injection.

    Since A6 this is the real scorer (brain/injection.py), not the small denylist this used to
    be — the denylist missed "ignore all previous instructions" and every Bangla phrasing.
    """
    from brain.injection import FINDING_SCORE, score_text

    return sum(1 for p in prompts if p and score_text(p).score >= FINDING_SCORE)
