#!/usr/bin/env python3
"""Save scored LinkedIn candidates from stdin JSON into contacts (PROPOSED).

stdin: {"company": "Globex", "candidates": [{"name","title","profile_url","current_company",
        "connection_degree","mutual_connections","location"}, ...]}
Job context (applied or not) is read from the jobs table, never trusted from input.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.contacts import save_ranked_contacts  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    payload = json.load(sys.stdin)
    company = str(payload.get("company", "")).strip()
    db = os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))
    conn = sqlite3.connect(db)
    job_id = payload.get("job_id")
    if job_id is not None:
        row = conn.execute("SELECT id, role, company, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row and not company:
            company = row[2]
    else:
        row = conn.execute("SELECT id, role, company, status FROM jobs WHERE lower(company) = lower(?) AND status = 'APPLIED' LIMIT 1",
                           (company,)).fetchone()
        if not row:
            row = conn.execute("SELECT id, role, company, status FROM jobs WHERE lower(company) = lower(?) LIMIT 1", (company,)).fetchone()
    conn.close()

    actual_job_id = row[0] if row else None
    role = row[1] if row else ""
    is_applied = bool(row and row[3] == "APPLIED")

    saved = save_ranked_contacts(
        job_id=actual_job_id, company=company, candidates=payload.get("candidates", []),
        db_path=db, job_applied=is_applied, role=role, top_n=4,
    )
    print(json.dumps({"saved": len(saved), "names": [c["name"] for c in saved]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
