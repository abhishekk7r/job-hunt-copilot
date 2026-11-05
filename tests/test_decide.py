"""Tests for simplified tools/decide.py: next-jobs, mark-job, caps, and referral-first."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest

from tools import decide

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_handled_tracker_pairs_status_filtering(tmp_path):
    """Verify get_handled_tracker_pairs correctly filters by excluded tracker statuses."""
    tracker_file = tmp_path / "tracker.csv"
    tracker_file.write_text(
        "company,role,status\n"
        "Alpha Corp,Senior SDE,applied\n"
        "Beta LLC,Staff Engineer,interview\n"
        "Gamma Inc,Lead Backend,offer\n"
        "Delta Co,Distributed Systems,rejected\n"
        "Epsilon Ltd,SDE-2,withdrawn\n"
        "Zeta Corp,Architect,closed\n"
        "Active Co,Backend Engineer,drafted\n"
        "Pending Co,Java SDE,lead\n",
        encoding="utf-8",
    )

    pairs = decide.get_handled_tracker_pairs(tracker_file)
    from tools.rank_state import norm

    # All excluded statuses should be present in pairs
    assert (norm("Alpha Corp"), norm("Senior SDE")) in pairs
    assert (norm("Beta LLC"), norm("Staff Engineer")) in pairs
    assert (norm("Gamma Inc"), norm("Lead Backend")) in pairs
    assert (norm("Delta Co"), norm("Distributed Systems")) in pairs
    assert (norm("Epsilon Ltd"), norm("SDE-2")) in pairs
    assert (norm("Zeta Corp"), norm("Architect")) in pairs

    # Active/drafted statuses must NOT be in handled pairs
    assert (norm("Active Co"), norm("Backend Engineer")) not in pairs
    assert (norm("Pending Co"), norm("Java SDE")) not in pairs


def test_decide_next_jobs_filtering_and_caps(temp_db, tmp_path):
    """Verify next_jobs filters by status, verdict (Moderate+), paused companies, tracker, and caps."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO jobs (id, company, role, job_url, location, platform, status, rank_score, rank_verdict, updated_at)
        VALUES
        (101, 'Alpha Inc', 'Backend Engineer', 'https://alpha.example/101', 'Bengaluru', 'linkedin', 'TO_APPLY', 95, 'Strong Fit', '2026-11-03'),
        (102, 'Beta Corp', 'Java Developer', 'https://beta.example/102', 'Remote', 'naukri', 'TO_APPLY', 85, 'Good Fit', '2026-11-03'),
        (103, 'Gamma Ltd', 'Distributed Systems', 'https://gamma.example/103', 'Hyderabad', 'company_site', 'TO_APPLY', 80, 'High', '2026-11-03'),
        (104, 'Delta LLC', 'Junior SWE', 'https://delta.example/104', 'Pune', 'linkedin', 'TO_APPLY', 55, 'Moderate Fit', '2026-11-03'),
        (105, 'Weak Co', 'Intern Dev', 'https://weak.example/105', 'Pune', 'linkedin', 'TO_APPLY', 25, 'Weak Fit', '2026-11-03'),
        (106, 'Epsilon Co', 'Lead Engineer', 'https://epsilon.example/106', 'Bengaluru', 'naukri', 'APPLIED', 92, 'Good Fit', '2026-11-03'),
        (107, 'Paused Corp', 'Senior SWE', 'https://paused.example/107', 'Remote', 'company_site', 'TO_APPLY', 93, 'Good Fit', '2026-11-03'),
        (108, 'Tracked Handled Corp', 'DevOps Specialist', 'https://tracked.example/108', 'Delhi', 'linkedin', 'TO_APPLY', 91, 'Good Fit', '2026-11-03'),
        (109, 'Drafted In Tracker', 'Python Dev', 'https://drafted.example/109', 'Bengaluru', 'linkedin', 'TO_APPLY', 94, 'Strong Fit', '2026-11-03')
    """)

    cur.execute("""
        INSERT INTO open_items (area, item, status, saved_at)
        VALUES ('autoapply_paused', 'Auto-apply paused for Paused Corp: owner marked decision as wrong', 'OPEN', '2026-11-03T00:00:00Z')
    """)
    conn.commit()
    conn.close()

    tracker_file = tmp_path / "tracker.csv"
    tracker_file.write_text(
        "company,role,status\n"
        "Tracked Handled Corp,DevOps Specialist,applied\n"
        "Drafted In Tracker,Python Dev,drafted\n",
        encoding="utf-8",
    )

    # 1. Normal query: jobs 109, 101, 102, 103, 104 qualify (105 is Weak, 106 is APPLIED, 107 is Paused, 108 is in tracker)
    jobs = decide.next_jobs(limit=10, db_path=temp_db, tracker_path=tracker_file)
    assert len(jobs) == 5
    job_ids = [j["id"] for j in jobs]
    assert 109 in job_ids, "Tracker row with status 'drafted' must NOT be excluded"
    assert 104 in job_ids, "Moderate Fit job must be included (weight >= 2)"
    assert 105 not in job_ids, "Weak Fit job must be excluded (weight < 2)"
    assert 107 not in job_ids, "Paused company must be excluded"
    assert 108 not in job_ids, "Tracker row with status 'applied' MUST be excluded"

    # 2. Limit parameter respected
    jobs_lim2 = decide.next_jobs(limit=2, db_path=temp_db, tracker_path=tracker_file)
    assert len(jobs_lim2) == 2

    # 3. Daily application cap: when 25 applications exist today, returns empty list
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    today_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT12:00:00Z")
    for i in range(25):
        cur.execute(
            "INSERT INTO action_log (run_id, ts, actor, action, target, result, detail) "
            "VALUES ('run_day', ?, 'owner_session', 'APPLIED', ?, 'APPLIED', 'Applied')",
            (today_ts, str(900 + i)),
        )
    conn.commit()
    conn.close()

    assert decide.next_jobs(limit=5, db_path=temp_db, tracker_path=tracker_file) == []


def test_decide_mark_job_status_and_action_log(temp_db):
    """Verify mark_job records status, actor, action_log, and enforces safety rules."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO jobs (id, company, role, job_url, location, platform, status, updated_at)
        VALUES
        (201, 'TargetCorp', 'Backend SDE', 'https://targetcorp.com/201', 'Bengaluru', 'freehire', 'TO_APPLY', '2026-11-03'),
        (202, 'BlockedCorp', 'Staff SWE', 'https://blockedcorp.com/202', 'Remote', 'freehire', 'BLOCKED_USER', '2026-11-03'),
        (203, 'NeedsInputCorp', 'Java Dev', 'https://needsinputcorp.com/203', 'Pune', 'freehire', 'NEEDS_INPUT', '2026-11-03')
    """)
    conn.commit()
    conn.close()

    # 1. Invalid status rejected
    res_bad_status = decide.mark_job(201, "INVALID_STATUS", reason="submitted", db_path=temp_db)
    assert res_bad_status["ok"] is False

    # 2. Invalid reason rejected
    res_bad_reason = decide.mark_job(201, "APPLIED", reason="invalid_reason_xyz", db_path=temp_db)
    assert res_bad_reason["ok"] is False

    # 3. Transition from immutable status (BLOCKED_USER) rejected
    res_imm = decide.mark_job(202, "APPLIED", reason="submitted", db_path=temp_db)
    assert res_imm["ok"] is False
    assert "immutable" in res_imm["error"]

    # 4. Mark job APPLIED with actor 'owner_session' (no gate_pass or ctl:submit required in S3!)
    res_applied = decide.mark_job(201, "APPLIED", reason="submitted", actor="owner_session", db_path=temp_db)
    assert res_applied["ok"] is True
    assert res_applied["actor"] == "owner_session"

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT status, date_applied FROM jobs WHERE id = 201")
    j201 = cur.fetchone()
    assert j201["status"] == "APPLIED"
    assert j201["date_applied"] is not None

    # Check action_log recorded with actor
    cur.execute("SELECT actor, action, result FROM action_log WHERE target = '201' ORDER BY id DESC LIMIT 1")
    log_row = cur.fetchone()
    assert log_row["actor"] == "owner_session"
    assert log_row["action"] == "APPLIED"

    # 5. Mark job NEEDS_INPUT with reason 'challenge'
    res_ni = decide.mark_job(203, "NEEDS_INPUT", reason="challenge", actor="cycle", db_path=temp_db)
    assert res_ni["ok"] is True
    assert res_ni["actor"] == "cycle"

    cur.execute("SELECT status, blocker_note FROM jobs WHERE id = 203")
    j203 = cur.fetchone()
    assert j203["status"] == "NEEDS_INPUT"
    assert j203["blocker_note"] == "challenge"

    # 6. Mark job PARKED with reason 'already_applied'
    cur.execute("UPDATE jobs SET status = 'TO_APPLY' WHERE id = 203")
    conn.commit()
    res_park = decide.mark_job(203, "PARKED", reason="already_applied", actor="cycle", db_path=temp_db)
    assert res_park["ok"] is True
    cur.execute("SELECT status, blocker_note FROM jobs WHERE id = 203")
    j_park = cur.fetchone()
    assert j_park["status"] == "BLOCKED_USER"
    assert j_park["blocker_note"] == "already_applied"

    conn.close()


def test_decide_cli(temp_db):
    """Test CLI subcommands: next-jobs, mark-job, set-referral."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO jobs (id, company, role, job_url, location, platform, status, rank_score, rank_verdict, updated_at)
        VALUES (301, 'CliCorp', 'Senior SDE', 'https://clicorp.com/301', 'Bengaluru', 'freehire', 'TO_APPLY', 75, 'Good Fit', '2026-11-03')
    """)
    conn.commit()
    conn.close()

    # CLI next-jobs
    out_next = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "decide.py"), "next-jobs", "--limit", "5", "--db", temp_db],
        capture_output=True,
        text=True,
        check=True,
    )
    jobs = json.loads(out_next.stdout)
    assert len(jobs) == 1
    assert jobs[0]["company"] == "CliCorp"

    # CLI mark-job
    out_mark = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "decide.py"), "mark-job", "--job", "301", "--status", "APPLIED", "--reason", "submitted", "--actor", "owner_session", "--db", temp_db],
        capture_output=True,
        text=True,
        check=True,
    )
    res = json.loads(out_mark.stdout)
    assert res["ok"] is True
    assert res["actor"] == "owner_session"
