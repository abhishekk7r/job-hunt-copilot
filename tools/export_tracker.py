#!/usr/bin/env python3
"""Export tracker: One-way export from harness.db to job_search_tracker.csv.

Exports the system of record (harness.db) into upstream's canonical 14-column CSV
so that upstream tools (/outcome, /gmail-sync, /notion-sync, /html-report) keep working.

Usage:
    python3 tools/export_tracker.py [--db PATH] [--out PATH]
"""

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HEADER = [
    "date",
    "company",
    "sector",
    "role",
    "role_type",
    "channel",
    "status",
    "contact_person",
    "fit_rating",
    "notes",
    "cv_file",
    "cover_letter_file",
    "source",
    "deadline",
]

STATUS_MAP = {
    "APPLIED": "applied",
    "TO_APPLY": "drafted",
    "BLOCKED_USER": "paused",
    "CONTACTED": "interview",
    "REJECTED": "rejected",
    "COMPANY_SITE_ONLY": "manual",
    "RANKED_OUT": "skipped",
    "HALTED": "paused",
}


def export_tracker(db_path: Path, out_path: Path) -> int:
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT company, role, platform, status, blocker_note, recruiter_name,
               date_applied, first_seen, rank_score, rank_reason,
               applied_with_resume, source, updated_at
        FROM jobs
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)

        for r in rows:
            date_val = r["date_applied"] or (r["first_seen"][:10] if r["first_seen"] else "")
            status_val = STATUS_MAP.get(r["status"], "drafted")
            fit = int(r["rank_score"]) if r["rank_score"] is not None else 75
            notes = r["blocker_note"] or r["rank_reason"] or ""

            writer.writerow([
                date_val,
                r["company"],
                "",  # sector
                r["role"],
                "Full-time",  # role_type
                r["platform"] or "Direct",
                status_val,
                r["recruiter_name"] or "",
                str(fit),
                notes,
                r["applied_with_resume"] or "",
                "",  # cover_letter_file
                r["source"] or r["platform"] or "scraper",
                "",  # deadline
            ])

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Export harness.db to job_search_tracker.csv")
    parser.add_argument("--db", default=os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db")), help="Path to harness.db")
    parser.add_argument("--out", default=str(REPO_ROOT / "job_search_tracker.csv"), help="Output CSV path")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_path = Path(args.out)

    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")

    count = export_tracker(db_path, out_path)
    print(f"Exported {count} jobs from {db_path.name} to {out_path.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
