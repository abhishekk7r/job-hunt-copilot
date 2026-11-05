#!/usr/bin/env python3
"""Migration 001: Add harness execution columns, dedup source_key, and logging/kill-switch tables."""

import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.job_key import make_key
except ImportError:
    make_key = lambda company, role, url="": f"{company}_{role}".strip().lower()


def migrate(db_path: str = "") -> bool:
    if not db_path:
        db_path = os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))

    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")

    cur = conn.cursor()
    cur.execute("PRAGMA user_version;")
    ver = cur.fetchone()[0]

    # Check if already applied
    if ver >= 1:
        conn.close()
        return False

    # Check if jobs table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
    if not cur.fetchone():
        # Schema not initialized, initialize core tables
        schema_path = REPO_ROOT / "schema.sql"
        if schema_path.exists():
            cur.executescript(schema_path.read_text(encoding="utf-8"))

    # Inspect existing columns in jobs
    cur.execute("PRAGMA table_info(jobs)")
    existing_cols = {row["name"] for row in cur.fetchall()}

    columns_to_add = [
        ("salary_lpa", "INTEGER"),
        ("stack_keywords", "TEXT"),
        ("source", "TEXT"),
        ("source_key", "TEXT"),
        ("rank_score", "REAL"),
        ("rank_verdict", "TEXT"),
        ("rank_reason", "TEXT"),
        ("posting_url_canonical", "TEXT"),
        ("first_seen", "TEXT"),
        ("applied_with_resume", "TEXT"),
        ("last_status_before_outreach", "TEXT"),
        ("outreach_state", "TEXT DEFAULT 'NONE'"),
    ]

    for col_name, col_type in columns_to_add:
        if col_name not in existing_cols:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type};")

    # Populate source_key for any existing jobs missing it
    cur.execute("SELECT id, company, role, job_url, source_key FROM jobs")
    rows = cur.fetchall()
    for row in rows:
        if not row["source_key"]:
            k = make_key(row["company"], row["role"], row["job_url"])
            cur.execute("UPDATE jobs SET source_key = ? WHERE id = ?", (k, row["id"]))

    # Add unique index on source_key
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_key ON jobs(source_key);")

    # Add new tables: run_log, action_log, kill_switch
    cur.execute("""
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
    """)

    cur.execute("""
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
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS kill_switch (
            id INTEGER PRIMARY KEY CHECK (id=1),
            "on" INTEGER NOT NULL DEFAULT 0,
            reason TEXT DEFAULT '',
            ts TEXT DEFAULT ''
        );
    """)

    cur.execute('INSERT OR IGNORE INTO kill_switch (id, "on", reason, ts) VALUES (1, 0, "", "");')

    cur.execute("PRAGMA user_version = 1;")
    conn.commit()
    conn.close()
    return True


if __name__ == "__main__":
    target_db = sys.argv[1] if len(sys.argv) > 1 else ""
    migrated = migrate(target_db)
    status_str = "applied" if migrated else "already at version 1 or higher"
    print(f"Migration 001 {status_str}.")
