-- Search keys: other words a record can be found by, kept in the vault's record_meta.md.
-- The index is a cache, so it is dropped and rebuilt from the files with the new columns.
DROP TABLE IF EXISTS records_fts;
DELETE FROM index_files;
CREATE VIRTUAL TABLE records_fts USING fts5(
    body,
    keys,
    store UNINDEXED,
    kind UNINDEXED,
    path UNINDEXED,
    rid UNINDEXED,
    record UNINDEXED,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
