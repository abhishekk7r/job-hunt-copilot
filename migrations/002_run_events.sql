-- Migration 002: Add run_events table and index for live progress tracking
-- PRAGMA user_version = 2

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    phase TEXT NOT NULL,
    step TEXT NOT NULL,
    detail TEXT DEFAULT '',
    state TEXT CHECK(state IN ('started','ok','skipped','error')),
    counts TEXT DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_run_events_run_id_seq ON run_events(run_id, seq);
