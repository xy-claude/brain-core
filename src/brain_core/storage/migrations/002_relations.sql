-- 002_relations: the entity graph lives in SQLite (M17). Replaces the Kuzu CLI store.
-- One row per (subject, predicate, object); id is the sha256 of "S —[p]→ O" so it matches
-- the vault/Hindsight record id for the same relation.

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (subject, predicate, object)
);

CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object);
