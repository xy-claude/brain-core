-- 009_claims: claims, evidence and time (M3). Derived from the vault, ontology.yaml and the
-- journal's recording times; deleting brain.db loses nothing here (audit L.1, L.5).
-- Raw rows, one source each, are in claim_raw: exactly the open versions of data/journal.db's
-- derivation_journal. Every other table is recomputed from them, never edited.
CREATE TABLE IF NOT EXISTS claim_raw (            -- raw rows as the rules read them (G.2)
    kind      TEXT NOT NULL CHECK (kind IN ('evidence', 'review', 'link', 'time')),
    row_key   TEXT NOT NULL,                       -- JSON, the source id first
    source_id TEXT NOT NULL,
    row_json  TEXT NOT NULL,
    line      INTEGER NOT NULL DEFAULT 0,              -- locator only: never in a journal version
    PRIMARY KEY (kind, row_key)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_claim_raw_source ON claim_raw(source_id);

CREATE TABLE IF NOT EXISTS claims_state (         -- raw rows changed since the last recompute
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    dirty  INTEGER NOT NULL DEFAULT 1,
    report TEXT NOT NULL DEFAULT '[]',                 -- what the last recompute asks a person to look at
    inputs TEXT NOT NULL DEFAULT ''                    -- fingerprint of the entities and the ontology used
);
INSERT OR IGNORE INTO claims_state (id, dirty) VALUES (1, 1);

CREATE TABLE IF NOT EXISTS claims (                -- Claim, minus what has its own table
    id             TEXT PRIMARY KEY,                -- ClaimKey.id()
    subject        TEXT NOT NULL,
    predicate      TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT '',
    object_entity  TEXT,
    object_literal TEXT,
    datatype       TEXT CHECK (datatype IN ('text', 'int', 'version', 'port', 'url', 'date')),
    lifecycle      TEXT NOT NULL CHECK (lifecycle IN ('candidate', 'accepted', 'rejected')),
    verification   TEXT NOT NULL CHECK (verification IN ('stated', 'approved', 'derived', 'unverified')),
    confidence     TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    retracted_at   TEXT,
    rank           INTEGER NOT NULL,                -- traversal order (H.3): accepted, candidate, rejected
    CHECK ((object_entity IS NULL) <> (object_literal IS NULL)),
    CHECK ((object_literal IS NULL) = (datatype IS NULL)),
    CHECK (retracted_at IS NULL OR lifecycle = 'rejected'),
    CHECK (lifecycle <> 'accepted' OR verification <> 'unverified')
);
CREATE INDEX IF NOT EXISTS idx_claims_out ON claims(subject, lifecycle, rank, id);
CREATE INDEX IF NOT EXISTS idx_claims_in  ON claims(object_entity, lifecycle, rank, id);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(subject, predicate, role);

CREATE TABLE IF NOT EXISTS identity_redirects (   -- Redirect: retired ids of every kind (F.5)
    kind   TEXT NOT NULL CHECK (kind IN ('entity', 'claim', 'record')),
    old_id TEXT NOT NULL,
    new_id TEXT NOT NULL,
    cause  TEXT NOT NULL CHECK (cause IN ('merge', 'rename', 'merge+rename', 'id-scheme')),
    PRIMARY KEY (kind, old_id),
    CHECK (old_id <> new_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_redirects_new ON identity_redirects(kind, new_id);

CREATE TABLE IF NOT EXISTS claim_evidence (       -- Evidence, flattened and resolved
    claim_id     TEXT NOT NULL,
    occ_id       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    record_id    TEXT NOT NULL,
    ordinal      INTEGER NOT NULL CHECK (ordinal >= 1),
    rule         TEXT NOT NULL,
    line         INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    object_name  TEXT,
    stated_date  TEXT,
    event_date   TEXT,
    valid_from   TEXT,
    valid_to     TEXT,
    timeless     INTEGER NOT NULL DEFAULT 0,
    recorded_at  TEXT NOT NULL,
    recorded_by  TEXT NOT NULL CHECK (recorded_by IN ('write', 'ingest', 'move')),
    origin       TEXT NOT NULL CHECK (origin IN ('user', 'agent', 'markup', 'extracted', 'inferred', 'reflection', 'external')),
    verification TEXT NOT NULL CHECK (verification IN ('stated', 'approved', 'derived', 'unverified')),
    confidence   TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    quote        TEXT NOT NULL CHECK (length(quote) BETWEEN 1 AND 300),
    PRIMARY KEY (claim_id, occ_id, rule),
    CHECK (timeless = 0 OR (valid_from IS NULL AND valid_to IS NULL)),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to > valid_from)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_evidence_source ON claim_evidence(source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_record ON claim_evidence(record_id);
CREATE INDEX IF NOT EXISTS idx_evidence_occ    ON claim_evidence(occ_id);

CREATE TABLE IF NOT EXISTS record_times (         -- record_meta.md valid / until / event
    rid        TEXT NOT NULL,
    occ_scope  TEXT NOT NULL DEFAULT '',            -- '' = every occurrence; else <source>#<k>
    valid_from TEXT,
    valid_to   TEXT,
    event_date TEXT,
    timeless   INTEGER NOT NULL DEFAULT 0,
    line_occ   TEXT NOT NULL,
    PRIMARY KEY (rid, occ_scope),
    CHECK (timeless = 0 OR (valid_from IS NULL AND valid_to IS NULL))
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS record_links (         -- record_meta.md supersedes / was
    new_rid  TEXT NOT NULL,
    old_rid  TEXT NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('supersedes', 'was')),
    line_occ TEXT NOT NULL,
    PRIMARY KEY (new_rid, old_rid, kind)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_links_old ON record_links(old_rid);

CREATE TABLE IF NOT EXISTS claim_periods (        -- Period, computed
    claim_id  TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    seq       INTEGER NOT NULL,
    true_from TEXT,
    true_to   TEXT,
    link_end  TEXT,
    timeless  INTEGER NOT NULL DEFAULT 0,
    undated   INTEGER NOT NULL DEFAULT 0,
    stated    INTEGER NOT NULL DEFAULT 0,
    disputed  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (claim_id, seq)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS claim_conflicts (      -- Conflict, computed; one row per window
    claim_a      TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    claim_b      TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('functional_overlap')),
    scope        TEXT NOT NULL CHECK (scope IN ('interval', 'current')),
    overlap_from TEXT,
    overlap_to   TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (claim_a, claim_b, seq),
    CHECK (claim_a < claim_b)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_conflicts_b ON claim_conflicts(claim_b);

CREATE TABLE IF NOT EXISTS claim_reviews (        -- Review, from claim_reviews.md
    occ_id         TEXT PRIMARY KEY,
    action         TEXT NOT NULL CHECK (action IN ('reject', 'retract', 'restore', 'ack')),
    key_json       TEXT NOT NULL,                   -- the key as written (names, not ids)
    other_json     TEXT,
    claim_id       TEXT NOT NULL,                   -- no FK: a rejection outlives its evidence
    other_claim_id TEXT,
    recorded_at    TEXT NOT NULL,
    reason         TEXT,
    CHECK ((action = 'ack') = (other_json IS NOT NULL))
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_reviews_claim ON claim_reviews(claim_id);
