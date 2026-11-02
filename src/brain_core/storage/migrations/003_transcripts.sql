-- 003_transcripts: a read-only index of the Claude Code session transcripts of this agent's
-- folder (~/.claude/projects/<encoded cwd>/*.jsonl). One row per text block, FTS5 over the
-- text, and a per-file byte offset so a reindex only reads what was appended.

CREATE TABLE IF NOT EXISTS transcripts (
    id TEXT PRIMARY KEY,            -- message uuid + block index
    session TEXT NOT NULL,
    ts TEXT NOT NULL,               -- ISO timestamp from the transcript line
    role TEXT NOT NULL,             -- user | assistant
    text TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    text,
    content='transcripts',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;

CREATE TABLE IF NOT EXISTS transcript_files (
    path TEXT PRIMARY KEY,
    offset INTEGER NOT NULL,
    mtime REAL NOT NULL
);
