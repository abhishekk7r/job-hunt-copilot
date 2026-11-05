#!/usr/bin/env python3
"""Generates phone-readable daily digest from harness.db.

Usage:
  python3 tools/digest.py [--date YYYY-MM-DD] [--output path/to/digest.md]
"""

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_db_path() -> str:
    return os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))


def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


def generate_digest_content(conn: sqlite3.Connection, target_date: str) -> str:
    # 1. Kill Switch
    ks_row = q(conn, "SELECT \"on\", reason, ts FROM kill_switch WHERE id = 1")
    ks_on = bool(ks_row[0]["on"]) if ks_row else False
    ks_reason = ks_row[0]["reason"] if ks_row else ""
    ks_status = f"🔴 **HALTED (Kill Switch ON)** - {ks_reason}" if ks_on else "🟢 **Active (Kill Switch OFF)**"

    # 2. Jobs Breakdown
    all_jobs = q(conn, "SELECT * FROM jobs ORDER BY rank_score DESC, updated_at DESC")
    applied_jobs = [j for j in all_jobs if j.get("status") == "APPLIED"]
    blocked_jobs = [j for j in all_jobs if j.get("status") == "BLOCKED_USER"]
    ranked_jobs = [j for j in all_jobs if j.get("rank_score") is not None]
    to_apply_jobs = [j for j in all_jobs if j.get("status") == "TO_APPLY"]
    ranked_out_jobs = [j for j in all_jobs if j.get("status") == "RANKED_OUT"]

    # 3. Outreach Queue
    outreach = q(conn, "SELECT * FROM outreach_queue ORDER BY id DESC")
    pending_outreach = [o for o in outreach if o.get("approval_status") == "PENDING_MOBILE_REVIEW"]

    # 4. Run Log Errors
    runs = q(conn, "SELECT * FROM run_log ORDER BY id DESC LIMIT 10")
    halted_runs = [r for r in runs if r.get("status") == "HALTED" or r.get("halted_reason")]

    md = []
    md.append(f"# Daily Job Search Digest — {target_date}\n")
    md.append(f"**System Status:** {ks_status}\n")

    # Funnel Summary
    md.append("## 📊 Pipeline Funnel")
    md.append(f"- **To Apply:** {len(to_apply_jobs)}")
    md.append(f"- **Applied:** {len(applied_jobs)}")
    md.append(f"- **Blocked (Needs You):** {len(blocked_jobs)}")
    md.append(f"- **Outreach Drafts Pending:** {len(pending_outreach)}")
    md.append(f"- **Ranked Out / Skipped:** {len(ranked_out_jobs)}")
    md.append("")

    # Needs You / Blocked Applications
    md.append("## ⚠️ Blocked Applications (Action Required)")
    if blocked_jobs:
        for j in blocked_jobs:
            blocker = j.get("blocker_note") or "Unknown requirement"
            md.append(f"### #{j['id']} {j['company']} — {j['role']}")
            md.append(f"- **Blocker:** {blocker}")
            md.append(f"- **Action Needed:** Please review form manually and answer required question.")
            md.append(f"- **Link:** [{j.get('job_url', 'Posting')}]({j.get('job_url', '#')})")
            md.append("")
    else:
        md.append("No applications currently blocked.\n")

    # Outreach Queue Drafts
    md.append("## 📬 Outreach Drafts (Pending Mobile / Dashboard Review)")
    if pending_outreach:
        for o in pending_outreach:
            md.append(f"### [Draft #{o['id']}] {o['company']} → {o.get('recruiter_name', 'Recruiter')}")
            md.append(f"- **Channel:** {o.get('channel', 'LinkedIn DM')} ({o.get('char_count', 0)} chars)")
            md.append(f"- **Approval Status:** `{o.get('approval_status')}`")
            md.append(f"> {o.get('rendered_message', '')}\n")
    else:
        md.append("No outreach drafts pending review.\n")

    # New Ranked Jobs
    md.append("## 🎯 Top Ranked Jobs")
    if ranked_jobs:
        for j in ranked_jobs[:10]:
            score = j.get("rank_score", "–")
            verdict = j.get("rank_verdict", "")
            verdict_str = f" [{verdict}]" if verdict else ""
            md.append(f"- **{j['company']}** — {j['role']} (Score: {score}{verdict_str}) | Status: `{j.get('status')}`")
    else:
        md.append("No ranked jobs recorded.\n")

    # Skipped / Ranked Out
    md.append("\n## ⏭️ Skipped & Ranked Out")
    if ranked_out_jobs:
        for j in ranked_out_jobs[:10]:
            reason = j.get("rank_reason") or "Below score threshold"
            md.append(f"- **{j['company']}** — {j['role']} | Reason: {reason}")
    else:
        md.append("No jobs filtered out.\n")

    # Halted Runs / Errors
    md.append("\n## 🛑 Halted Runs & System Errors")
    if halted_runs:
        for r in halted_runs:
            reason = r.get("halted_reason") or "Unknown halt"
            started = (r.get("started_at") or "")[:19]
            md.append(f"- `{started}` **{r.get('mode', 'run')}** [{r.get('status')}]: {reason}")
    else:
        md.append("No execution errors or halted runs recorded.\n")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="Generate daily job search markdown digest.")
    parser.add_argument("--date", default=datetime.utcnow().strftime("%Y-%m-%d"), help="Target date YYYY-MM-DD")
    parser.add_argument("--output", default="", help="Optional output filepath")
    args = parser.parse_args()

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row

    content = generate_digest_content(conn, args.date)
    conn.close()

    out_path = Path(args.output) if args.output else (REPO_ROOT / "reports" / f"digest-{args.date}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"Digest generated successfully: {out_path}")


if __name__ == "__main__":
    main()
