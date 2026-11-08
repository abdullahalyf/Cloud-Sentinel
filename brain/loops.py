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


class IncrementalLoopScore:
    """
    The loop score, computed only for the prompts that are new (A11).

    **Why.** The plain `semantic_loop_score` re-tokenizes and re-clusters all 16 recent
    prompts on every tick, for every agent. At 100 agents that is 1600 tokenizations and
    1600 Jaccard comparisons per tick, and the profile said the regex work was the
    single biggest thing left in the tick after the write batching. But the window
    slides by one prompt at a time: 15 of the 16 word sets are *exactly the same* as
    they were last tick. Recomputing them is work whose answer is already known.

    **How.** A cluster holds the *prompts* that joined it, in order, and each prompt's
    word set is cached. When the window slides forward, the prompts that left the
    window are removed from their clusters and only the new prompt is compared against
    the clusters that are still standing.

    **The one thing it must not get wrong.** The score is what the detectors act on, so
    it has to be the *same number* the plain scorer gives. The greedy clustering is
    order-dependent — a prompt joins the *first* cluster it matches — which means a
    prompt that joined a cluster that has since left the window must be re-placed. So
    the fast path only runs when the new window is a *suffix-extension* of the old one
    (the common case: the window slides forward, or grows), and anything else falls
    back to recomputing from scratch. `brain/tests/test_perf.py` checks that the two
    agree, prompt for prompt.
    """

    def __init__(self, min_prompts: int = 6, threshold: float = 0.4, window: int = 16):
        self.min_prompts = min_prompts
        self.threshold = threshold
        self.window = window
        self._tokens: dict[str, frozenset[str]] = {}       # prompt → its word set
        self._clusters: list[list[str]] = []                # cluster → the prompts in it
        self._last: tuple[str, ...] = ()                    # the window last scored

    def _tokenize(self, prompt: str) -> frozenset[str]:
        """The word set of a prompt, cached by the prompt itself."""
        hit = self._tokens.get(prompt)
        if hit is None:
            hit = tokens(prompt)
            self._tokens[prompt] = hit
        return hit

    def score(self, prompts: list[str]) -> float:
        """The loop score for the current window."""
        recent = tuple(p for p in prompts[-self.window:] if p)

        if len(recent) < self.min_prompts:
            self._reset()
            return 0.0

        if not self._can_extend(recent):
            # The window changed in a way the fast path does not model (prompts were
            # edited, reordered, or the window jumped backwards). Recompute from
            # scratch — it is rare, and correctness matters more than speed here.
            return self._recompute(recent)

        self._extend(recent)
        if not self._clusters:
            return 0.0
        return round(max(len(c) for c in self._clusters) / len(recent), 2)

    # ── the fast path ────────────────────────────────────────────────────────
    def _can_extend(self, recent: tuple[str, ...]) -> bool:
        """Can the new window be reached from the old one by adding to its end?

        Only then is the clustering unchanged for the prompts already placed: a
        prompt joins the first cluster it matches, and the clusters before it have
        not changed.
        """
        old = self._last
        if not old:
            return True
        return len(recent) >= len(old) and recent[:len(old)] == old

    def _extend(self, recent: tuple[str, ...]) -> None:
        """Place the prompts that are new since the last call."""
        added = recent[len(self._last):]
        for prompt in added:
            t = self._tokenize(prompt)
            for c in self._clusters:
                if similarity(t, self._tokenize(c[0])) >= self.threshold:
                    c.append(prompt)
                    break
            else:
                self._clusters.append([prompt])
        self._last = recent

    # ── the slow path ────────────────────────────────────────────────────────
    def _recompute(self, recent: tuple[str, ...]) -> float:
        """The plain scorer, and the clusters are rebuilt from it."""
        self._clusters = []
        for prompt in recent:
            t = self._tokenize(prompt)
            for c in self._clusters:
                if similarity(t, self._tokenize(c[0])) >= self.threshold:
                    c.append(prompt)
                    break
            else:
                self._clusters.append([prompt])
        self._last = recent
        return round(max(len(c) for c in self._clusters) / len(recent), 2)

    def _reset(self) -> None:
        self._clusters = []
        self._last = ()



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
