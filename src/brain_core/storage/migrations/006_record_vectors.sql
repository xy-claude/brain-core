-- Vectors of the records in records_fts, for the optional vector search (stores.vectors).
-- Derived data: dropping the table loses nothing, `brain index` fills it again from the files.
CREATE TABLE IF NOT EXISTS record_vectors (
    record_id  TEXT PRIMARY KEY,   -- same id as records_fts.rid
    model      TEXT NOT NULL,      -- the model that made it; another model's vector is never compared
    dim        INTEGER NOT NULL,
    text_hash  TEXT NOT NULL,      -- hash of exactly what was embedded
    vec        BLOB NOT NULL       -- little-endian float32, full dimensions
);
