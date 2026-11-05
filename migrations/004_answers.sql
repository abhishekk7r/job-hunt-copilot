-- 004_answers.sql: Unified answer bank
CREATE TABLE IF NOT EXISTS answers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT NOT NULL,          -- canonical wording
  answer TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('fact','choice','story','policy','legal')),
  scope TEXT NOT NULL DEFAULT 'global',   -- 'global' or 'company:<normalized name>'
  status TEXT NOT NULL DEFAULT 'approved' CHECK (status IN ('approved','drafted','retired')),
  source TEXT NOT NULL DEFAULT '',        -- e.g. 'screening_qa', 'decision:12', 'job:41', 'owner'
  uses INTEGER NOT NULL DEFAULT 0,
  last_used_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS answers_q_scope ON answers(lower(question), scope);
