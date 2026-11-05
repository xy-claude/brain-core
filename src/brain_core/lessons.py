"""UserPromptSubmit hook: put the one or two past corrections that match the prompt in front
of the agent before it answers.

The brief carries the last two weeks of corrections and a theme becomes a rule after three;
an older correction that never became a rule is on disk but never in context. This matches
the prompt against corrections.md by words alone (no model, no network, no index), so it is
cheap enough to run on every prompt, and it prefers silence to a weak match.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from brain_core import traits
from brain_core.recall import tokens

MAX_LESSONS = 2
MIN_SHARED = 2  # distinct words a prompt and a correction must have in common
MIN_SCORE = 0.15  # tf-idf cosine; set on a small corpus, re-tune from the lessons_injected log
PROMPT_CHARS = 4_000
RULE_CHARS = 300
_FIELDS = ("error", "correction", "implied rule", "rule", "lesson")
# words that say nothing about the subject; without this "what does it do" matches anything
_FUNCTION = frozenset(
    """what which who whom whose when where why how do does doe did done doing is are was were
    be been being am have has had having i you he she it we they me my your our their this that
    these those there here if then than so not no yes can could will would should shall may
    might must to of in on at by for with from into about as or but before after again also
    just very more most some any all each other up down out over under get got make made let
    want need know think say said tell ask see look use used using one two thing way time
    please okay ok""".split()  # noqa: SIM905 (a word per line would run to a hundred lines)
)


def lessons(corrections: str, prompt: str) -> list[dict[str, Any]]:
    """The corrections in `corrections` (the text of corrections.md) that match `prompt`,
    best first, at most MAX_LESSONS. Empty when nothing clears both thresholds."""
    items = traits._corrections(corrections)
    asked = _words(prompt[:PROMPT_CHARS])
    if not items or not asked:
        return []
    docs = [_words(" ".join([title, *(f.get(k, "") for k in _FIELDS)])) for _d, title, f in items]
    seen = Counter(w for doc in docs for w in doc)

    def weight(word: str) -> float:
        # a word no correction uses still counts against the prompt, so a long prompt about
        # something else scores low instead of matching on a few stray words
        return math.log(1 + len(docs) / seen.get(word, 0.5))

    def norm(words: set[str]) -> float:
        return math.sqrt(sum(weight(w) ** 2 for w in words))

    out: list[dict[str, Any]] = []
    for (when, title, fields), doc in zip(items, docs, strict=True):
        shared = asked & doc
        # tokens() puts a naive singular beside every plural; count the pair once
        distinct = sorted(w for w in shared if w + "s" not in shared)
        if len(distinct) < MIN_SHARED:
            continue
        score = sum(weight(w) ** 2 for w in shared) / (norm(asked) * norm(doc))
        if score < MIN_SCORE:
            continue
        rule = next(
            (fields[k] for k in ("implied rule", "rule", "correction") if fields.get(k)), ""
        )
        out.append(
            {
                "date": when.isoformat(),
                "title": title,
                "rule": rule[:RULE_CHARS],
                "score": round(score, 3),
                "shared": distinct,
            }
        )
    out.sort(key=lambda h: h["score"], reverse=True)
    return out[:MAX_LESSONS]


def render(hits: list[dict[str, Any]]) -> str:
    lines = ["Past corrections that match this request (brain-core); apply them:"]
    lines += [
        f"- [{h['date']}] {h['title']}" + (f": {h['rule']}" if h["rule"] else "") for h in hits
    ]
    return "\n".join(lines)


def _words(text: str) -> set[str]:
    return {w for w in tokens(text) if w not in _FUNCTION and not w.isdigit()}
