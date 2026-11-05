#!/usr/bin/env python3
"""Bridge: Synchronizes upstream scraper/ranking state to SQLite harness.db.

Reads ranked entries from job_scraper/seen_jobs.json using upstream's rank_state.py,
filters against candidate criteria, and upserts jobs to harness.db without downgrading
jobs already in progress (e.g. APPLIED, BLOCKED_USER).

Usage:
    python3 tools/bridge.py [--state PATH] [--db PATH] [--min-verdict VERDICT] [--dry-run]
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from harness.config import identity_capsule
from tools import excluded_companies
from tools.job_key import make_key
from tools.rank_state import load_state, VERDICT_WEIGHTS

DO_NOT_DOWNGRADE_STATUSES = {"APPLIED", "BLOCKED_USER", "CONTACTED", "COMPANY_SITE_ONLY", "OUTREACH_DRAFTED"}


def parse_salary_lpa(val: Any) -> Optional[int]:
    """Extract numeric LPA from salary string or number if present."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    val_str = str(val).strip().lower()
    # Try parsing e.g. "25-30 lpa", "28 lpa", "2500000"
    import re
    m = re.search(r"(\d+)\s*(?:-|to)?\s*(\d+)?\s*lpa", val_str)
    if m:
        if m.group(2):
            return int(m.group(2))  # top of range
        return int(m.group(1))
    m2 = re.search(r"(\d+)", val_str)
    if m2:
        num = int(m2.group(1))
        if num > 100000:
            return int(num / 100000)
        return num
    return None


def entry_passes_filters(
    entry: Dict[str, Any],
    min_verdict: str,
    capsule: Dict[str, Any]
) -> Tuple[bool, str]:
    verdict = str(entry.get("rank_verdict", "")).strip().lower()
    min_v = min_verdict.strip().lower()

    target_weight = VERDICT_WEIGHTS.get(min_v, 2)
    actual_weight = VERDICT_WEIGHTS.get(verdict, -1)

    if actual_weight < target_weight:
        return False, f"Verdict '{verdict}' below minimum threshold '{min_verdict}'"

    salary_val = entry.get("salary_lpa") or entry.get("salary")
    salary_num = parse_salary_lpa(salary_val)
    floor = capsule.get("min_ctc_lpa", 22)
    if salary_num is not None and salary_num < floor:
        return False, f"Salary {salary_num} LPA below floor {floor} LPA"

    stack = f"{entry.get('stack', '')} {entry.get('title', '')} {entry.get('role', '')}".lower()
    excluded = [s.lower() for s in capsule.get("excluded_stack", ["android", "ios", "flask", "react-only"])]
    for bad in excluded:
        if bad in stack:
            return False, f"Excluded stack keyword '{bad}' found"

    return True, "Passed"


def bridge_seen_jobs(
    state_path: Path,
    db_path: Path,
    min_verdict: str = "Medium",
    dry_run: bool = False
) -> Dict[str, Any]:
    doc, seen = load_state(state_path)
    capsule = identity_capsule()

    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    counts = {
        "total_seen": len(seen),
        "eligible": 0,
        "inserted": 0,
        "updated": 0,
        "ranked_out": 0,
        "skipped_existing_active": 0,
    }

    now_str = datetime.utcnow().isoformat()
    excl = excluded_companies.load()

    for key, entry in seen.items():
        if not isinstance(entry, dict):
            continue

        company = str(entry.get("company", "")).strip()
        role = str(entry.get("title") or entry.get("role", "")).strip()
        job_url = str(entry.get("url") or entry.get("job_url", "")).strip()
        if not company or not role or not job_url:
            continue

        if excluded_companies.is_excluded(company, excl):
            continue
        source_key = entry.get("source_key") or make_key(company, role, job_url)
        passes, reason = entry_passes_filters(entry, min_verdict, capsule)

        salary_num = parse_salary_lpa(entry.get("salary_lpa") or entry.get("salary"))
        stack_str = str(entry.get("stack", "")).strip()
        source = str(entry.get("source", "scraper")).strip()
        rank_score = entry.get("rank_score")
        rank_verdict = entry.get("rank_verdict")
        rank_reason = entry.get("rank_reason", "")

        # Check existing row
        cur.execute("SELECT id, status, outreach_state FROM jobs WHERE source_key = ? OR job_url = ?", (source_key, job_url))
        existing = cur.fetchone()

        if passes:
            counts["eligible"] += 1
            target_status = "TO_APPLY"
        else:
            counts["ranked_out"] += 1
            target_status = "RANKED_OUT"

        if existing:
            current_status = existing["status"]
            # Never downgrade in-progress or completed jobs
            if current_status in DO_NOT_DOWNGRADE_STATUSES:
                counts["skipped_existing_active"] += 1
                new_status = current_status
            else:
                new_status = target_status

            if not dry_run:
                cur.execute("""
                    UPDATE jobs
                    SET company = ?, role = ?, job_url = ?, status = ?,
                        salary_lpa = COALESCE(?, salary_lpa),
                        stack_keywords = CASE WHEN ? != '' THEN ? ELSE stack_keywords END,
                        source = ?, source_key = ?,
                        rank_score = COALESCE(?, rank_score),
                        rank_verdict = COALESCE(?, rank_verdict),
                        rank_reason = CASE WHEN ? != '' THEN ? ELSE rank_reason END,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    company, role, job_url, new_status,
                    salary_num, stack_str, stack_str, source, source_key,
                    rank_score, rank_verdict, rank_reason, rank_reason,
                    now_str, existing["id"]
                ))
            counts["updated"] += 1
        else:
            if not dry_run:
                cur.execute("""
                    INSERT INTO jobs (
                        company, role, job_url, platform, tier, status,
                        salary_lpa, stack_keywords, source, source_key,
                        rank_score, rank_verdict, rank_reason,
                        first_seen, updated_at
                    )
                    VALUES (?, ?, ?, ?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    company, role, job_url, source, target_status,
                    salary_num, stack_str, source, source_key,
                    rank_score, rank_verdict, rank_reason,
                    now_str, now_str
                ))
            counts["inserted"] += 1

    if not dry_run:
        conn.commit()
    conn.close()

    return counts


def main():
    parser = argparse.ArgumentParser(description="Bridge scraper state into harness DB")
    parser.add_argument("--state", default=str(REPO_ROOT / "job_scraper" / "seen_jobs.json"), help="Path to seen_jobs.json")
    parser.add_argument("--db", default=os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db")), help="Path to harness.db")
    parser.add_argument("--min-verdict", default="Medium", help="Minimum rank verdict threshold (default: Medium)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying DB")
    args = parser.parse_args()

    state_path = Path(args.state)
    db_path = Path(args.db)

    if not state_path.exists():
        sys.exit(f"State file not found: {state_path}")
    if not db_path.exists() and not args.dry_run:
        sys.exit(f"Database not found: {db_path} - run migration first")

    counts = bridge_seen_jobs(state_path, db_path, min_verdict=args.min_verdict, dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Bridge completed: {counts['inserted']} inserted, {counts['updated']} updated, {counts['eligible']} eligible, {counts['ranked_out']} ranked out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
