-- 008_entities: the entity registry (M2), derived from vault/entities/*.md and rebuilt from
-- them: deleting brain.db loses nothing here. Mentions: the occurrences that name an entity,
-- found without a model (a wikilink, an alias in the text, a #tag).
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,                   -- UUIDv7 from the note's frontmatter
    type        TEXT NOT NULL,                      -- one of ontology.yaml's entity_types
    name        TEXT NOT NULL,
    source_id   TEXT NOT NULL UNIQUE,               -- vault:entities/<file>.md
    merged_into TEXT REFERENCES entities(id) DEFERRABLE INITIALLY DEFERRED,
    ontology    INTEGER NOT NULL DEFAULT 1,
    degree      INTEGER NOT NULL DEFAULT 0          -- claims naming it (M3; the hub test)
);
CREATE TABLE IF NOT EXISTS aliases (
    alias     TEXT NOT NULL,                        -- normalised (NFKC, casefold)
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (alias, entity_id)
);
CREATE TABLE IF NOT EXISTS mentions (
    occ_id    TEXT NOT NULL,                        -- the occurrence that mentions it
    source_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    ordinal   INTEGER NOT NULL CHECK (ordinal >= 1),
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    how       TEXT NOT NULL CHECK (how IN ('wikilink', 'alias', 'tag', 'extracted')),
    PRIMARY KEY (occ_id, entity_id, how)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_source ON mentions(source_id);
