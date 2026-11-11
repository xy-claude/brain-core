-- One full-text index over every record the markdown stores parse (vault files, notes folders).
-- It is a cache: the files are the truth, and stores/index.py rebuilds any row from them.
-- porter: "deployed" finds "deploy". unicode61: accented and non-Latin words are indexed.
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    body,
    store UNINDEXED,
    kind UNINDEXED,
    path UNINDEXED,
    record UNINDEXED,
    tokenize = 'porter unicode61 remove_diacritics 2'
);

-- size and mtime of each indexed file: a file is parsed again only when one of them changes
CREATE TABLE IF NOT EXISTS index_files (
    store TEXT NOT NULL,
    path  TEXT NOT NULL,
    sig   TEXT NOT NULL,
    PRIMARY KEY (store, path)
);
