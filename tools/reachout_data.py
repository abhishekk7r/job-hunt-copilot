#!/usr/bin/env python3
"""Existing reach-out state, so no cycle ever re-contacts or re-drafts someone.

Prints JSON: people already contacted/queued (any status except PROPOSED), known recruiters per
applied job, and existing email drafts. Read-only. The people phase must run this first.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def collect(db: str) -> dict:
    c = sqlite3.connect(db)
    c.execute("PRAGMA query_only = ON")
    c.row_factory = sqlite3.Row
    q = lambda sql: [dict(r) for r in c.execute(sql)]
    out = {
        "already_contacted": q("SELECT name, current_company AS company, profile_url, status FROM contacts "
                               "WHERE status IN ('SENT','PREFILLED','SKIPPED','SKIPPED_TOO_SENIOR','JOB_CONTACT')"),
        "recruiters_for_applied_jobs": q("SELECT company, role, recruiter_name, recruiter_title, recruiter_linkedin, "
                                         "recruiter_email FROM jobs WHERE status='APPLIED' AND recruiter_name<>''"),
        "email_drafts": q("SELECT company, contact_name, to_email, status FROM outreach_email_drafts"),
        "queued_messages": q("SELECT company, recruiter_name, channel, approval_status FROM outreach_queue"),
        "applied_companies": [r["company"] for r in q("SELECT DISTINCT company FROM jobs WHERE status='APPLIED'")],
    }
    c.close()
    return out


def get_reach_targets(db: str, days: int = 14) -> list:
    c = sqlite3.connect(db)
    c.execute("PRAGMA query_only = ON")
    c.row_factory = sqlite3.Row
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = c.execute("""
        SELECT j.id, j.company, j.role, j.status, j.rank_score, j.date_applied, j.updated_at
        FROM jobs j
        LEFT JOIN contacts c ON c.job_id = j.id
        WHERE (
            (j.status = 'APPLIED' AND (j.date_applied >= ? OR (j.date_applied IS NULL AND j.updated_at >= ?)))
            OR j.status = 'TO_APPLY'
        )
        GROUP BY j.id
        HAVING COUNT(c.id) = 0
        ORDER BY j.rank_score DESC, j.id ASC
    """, (cutoff_date, cutoff_date)).fetchall()

    targets = []
    for r in rows:
        row_dict = dict(r)
        if row_dict["status"] == "TO_APPLY":
            note_file = REPO_ROOT / "reports" / "jobs" / f"{r['id']}.md"
            if not note_file.exists():
                continue
            text = note_file.read_text(encoding="utf-8")
            if "referral_first: yes" not in text.lower():
                continue
            row_dict["referral_first"] = True
        else:
            row_dict["referral_first"] = False
        targets.append(row_dict)
    c.close()
    return targets


def get_pending_drafts(db: str) -> list:
    c = sqlite3.connect(db)
    c.execute("PRAGMA query_only = ON")
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT q.id, q.job_id, q.company, q.role, q.recruiter_name, q.recruiter_linkedin,
               q.channel, q.rendered_message, q.char_count, q.approval_status
        FROM outreach_queue q
        WHERE q.approval_status IN ('PENDING_MOBILE_REVIEW', 'APPROVED_TO_SEND')
        ORDER BY q.id ASC
    """).fetchall()
    drafts = [dict(r) for r in rows]
    c.close()
    return drafts


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("Usage: python3 tools/reachout_data.py [--targets] [--drafts]")
        print("Prints existing reach-out state, target jobs needing contacts, or pending drafts.")
        sys.exit(0)
    db_path = os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))
    if "--targets" in sys.argv:
        print(json.dumps(get_reach_targets(db_path), indent=2))
    elif "--drafts" in sys.argv:
        print(json.dumps(get_pending_drafts(db_path), indent=2))
    else:
        print(json.dumps(collect(db_path), indent=2))
