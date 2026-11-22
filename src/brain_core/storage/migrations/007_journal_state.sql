-- 007_journal_state: the journal marker brain.db keeps (M1c). The generation and the last
-- sync_seq of data/journal.db that this brain.db has seen; written with the index rows, after
-- the journal's own commit. A brain.db ahead of its journal, or of another generation, means
-- the journal lost commits or was replaced: the next sync reads every file again.
CREATE TABLE IF NOT EXISTS journal_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    generation TEXT NOT NULL,
    sync_seq INTEGER NOT NULL
);
