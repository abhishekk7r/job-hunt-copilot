#!/usr/bin/env python3
"""Find-Apply-Reach decision engine and job application queue manager.

Simplified model:
- next-jobs: selects TO_APPLY jobs matching threshold (Moderate+ fit), respecting caps and referral-first.
- mark-job: records job status transitions (APPLIED, WOULD_SUBMIT, NEEDS_INPUT, PARKED) with caps, safety checks, and actor tracking.
- set-referral: toggles referral-first flag on research notes.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.rank_state import VERDICT_WEIGHTS

DAILY_APPLICATION_CAP = 25
RUN_APPLICATION_CAP = 8
EXCLUDED_TRACKER_STATUSES = {"applied", "interview", "offer", "rejected", "withdrawn", "closed"}
DO_NOT_DOWNGRADE_STATUSES = {"APPLIED", "BLOCKED_USER", "CONTACTED", "COMPANY_SITE_ONLY", "OUTREACH_DRAFTED"}
VALID_MARK_REASONS = {
    "hard_stop", "escalated", "gate_failed", "shadow_filled", "submitted",
    "login_required", "cap_reached", "challenge", "already_applied"
}
VALID_JOB_STATUSES = {"APPLIED", "WOULD_SUBMIT", "NEEDS_INPUT", "PARKED"}


def get_handled_tracker_pairs(tracker_path: Optional[Path] = None) -> Set[Tuple[str, str]]:
    from tools.rank_state import norm
    t_path = tracker_path or (REPO_ROOT / "job_search_tracker.csv")
    if not t_path.exists():
        return set()
    pairs: Set[Tuple[str, str]] = set()
    try:
        with open(t_path, "r", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                if str(row.get("status") or "").strip().lower() in EXCLUDED_TRACKER_STATUSES:
                    c, r = str(row.get("company") or "").strip(), str(row.get("role") or "").strip()
                    if c and r:
                        pairs.add((norm(c), norm(r)))
    except Exception:
        pass
    return pairs


def next_jobs(
    limit: int = 5,
    run_id: Optional[str] = None,
    db_path: Optional[str] = None,
    tracker_path: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    target_db = db_path or os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))
    if not os.path.exists(target_db):
        return []

    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kill_switch'")
        if cur.fetchone():
            cur.execute('SELECT "on" FROM kill_switch WHERE id = 1')
            if (ks := cur.fetchone()) and ks[0] == 1:
                return []

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='action_log'")
        today_count, run_count = 0, 0
        if cur.fetchone():
            cur.execute("SELECT COUNT(*) FROM action_log WHERE (action IN ('apply', 'job_applied', 'APPLIED') OR result = 'APPLIED') AND date(ts) = date('now')")
            today_count = int(cur.fetchone()[0])
            if today_count >= DAILY_APPLICATION_CAP:
                return []
            if run_id:
                cur.execute("SELECT COUNT(*) FROM action_log WHERE (action IN ('apply', 'job_applied', 'APPLIED') OR result = 'APPLIED') AND run_id = ?", (run_id,))
                run_count = int(cur.fetchone()[0])
                if run_count >= RUN_APPLICATION_CAP:
                    return []

        eff_limit = min(limit, max(0, DAILY_APPLICATION_CAP - today_count))
        if run_id:
            eff_limit = min(eff_limit, max(0, RUN_APPLICATION_CAP - run_count))
        if eff_limit <= 0:
            return []

        paused_companies: set = set()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='open_items'")
        if cur.fetchone():
            cur.execute("SELECT item FROM open_items WHERE area = 'autoapply_paused' AND status = 'OPEN'")
            for r in cur.fetchall():
                raw = str(r["item"] or "")
                comp = raw.split("Auto-apply paused for ")[1].split(":")[0].strip().lower() if "Auto-apply paused for " in raw else raw.strip().lower()
                if comp:
                    paused_companies.add(comp)

        from tools.rank_state import norm
        tracker_set = get_handled_tracker_pairs(tracker_path)

        cur.execute("SELECT id, company, role, job_url, location, platform, rank_score, rank_verdict, salary_lpa FROM jobs WHERE status = 'TO_APPLY' ORDER BY rank_score DESC NULLS LAST, id ASC")
        selected: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            if len(selected) >= eff_limit:
                break
            comp, role = str(r["company"] or "").strip(), str(r["role"] or "").strip()
            verdict = str(r["rank_verdict"] or "").strip().lower()
            if VERDICT_WEIGHTS.get(verdict, -1) < 2:
                continue
            c_norm = comp.lower()
            if any(p in c_norm or c_norm in p for p in paused_companies):
                continue
            if (norm(comp), norm(role)) in tracker_set:
                continue

            from tools.research_note import is_referral_first
            if is_referral_first(r["id"], reports_dir=reports_dir):
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='outreach_queue'")
                if cur.fetchone():
                    cur.execute("SELECT 1 FROM outreach_queue WHERE job_id = ? AND approval_status != 'SKIPPED_BY_USER' LIMIT 1", (r["id"],))
                    if not cur.fetchone():
                        continue
                else:
                    continue

            selected.append({
                "id": r["id"], "company": comp, "role": role, "job_url": r["job_url"],
                "location": r["location"] or "India", "platform": r["platform"],
                "rank_score": r["rank_score"], "rank_verdict": r["rank_verdict"], "salary_lpa": r["salary_lpa"],
            })
        return selected
    finally:
        conn.close()


def mark_job(
    job_id: int,
    status: str,
    reason: str = "",
    note: str = "",
    run_id: Optional[str] = None,
    actor: str = "owner_session",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    reason_code = reason or note
    if reason_code and reason_code not in VALID_MARK_REASONS:
        return {"ok": False, "error": f"Invalid reason code: {reason_code!r}. Must be one of {sorted(VALID_MARK_REASONS)}"}
    if status not in VALID_JOB_STATUSES:
        return {"ok": False, "error": f"Invalid status: {status!r}. Must be one of {sorted(VALID_JOB_STATUSES)}"}

    target_db = db_path or os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kill_switch'")
        if cur.fetchone():
            cur.execute('SELECT "on" FROM kill_switch WHERE id = 1')
            if (ks := cur.fetchone()) and ks[0] == 1:
                return {"ok": False, "error": "Kill switch engaged"}

        cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cur.fetchone()
        if not job_row:
            return {"ok": False, "error": f"Job {job_id} not found"}

        current_status = job_row["status"] or ""
        company = job_row["company"]

        if current_status in DO_NOT_DOWNGRADE_STATUSES:
            return {"ok": False, "error": f"Cannot transition job {job_id} from immutable status '{current_status}'"}
        if current_status not in ("TO_APPLY", "NEEDS_INPUT"):
            return {"ok": False, "error": f"Cannot transition job {job_id} from status '{current_status}' (must be TO_APPLY or NEEDS_INPUT)"}

        if status == "APPLIED":
            cur.execute("SELECT COUNT(*) FROM action_log WHERE (action IN ('apply', 'job_applied', 'APPLIED') OR result = 'APPLIED') AND date(ts) = date('now')")
            today_count = int(cur.fetchone()[0])
            if today_count >= DAILY_APPLICATION_CAP:
                return {"ok": False, "error": f"Daily application cap reached ({today_count}/{DAILY_APPLICATION_CAP})"}

            if run_id:
                cur.execute("SELECT COUNT(*) FROM action_log WHERE (action IN ('apply', 'job_applied', 'APPLIED') OR result = 'APPLIED') AND run_id = ?", (run_id,))
                run_count = int(cur.fetchone()[0])
                if run_count >= RUN_APPLICATION_CAP:
                    return {"ok": False, "error": f"Run application cap reached ({run_count}/{RUN_APPLICATION_CAP})"}

            cur.execute("UPDATE jobs SET status = 'APPLIED', date_applied = ?, updated_at = ? WHERE id = ?", (today_date, now_ts, job_id))
        elif status == "NEEDS_INPUT":
            cur.execute("UPDATE jobs SET status = 'NEEDS_INPUT', blocker_note = ?, updated_at = ? WHERE id = ?", (reason_code, now_ts, job_id))
        elif status == "PARKED":
            cur.execute("UPDATE jobs SET status = 'BLOCKED_USER', blocker_note = ?, updated_at = ? WHERE id = ?", (reason_code, now_ts, job_id))

        cur.execute(
            "INSERT INTO action_log (run_id, ts, actor, action, target, result, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id or "", now_ts, actor, status, str(job_id), status, reason_code or f"job {job_id} at {company}"),
        )
        conn.commit()
        return {"ok": True, "job_id": job_id, "company": company, "status": status, "reason": reason_code, "actor": actor}
    finally:
        conn.close()


def set_referral(
    job_id: int,
    on: bool = True,
    reports_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    from tools.research_note import set_referral_flag
    ok = set_referral_flag(job_id, on=on, reports_dir=reports_dir)
    return {"ok": ok, "job_id": job_id, "referral_first": on}


def main():
    parser = argparse.ArgumentParser(description="Find-Apply-Reach decision engine and job queue CLI")
    subparsers = parser.add_subparsers(dest="command")

    next_p = subparsers.add_parser("next-jobs", help="Select next jobs ready for apply")
    next_p.add_argument("--limit", type=int, default=5, help="Maximum number of jobs")
    next_p.add_argument("--run-id", type=str, default=None, help="Current cycle Run ID")
    next_p.add_argument("--db", type=str, default=None, help="Database path")
    next_p.add_argument("--tracker", type=str, default=None, help="Path to tracker CSV")

    mark_p = subparsers.add_parser("mark-job", help="Record job application attempt result")
    mark_p.add_argument("--job", type=int, required=True, help="Job ID")
    mark_p.add_argument("--status", type=str, required=True, choices=sorted(list(VALID_JOB_STATUSES)))
    mark_p.add_argument("--reason", type=str, choices=sorted(list(VALID_MARK_REASONS)), default=None, help="Enumerated reason code")
    mark_p.add_argument("--note", type=str, default="", help="Detail or blocker note (deprecated, use --reason)")
    mark_p.add_argument("--actor", type=str, choices=["owner_session", "cycle"], default="owner_session", help="Action initiator")
    mark_p.add_argument("--run-id", type=str, default=None, help="Current cycle Run ID")
    mark_p.add_argument("--db", type=str, default=None, help="Database path")

    ref_p = subparsers.add_parser("set-referral", help="Toggle referral-first flag for a job")
    ref_p.add_argument("--job", type=int, required=True, help="Job ID")
    ref_p.add_argument("--on", action="store_true", default=None, help="Turn referral_first ON")
    ref_p.add_argument("--off", action="store_true", default=None, help="Turn referral_first OFF")

    args = parser.parse_args()

    if args.command == "next-jobs":
        tracker_p = Path(args.tracker) if args.tracker else None
        jobs = next_jobs(limit=args.limit, run_id=args.run_id, db_path=args.db, tracker_path=tracker_p)
        print(json.dumps(jobs, indent=2))
        sys.exit(0)

    if args.command == "mark-job":
        actor = getattr(args, "actor", "owner_session")
        res = mark_job(job_id=args.job, status=args.status, reason=args.reason or args.note, run_id=args.run_id, actor=actor, db_path=args.db)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("ok") else 1)

    if args.command == "set-referral":
        on_val = False if args.off else True
        res = set_referral(args.job, on=on_val)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("ok") else 1)

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
