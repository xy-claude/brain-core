"""The claim model (audit F.3, F.5, J.1), as validated by the audit's checker.

A claim is an assertion about entities: its id hashes the key (subject, predicate, role,
object) and nothing else. Each occurrence that supports it is one evidence row, with valid time
from the text (stated dates, ``valid:`` / ``until:``) and transaction time from the journal's
ledger, never from the text. Validity is three-valued: every row votes, and silence or
disagreement is UNKNOWN, never true.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Level = Literal["high", "medium", "low"]
Validity = Literal["true", "false", "unknown"]
Datatype = Literal["text", "int", "version", "port", "url", "date"]
FROZEN = ConfigDict(extra="forbid", frozen=True)


def h(*parts: object) -> str:
    """Every derived key: sha256 of a JSON list, first 32 hex characters."""
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:32]


class Lifecycle(StrEnum):  # review state of the assertion, nothing else (J.2)
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Origin(StrEnum):  # how ONE evidence row came to be
    USER = "user"
    AGENT = "agent"
    MARKUP = "markup"
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    REFLECTION = "reflection"
    EXTERNAL = "external"


class Verification(StrEnum):  # strongest first; a claim takes its strongest evidence
    STATED = "stated"
    APPROVED = "approved"
    DERIVED = "derived"
    UNVERIFIED = "unverified"


class ClaimKey(BaseModel):
    """What is asserted. A claim's id hashes this and nothing else."""

    model_config = FROZEN
    subject: str  # entity UUID after merged_into; `name:<alias>` until a note names it
    predicate: str  # ontology name, after `renames:`
    role: str = ""  # qualifies a functional predicate: USES(graph-database) != USES(cache)
    object_entity: str | None = None
    object_literal: str | None = None
    datatype: Datatype | None = None

    @model_validator(mode="after")
    def _one_object(self) -> Self:
        if (self.object_entity is None) == (self.object_literal is None):
            raise ValueError("exactly one of object_entity, object_literal")
        if (self.object_literal is None) != (self.datatype is None):
            raise ValueError("a literal needs a datatype; an entity has none")
        return self

    def id(self) -> str:
        if self.object_entity is not None:
            obj: tuple[str, str] = ("e", self.object_entity)
        else:
            obj = (f"l:{self.datatype}", " ".join(str(self.object_literal).split()))
        return h("claim/1", self.subject, self.predicate, self.role, *obj)


class Occurrence(BaseModel):
    """One copy of a record's text in one source: the k-th copy of `record_id` there (G.2)."""

    model_config = FROZEN
    source_id: str  # "vault:relations.md", "notes:shared/x.md": never an absolute path (G11)
    record_id: str = Field(min_length=16)
    ordinal: int = Field(ge=1)

    def id(self) -> str:
        return h("occ/1", self.source_id, self.record_id, self.ordinal)


EntityType = Literal[
    "person", "organization", "project", "component", "technology", "concept", "mission"
]


class Entity(BaseModel):
    """A thing claims are about. Canonical form: an Obsidian note in vault/entities/ (F.1)."""

    model_config = FROZEN
    id: str  # UUIDv7, written once into the note's frontmatter; survives renames and moves
    type: EntityType
    name: str
    source_id: str  # "vault:entities/Neo4j.md"
    merged_into: str | None = None  # set on the losing note of a merge; the note stays
    ontology: int = 1
    aliases: frozenset[str] = frozenset()  # normalised (NFKC, casefold): the aliases table


class Mention(BaseModel):
    """An occurrence that names an entity, found without a model (wikilink, alias, tag)."""

    model_config = FROZEN
    occurrence: Occurrence
    entity_id: str
    how: Literal["wikilink", "alias", "tag", "extracted"]


class Redirect(BaseModel):
    """An identity that was retired, and what replaced it: any old id found in an event, a
    review or an eval label can be followed to the current one."""

    model_config = FROZEN
    kind: Literal["entity", "claim", "record"]
    old_id: str
    new_id: str
    cause: Literal["merge", "rename", "merge+rename", "id-scheme"]  # id-scheme: `was:` lines


