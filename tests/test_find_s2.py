"""Tests for FIND step (S2): verdict weights, threshold consistency, research notes, referral flag."""

from pathlib import Path
import sqlite3
import pytest

from tools.rank_state import VERDICT_WEIGHTS
from tools.decide import next_jobs, set_referral
from tools.research_note import (
    write_research_note,
    read_research_note,
    is_referral_first,
    set_referral_flag,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_single_verdict_weights_definition():
    """Ensure VERDICT_WEIGHTS is only defined once in tools/rank_state.py."""
    definitions = []
    for p in (REPO_ROOT / "tools").glob("*.py"):
        content = p.read_text(encoding="utf-8")
        for idx, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("VERDICT_WEIGHTS") and "=" in stripped and not stripped.startswith("VERDICT_WEIGHTS.get"):
                definitions.append((p.name, idx, stripped))

    assert len(definitions) == 1, f"Expected VERDICT_WEIGHTS defined once, found: {definitions}"
    assert definitions[0][0] == "rank_state.py"


def test_threshold_consistency_returns_moderate_fit(temp_db):
    """next_jobs must return Moderate Fit jobs (weight >= 2) bridged into jobs table."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO jobs (company, role, job_url, location, platform, rank_score, rank_verdict, status, updated_at)
           VALUES ('TestCo', 'Backend SDE', 'https://example.com/job/1', 'Remote, India', 'freehire', 52, 'Moderate Fit', 'TO_APPLY', datetime('now'))"""
    )
    conn.commit()
    conn.close()

    jobs = next_jobs(limit=10, db_path=temp_db)
    assert len(jobs) == 1
    assert jobs[0]["company"] == "TestCo"
    assert jobs[0]["rank_verdict"] == "Moderate Fit"


def test_threshold_filters_weak_fit(temp_db):
    """next_jobs must filter out Weak Fit jobs (weight 1 < 2)."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO jobs (company, role, job_url, location, platform, rank_score, rank_verdict, status, updated_at)
           VALUES ('WeakCo', 'Junior Dev', 'https://example.com/job/2', 'Remote, India', 'freehire', 32, 'Weak Fit', 'TO_APPLY', datetime('now'))"""
    )
    conn.commit()
    conn.close()

    jobs = next_jobs(limit=10, db_path=temp_db)
    assert len(jobs) == 0


def test_research_note_writer_and_defaults(tmp_path):
    """Writing research notes with defaults and referral_first rules."""
    reports_dir = tmp_path / "reports" / "jobs"

    # High score >= 80 -> referral_first defaults to True
    note_path_1 = write_research_note(
        job_id=101,
        company="Stripe",
        role="Staff Engineer",
        apply_url="https://stripe.com/jobs/101",
        rank_score=85,
        summary="High scale payment infrastructure role.",
        must_have="Distributed systems, Java/Go",
        nice_to_have="Payment processing experience",
        fit_reasons="Strong distributed systems match",
        gaps="None",
        ats_type="Greenhouse",
        login_required="no",
        pitch_angle="10+ years scaling payment gateways",
        reports_dir=reports_dir,
    )
    assert note_path_1.is_file()
    assert is_referral_first(101, reports_dir=reports_dir) is True

    parsed_1 = read_research_note(101, reports_dir=reports_dir)
    assert parsed_1 is not None
    assert parsed_1["company"] == "Stripe"
    assert parsed_1["ats_type"] == "Greenhouse"
    assert parsed_1["referral_first"] is True
    assert parsed_1["rank_score"] == 85

    # Moderate score < 80 -> referral_first defaults to False
    write_research_note(
        job_id=102,
        company="Acme",
        role="Backend Engineer",
        rank_score=65,
        reports_dir=reports_dir,
    )
    assert is_referral_first(102, reports_dir=reports_dir) is False


def test_referral_first_skipping_and_toggle(temp_db, tmp_path):
    """referral_first jobs are skipped by next_jobs until outreach is queued or flag is turned off."""
    reports_dir = tmp_path / "reports" / "jobs"
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO jobs (id, company, role, job_url, location, platform, rank_score, rank_verdict, status, updated_at)
           VALUES (201, 'TopCo', 'Principal Engineer', 'https://topco.com/job/201', 'India', 'linkedin', 90, 'Strong Fit', 'TO_APPLY', datetime('now'))"""
    )
    conn.commit()

    # Create note with referral_first: yes
    write_research_note(
        job_id=201,
        company="TopCo",
        role="Principal Engineer",
        rank_score=90,
        reports_dir=reports_dir,
    )

    # 1. next_jobs should skip because referral_first is True and no outreach is queued
    res = next_jobs(limit=10, db_path=temp_db, reports_dir=reports_dir)
    assert len(res) == 0

    # 2. Toggle referral off via set_referral
    set_res = set_referral(201, on=False, reports_dir=reports_dir)
    assert set_res["ok"] is True
    assert set_res["referral_first"] is False

    res = next_jobs(limit=10, db_path=temp_db, reports_dir=reports_dir)
    assert len(res) == 1
    assert res[0]["id"] == 201

    # 3. Toggle referral back on
    set_referral(201, on=True, reports_dir=reports_dir)
    res = next_jobs(limit=10, db_path=temp_db, reports_dir=reports_dir)
    assert len(res) == 0

    # 4. Draft outreach in outreach_queue -> now next_jobs should return it
    cur.execute(
        """INSERT INTO outreach_queue (job_id, company, role, recruiter_name, recruiter_linkedin, channel, rendered_message, char_count, approval_status)
           VALUES (201, 'TopCo', 'Principal Engineer', 'Jane Doe', 'https://linkedin.com/in/janedoe', 'LinkedIn DM', 'Hi Jane...', 10, 'PENDING_MOBILE_REVIEW')"""
    )
    conn.commit()
    conn.close()

    res = next_jobs(limit=10, db_path=temp_db, reports_dir=reports_dir)
    assert len(res) == 1
    assert res[0]["id"] == 201
