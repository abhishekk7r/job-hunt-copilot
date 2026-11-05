-- Canonical schema for Job Harness SQLite database (harness.db)
-- PRAGMA user_version = 1

CREATE TABLE IF NOT EXISTS agent_locks (
    resource_id TEXT PRIMARY KEY,
    locked_by TEXT NOT NULL,
    task_description TEXT NOT NULL,
    locked_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_heartbeats (
    agent_name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    active_resource TEXT,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    job_url TEXT UNIQUE NOT NULL,
    job_id_ext TEXT DEFAULT 'N/A',
    location TEXT DEFAULT 'India',
    platform TEXT NOT NULL,
    tier INTEGER DEFAULT 2,
    status TEXT DEFAULT 'TO_APPLY',
    blocker_note TEXT DEFAULT '',
    recruiter_name TEXT DEFAULT '',
    recruiter_title TEXT DEFAULT '',
    recruiter_linkedin TEXT DEFAULT '',
    recruiter_email TEXT DEFAULT '',
    connection_degree INTEGER DEFAULT 2,
    date_applied TEXT DEFAULT '',
    next_followup TEXT DEFAULT '',
    notion_synced INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL,
    salary_lpa INTEGER,
    stack_keywords TEXT,
    source TEXT,
    source_key TEXT,
    rank_score REAL,
    rank_verdict TEXT,
    rank_reason TEXT,
    posting_url_canonical TEXT,
    first_seen TEXT,
    applied_with_resume TEXT,
    last_status_before_outreach TEXT,
    outreach_state TEXT DEFAULT 'NONE'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_key ON jobs(source_key);

CREATE TABLE IF NOT EXISTS outreach_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    recruiter_name TEXT NOT NULL,
    recruiter_linkedin TEXT NOT NULL,
    channel TEXT NOT NULL,
    rendered_message TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    approval_status TEXT DEFAULT 'PENDING_MOBILE_REVIEW',
    sent_from TEXT DEFAULT '',
    sent_at TEXT DEFAULT '',
    next_followup TEXT DEFAULT '',
    notion_synced INTEGER DEFAULT 0,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS screening_qa (
    question_key TEXT PRIMARY KEY,
    answer TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS story_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    question_pattern TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    key_metrics TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    connection_degree INTEGER DEFAULT 2,
    mutual_connections INTEGER DEFAULT 0,
    current_company TEXT NOT NULL,
    location TEXT DEFAULT '',
    score REAL DEFAULT 0.0,
    kind TEXT DEFAULT 'recruiter',
    outreach_kind TEXT DEFAULT 'job_specific',
    note_text TEXT DEFAULT '',
    note_chars INTEGER DEFAULT 0,
    status TEXT DEFAULT 'PROPOSED',
    created_at TEXT NOT NULL,
    email TEXT DEFAULT '',
    note TEXT DEFAULT '',
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS budgets (
    key TEXT PRIMARY KEY,
    val INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    halted_reason TEXT DEFAULT '',
    counts_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    result TEXT NOT NULL,
    detail TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kill_switch (
    id INTEGER PRIMARY KEY CHECK (id=1),
    "on" INTEGER NOT NULL DEFAULT 0,
    reason TEXT DEFAULT '',
    ts TEXT DEFAULT ''
);

INSERT OR IGNORE INTO kill_switch (id, "on", reason, ts) VALUES (1, 0, '', '');

-- Application-level long-form answers (e.g. Acme Corp's 6 story questions), with submit status.
CREATE TABLE IF NOT EXISTS app_story_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    status TEXT DEFAULT 'DRAFT_NOT_SUBMITTED',
    saved_at TEXT NOT NULL,
    UNIQUE(application, question)
);

CREATE TABLE IF NOT EXISTS open_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    item TEXT NOT NULL,
    status TEXT DEFAULT 'OPEN',
    saved_at TEXT NOT NULL,
    UNIQUE(area, item)
);

CREATE TABLE IF NOT EXISTS outreach_email_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    company TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    contact_linkedin TEXT,
    to_email TEXT DEFAULT '',
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT DEFAULT 'DRAFT_NOT_SENT',
    scheduled_for TEXT DEFAULT '',
    saved_at TEXT NOT NULL,
    UNIQUE(company, contact_name)
);

CREATE TABLE IF NOT EXISTS gmail_drafts_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT,
    draft_message_id TEXT UNIQUE,
    to_addr TEXT,
    subject TEXT,
    note TEXT DEFAULT '',
    snapshot_at TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fact','choice','story','policy','legal')),
    scope TEXT NOT NULL DEFAULT 'global',
    status TEXT NOT NULL DEFAULT 'approved' CHECK (status IN ('approved','drafted','retired')),
    source TEXT NOT NULL DEFAULT '',
    uses INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS answers_q_scope ON answers(lower(question), scope);