class Evidence(BaseModel):
    """One occurrence supporting one claim through one rule. Row key: (claim, occurrence, rule)."""

    model_config = FROZEN
    occurrence: Occurrence
    rule: str  # "relations.md/1", "decision-field/1"
    line: int = 0  # where it stands now: for citation only, never identity
    content_hash: str  # sha256 of the exact text of this version: the ledger's version key
    subject_name: str  # the raw names as written, so an alias change can re-resolve them
    object_name: str | None = None
    stated_date: date | None  # the date the text gives; None = undated. Valid time only
    event_date: date | None = None  # the day the described event happened, when stated
    valid_from: date | None = None  # an explicit start: meta `valid:`, a decision's own date
    valid_to: date | None = None  # an explicit end: meta `until:` (exclusive)
    timeless: bool = False  # meta `valid: always`; never inferred
    recorded_at: datetime  # transaction time, from the ledger, never from the text (J.1)
    recorded_by: Literal["write", "ingest", "move"]
    origin: Origin
    verification: Verification
    confidence: Level | None = None
    quote: str = Field(min_length=1, max_length=300)  # occurs in the record (grounding)

    @model_validator(mode="after")
    def _time(self) -> Self:
        if self.timeless and (self.valid_from or self.valid_to):
            raise ValueError("timeless takes no valid_from / valid_to")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self

    def start(self) -> tuple[date | None, bool]:
        """Where this row says the claim holds from, and whether that is a stated start
        (`valid:`, which also says "not before") or only the record's own date ("held then")."""
        return (self.valid_from, True) if self.valid_from else (self.stated_date, False)


class Period(BaseModel):
    """One stretch of a claim's validity, with every evidence row that speaks to it (J.1)."""

    model_config = FROZEN
    evidence: tuple[Evidence, ...]
    link_end: date | None = None  # a superseding record that does not assert the claim starts

    @property
    def timeless(self) -> bool:  # some row says `valid: always`
        return any(e.timeless for e in self.evidence)

    @property
    def undated(self) -> bool:  # some row has no date at all: it speaks for today only
        return any(e.start()[0] is None and not e.timeless for e in self.evidence)

    @property
    def stated(self) -> bool:  # some row states a start (`valid:`), which also says "not before"
        return any(e.valid_from for e in self.evidence)

    def votes(self, d: date, today: date) -> tuple[int, int]:
        """How many rows say the claim holds on d, and how many say it does not."""
        yes = no = 0
        for e in self.evidence:
            start, stated = e.start()
            if e.valid_to is not None and d >= e.valid_to:
                no += 1
            elif e.timeless:
                yes += 1  # "always": true on every day, one vote among the others
            elif start is None:
                yes += d == today  # undated: a standing fact, current now, silent on the past
            elif d >= start:
                yes += 1
            elif stated:
                no += 1  # before a stated start: "not yet"
        return yes, no

    def at(self, d: date, today: date) -> Validity:
        if self.link_end is not None and d >= self.link_end:
            return "false"  # superseded: ends every row of the period, a timeless one included
        yes, no = self.votes(d, today)
        if yes and not no:
            return "true"
        if no and not yes:
            return "false"
        return "unknown"  # the sources disagree, or none of them speaks about d

    @property
    def true_from(self) -> date | None:
        """Stored for SQL. With a stated start: the latest one (TRUE needs every stated start
        passed). Otherwise the first dated row. None: no dated row."""
        stated = [e.valid_from for e in self.evidence if e.valid_from]
        starts = [s for s, _stated in (e.start() for e in self.evidence) if s]
        return max(stated) if stated else min(starts) if starts else None

    @property
    def true_to(self) -> date | None:  # exclusive: the first stated end, or the link end
        ends = [e.valid_to for e in self.evidence if e.valid_to]
        return min([*ends, *([self.link_end] if self.link_end else [])], default=None)

    def true_on(self, d: date, today: date) -> bool:
        """Exactly `at(d) == "true"`, from the stored summary alone: what the SQL does."""
        if self.true_to is not None and d >= self.true_to:
            return False
        if self.stated:
            return self.true_from is not None and d >= self.true_from
        return (
            self.timeless
            or (self.true_from is not None and d >= self.true_from)
            or (self.undated and d == today)
        )

    @property
    def disputed(self) -> bool:
        """Some dated window where rows disagree: a stated start after another row's start or
        after an "always", two different stated ends, or an "always" with a stated end."""
        starts = [s for s, _stated in (e.start() for e in self.evidence) if s]
        stated = [e.valid_from for e in self.evidence if e.valid_from]
        ends = {e.valid_to for e in self.evidence if e.valid_to}
        return (
            bool(stated and (self.timeless or min(starts) < max(stated)))
            or len(ends) > 1
            or bool(self.timeless and ends)
        )


