-- Migration 003: Decisions and decision_log tables for autonomous decision policy
-- Idempotent creation with CHECK constraints and indexes

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    company TEXT NOT NULL,
    question TEXT NOT NULL,
    field_key TEXT DEFAULT '',
    proposed_answer TEXT DEFAULT '',
    rationale TEXT DEFAULT '',
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','EDITED','SKIPPED')),
    final_answer TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    answered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_job_id ON decisions(job_id);

CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT DEFAULT '',
    job_id INTEGER,
    company TEXT NOT NULL,
    field TEXT NOT NULL,
    answer TEXT DEFAULT '',
    source TEXT DEFAULT '',
    rule TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
    outcome TEXT NOT NULL CHECK (outcome IN ('AUTO','AUTO_LOG','ESCALATE','HARD_STOP')),
    wrong INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_decision_log_job_id ON decision_log(job_id);
CREATE INDEX IF NOT EXISTS idx_decision_log_outcome ON decision_log(outcome);
