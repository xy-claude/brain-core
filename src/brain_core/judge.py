"""The judge: a model reads the candidates recall gathered and picks the ones that answer.

Recall's two searches put forward records that might answer. Ranking them by a score cannot tell
"this answers the question" from "this is on the topic", and it cannot say "nothing here answers".
A model that reads the records can. With ``recall.judge: model`` brain-core asks one (the same
runners mental models use) and puts its picks first; with the default ``agent`` the calling agent
is the judge and reads the list itself.

The model is never trusted with facts: it returns numbers of records it was shown, a number that
was not shown is dropped, and any failure leaves recall's own order in place.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from datetime import date

from brain_core.stores.base import Record, full_text
from brain_core.stores.vault import _SECRET

Runner = Callable[[str, str], str]
RECORD_CHARS = 700  # of each record shown to the model
STATUSES = ("answered", "partial", "not_in_memory")

SYSTEM = """You are the last step of a memory search. You get a question and numbered memory \
records that a search put forward. Decide which records answer the question.

Rules:
- Pick only records that hold the answer or a needed part of it. A record that is merely on \
the same topic is not an answer.
- When records give different values for the same thing, the newest dated one is current: put \
it first, and leave the outdated one out unless the question asks about the past.
- A record marked (replaced) holds an old value.
- When the answer is spread over several records, pick every one that is needed.
- If the question names a day, prefer records dated that day.
- If no record answers the question, say so. Being close is not answering.

Reply with one JSON object and nothing else:
{"picks": [record numbers, most useful first, at most 10], "status": "answered" | "partial" | \
"not_in_memory"}
"answered": the picks answer it. "partial": the picks hold part of the answer. \
"not_in_memory": nothing answers it, and picks is []."""

_JSON = re.compile(r"\{.*\}", re.S)


class JudgeError(RuntimeError):
    """The model could not be asked or its reply could not be used; recall keeps its own order."""


def prompt(query: str, records: Sequence[tuple[Record, bool]], today: date) -> str:
    """``records``: each with whether a newer record replaced it."""
    lines = [
        f"[{i}] ({r.kind}, {r.date.isoformat()}{', replaced' if stale else ''}) "
        f"{' '.join(full_text(r).split())[:RECORD_CHARS]}"
        for i, (r, stale) in enumerate(records, 1)
    ]
    return (
        f"Today is {today.isoformat()}.\n\nRecords:\n" + "\n".join(lines) + f"\n\nQuestion: {query}"
    )


def parse(reply: str, shown: int) -> tuple[list[int], str]:
    """The picks as 0-based places in the list that was shown, and the status. A number that
    was not shown is dropped; a reply that is not the JSON asked for is an error."""
    m = _JSON.search(reply)
    try:
        doc = json.loads(m.group(0)) if m else None
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or doc.get("status") not in STATUSES:
        raise JudgeError(f"unusable reply: {reply[:120]!r}")
    raw = doc.get("picks")
    raw = raw if isinstance(raw, list) else []
    picks = list(dict.fromkeys(n - 1 for n in raw if isinstance(n, int) and 1 <= n <= shown))
    status = str(doc["status"])
    if status != "not_in_memory" and not picks:
        raise JudgeError("the reply says answered but names no record it was shown")
    return ([] if status == "not_in_memory" else picks[:10]), status


def judge(
    run: Runner, query: str, records: Sequence[tuple[Record, bool]], today: date
) -> tuple[list[int], str]:
    """Ask the model. A record that looks like it holds a secret is never sent: it keeps its
    place in the numbering as a blank, so the picks still point at the right records."""
    if not records:
        raise JudgeError("no candidates to judge")
    safe = [
        (r if not _SECRET.search(full_text(r)) else Record(r.id, r.kind, "(withheld)", r.date), s)
        for r, s in records
    ]
    try:
        reply = run(SYSTEM, prompt(query, safe, today))
    except Exception as e:  # a runner raises its own error types; none may break recall
        raise JudgeError(f"{type(e).__name__}: {str(e)[:160]}") from e
    return parse(reply, len(records))
