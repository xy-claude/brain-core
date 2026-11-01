-- 001_initial: baseline schema for brain-core v0 capabilities.
-- Creates: facts, decisions, events, hsam_days, reflections, metrics.
-- schema_version is managed by the migrator itself, not this file.

-- ─── facts: structured memory ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'pattern', 'preference', 'constraint')),
    tags TEXT,                                           -- JSON array, nullable
    metadata TEXT,                                       -- JSON object, nullable
    content_hash TEXT NOT NULL UNIQUE,                   -- dedup guard
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    superseded_by INTEGER REFERENCES facts(id)
);

CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_facts_superseded ON facts(superseded_by);

-- ─── facts_fts: full-text search over facts ──────────────────────────────
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    content,
    tags,
    content='facts',
    content_rowid='id'
);

-- Keep FTS index in sync via triggers
CREATE TRIGGER IF NOT EXISTS facts_fts_insert AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_fts_delete AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_fts_update AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
    INSERT INTO facts_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;

-- ─── decisions: classified decision log ──────────────────────────────────
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    reversible INTEGER NOT NULL CHECK (reversible IN (0, 1)),
    risk TEXT NOT NULL CHECK (risk IN ('low', 'medium', 'high')),
    confidence TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    reasoning TEXT,
    alternatives TEXT,                                   -- JSON array, nullable
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reversed', 'completed')),
    reversed_by INTEGER REFERENCES decisions(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);

-- ─── events: episodic event log ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload TEXT,                                        -- JSON, nullable
    session_id TEXT,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, occurred_at);

-- ─── hsam_days: daily archive index ──────────────────────────────────────
-- Archive body is a markdown file on disk; this table holds metadata only.
CREATE TABLE IF NOT EXISTS hsam_days (
    date TEXT PRIMARY KEY,                               -- YYYY-MM-DD
    archive_path TEXT NOT NULL,                          -- relative to workspace
    word_count INTEGER NOT NULL DEFAULT 0,
    last_written TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ─── reflections: end-of-session synthesis ───────────────────────────────
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    what_went_well TEXT,
    what_to_improve TEXT,
    apply_next_session TEXT,
    auto_generated INTEGER NOT NULL DEFAULT 0 CHECK (auto_generated IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reflections_session ON reflections(session_id);

-- ─── metrics: observability ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    tags TEXT,                                           -- JSON, nullable
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON metrics(metric_name, recorded_at);