class Conflict(BaseModel):
    """Two claims of one functional (subject, predicate, role) TRUE on the same days. Stored
    without reference to today, so the computed tier does not change with the calendar."""

    model_config = FROZEN
    other: str  # the conflicting claim's id
    kind: Literal["functional_overlap"]
    scope: Literal["interval", "current"]  # current: through an undated row, so "today" only
    overlap_from: date | None  # None: no lower bound
    overlap_to: date | None  # exclusive; None: no upper bound
    acknowledged: bool = False  # an `ack` line in claim_reviews.md: both true, by a person

    def active_on(self, d: date, today: date) -> bool:
        """Both claims are TRUE on d (given today). An interval conflict holds on every day of
        its window; a current one only on today, when today falls in its window."""
        inside = (self.overlap_from is None or d >= self.overlap_from) and (
            self.overlap_to is None or d < self.overlap_to
        )
        return inside and (self.scope == "interval" or d == today)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    key: ClaimKey
    lifecycle: Lifecycle  # from verification and claim_reviews.md (J.2)
    verification: Verification
    origins: frozenset[Origin]  # every evidence row's origin, kept through conflicts and merges
    confidence: Level | None = None
    evidence: list[Evidence] = Field(min_length=1)  # no evidence, no claim
    periods: list[Period] = Field(min_length=1)
    conflicts: list[Conflict] = []
    retracted_at: datetime | None = None  # the ledger time of the retract line
    aliases: frozenset[str] = frozenset()  # earlier ids of this claim: merges, renames (F.5)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.id != self.key.id():
            raise ValueError("id must be key.id()")
        if self.lifecycle is Lifecycle.ACCEPTED and self.verification is Verification.UNVERIFIED:
            raise ValueError("an unverified claim stays a candidate until a person approves it")
        if self.retracted_at and self.lifecycle is not Lifecycle.REJECTED:
            raise ValueError("a retracted claim is rejected")
        rows = [(e.occurrence.id(), e.rule) for e in self.evidence]
        if len(rows) != len(set(rows)):
            raise ValueError("one occurrence supports a claim once per rule")
        return self

    @property
    def disputed(self) -> bool:  # a conflict is on record and no person acknowledged it
        return any(not c.acknowledged for c in self.conflicts)

    def disputed_on(self, d: date, today: date) -> bool:  # what recall shows for day d
        return any(not c.acknowledged and c.active_on(d, today) for c in self.conflicts)

    def at(self, d: date, today: date) -> Validity:
        got = {p.at(d, today) for p in self.periods}
        return "true" if "true" in got else "unknown" if "unknown" in got else "false"


class LedgerRow(BaseModel):
    """One presence interval of one version at one occurrence: a journal row, never derived,
    never rebuilt, only backed up (J.1). journal.py writes them."""

    model_config = FROZEN
    occ_id: str
    content_hash: str
    seen_from: datetime
    seen_to: datetime | None = None
    via: Literal["write", "ingest", "move"]
    moved_from: str | None = None


class Review(BaseModel):
    """One line of claim_reviews.md, ordered by its ledger time (never a date written on the
    line), keeping the key as it was written (F.5)."""

    model_config = FROZEN
    action: Literal["reject", "retract", "restore", "ack"]
    key: ClaimKey  # as written, before any later merge or rename
    other: ClaimKey | None = None  # ack: the other claim of the pair
    recorded_at: datetime
    reason: str = ""


# (old record id, new record id, the new record's start): `supersedes`. Ids compare on their
# first 16 characters, the length record_meta.md writes
Link = tuple[str, str, date]
