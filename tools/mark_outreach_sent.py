#!/usr/bin/env python3
"""Mark outreach draft as sent, set next follow-up date, and update job status."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def mark_outreach_sent(
    queue_id: int,
    db_path: str = None,
    followup_days: int = 6,
    sent_from: str = "LinkedIn",
) -> dict:
    db = db_path or os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM outreach_queue WHERE id = ?", (queue_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise LookupError(f"Outreach queue id {queue_id} not found")

    now = datetime.utcnow()
    followup = (now + timedelta(days=followup_days)).strftime("%Y-%m-%d")

    if row["channel"] == "InMail":
        cur.execute("UPDATE budgets SET val = MAX(0, val - 1) WHERE key = 'inmail_credits'")

    cur.execute("""
        UPDATE outreach_queue
        SET approval_status = 'SENT', sent_from = ?, sent_at = ?, next_followup = ?, notion_synced = 0
        WHERE id = ?
    """, (sent_from, now.isoformat(), followup, queue_id))

    job_id = row["job_id"]
    if job_id:
        cur.execute("""
            UPDATE jobs
            SET outreach_state = 'SENT', next_followup = ?, notion_synced = 0, updated_at = ?
            WHERE id = ?
        """, (followup, now.isoformat(), job_id))

    if row["recruiter_linkedin"]:
        cur.execute("""
            UPDATE contacts
            SET status = 'SENT'
            WHERE profile_url = ?
        """, (row["recruiter_linkedin"],))
    elif row["recruiter_name"] and row["company"]:
        cur.execute("""
            UPDATE contacts
            SET status = 'SENT'
            WHERE name = ? AND current_company = ?
        """, (row["recruiter_name"], row["company"]))

    cur.execute("""
        INSERT INTO action_log (run_id, ts, actor, action, target, result, detail)
        VALUES (?, ?, 'user', 'mark_outreach_sent', ?, 'SENT', ?)
    """, (f"send-{now.strftime('%Y%m%d')}", now.isoformat(), str(queue_id), f"channel={row['channel']}"))

    conn.commit()
    conn.close()
    return {
        "queue_id": queue_id,
        "job_id": job_id,
        "status": "SENT",
        "next_followup": followup,
        "sent_from": sent_from,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Mark outreach draft as sent and set next follow-up date")
    parser.add_argument("--queue-id", type=int, required=True, help="ID in outreach_queue")
    parser.add_argument("--followup-days", type=int, default=6, help="Days until next follow-up (default: 6)")
    parser.add_argument("--sent-from", default="LinkedIn", help="Account or channel sent from (default: LinkedIn)")
    parser.add_argument("--db", default=None, help="Path to harness.db")

    args = parser.parse_args(argv)
    res = mark_outreach_sent(
        queue_id=args.queue_id,
        db_path=args.db,
        followup_days=args.followup_days,
        sent_from=args.sent_from,
    )
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
