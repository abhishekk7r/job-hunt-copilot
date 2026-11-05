"""Regression tests for Bugs 1-7 and Coordination features in harness/server.py."""

import json
import os
import sqlite3
import pytest
from pathlib import Path

from harness.server import (
    add_sourced_job,
    claim_next_job_for_claude,
    update_application_state,
    draft_outreach_for_mobile_review,
    process_mobile_approvals,
    mark_outreach_sent,
    acquire_lock,
    release_lock,
    start_session_with_capsule,
    get_or_save_screening_answer,
    get_application_answers,
    mark_application_answers_submitted,
    get_conn,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_bug1_add_sourced_job_stores_salary_and_stack(temp_db):
    """Bug 1: add_sourced_job validates salary_lpa & stack_keywords and stores them in DB."""
    res_str = add_sourced_job(
        company="Stripe",
        role="Backend Engineer",
        job_url="https://stripe.com/jobs/12345",
        platform="Direct",
        tier=1,
        salary_lpa=35,
        stack_keywords="Java, Spring Boot, Kafka"
    )
    res = json.loads(res_str)
    assert res["added"] is True
    job_id = res["job_id"]

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT salary_lpa, stack_keywords, source_key FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    assert row["salary_lpa"] == 35
    assert "Kafka" in row["stack_keywords"]
    assert row["source_key"] is not None
    conn.close()


def test_bug2_outreach_honors_custom_opener_and_wording(temp_db):
    """Bug 2: Outreach templates honor custom_opener and use 'I've applied' phrasing."""
    add_sourced_job(
        company="Razorpay",
        role="SDE-2",
        job_url="https://razorpay.com/careers/555",
        platform="Direct",
        tier=1,
        salary_lpa=28
    )
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT id FROM jobs WHERE company = 'Razorpay'")
    job_id = cur.fetchone()[0]
    conn.close()

    # Case A: Default wording
    res_default = json.loads(draft_outreach_for_mobile_review(
        job_id=job_id,
        recruiter_name="Priya Sharma",
        recruiter_title="Talent Partner",
        recruiter_linkedin="https://linkedin.com/in/priya",
        connection_degree=1
    ))
    assert "I've applied for the SDE-2 position" in res_default["rendered_message"]

    # Case B: Custom opener honored
    custom = "Following up on my direct application for the SDE-2 team"
    res_custom = json.loads(draft_outreach_for_mobile_review(
        job_id=job_id,
        recruiter_name="Priya Sharma",
        recruiter_title="Talent Partner",
        recruiter_linkedin="https://linkedin.com/in/priya",
        connection_degree=1,
        custom_opener=custom
    ))
    assert custom in res_custom["rendered_message"]


def test_bug3_drafting_does_not_overwrite_job_status(temp_db):
    """Bug 3: drafting outreach preserves jobs.status and sets outreach_state='DRAFTED'."""
    add_sourced_job(
        company="Swiggy",
        role="Senior Backend Engineer",
        job_url="https://swiggy.com/jobs/999",
        platform="Direct",
        tier=1,
        salary_lpa=32
    )
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT id FROM jobs WHERE company = 'Swiggy'")
    job_id = cur.fetchone()[0]

    # Put job in APPLIED status
    cur.execute("UPDATE jobs SET status = 'APPLIED' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    # Draft outreach
    res = json.loads(draft_outreach_for_mobile_review(
        job_id=job_id,
        recruiter_name="Rahul Verma",
        recruiter_title="Engineering Manager",
        recruiter_linkedin="https://linkedin.com/in/rahul",
        connection_degree=3
    ))
    assert res["queued_for_mobile_review"] is True

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT status, outreach_state, last_status_before_outreach FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    # status must stay APPLIED (not overwritten to OUTREACH_DRAFTED)
    assert row["status"] == "APPLIED"
    assert row["outreach_state"] == "DRAFTED"
    assert row["last_status_before_outreach"] == "APPLIED"
    conn.close()


def test_bug4_global_db_backed_budget_and_hard_stop(temp_db):
    """Bug 4: Session budget is DB-backed in budgets table and shared across callers."""
    session_res = json.loads(start_session_with_capsule("CLAUDE", session_id="test_sess_1"))
    sess_id = session_res["session_id"]
    assert sess_id == "test_sess_1"

    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    # Simulate 19 prior calls in DB
    cur.execute("UPDATE budgets SET val = 20 WHERE key = 'session_calls:test_sess_1'")
    conn.commit()
    conn.close()

    # 21st call must return HARD_STOP
    stop_res = json.loads(add_sourced_job(
        company="Cred",
        role="SDE-2",
        job_url="https://cred.club/careers/1",
        platform="Direct"
    ))
    assert stop_res.get("HARD_STOP") is True
    assert "MAX_CALLS_PER_SESSION" in stop_res.get("reason", "")


def test_bug7_update_application_state_validates_status(temp_db):
    """Bug 7: update_application_state returns error for invalid statuses and accepts valid ones."""
    add_sourced_job(
        company="Hooli",
        role="Backend SDE-2",
        job_url="https://hooli.com/jobs/42",
        platform="Direct",
        salary_lpa=30
    )
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT id FROM jobs WHERE company = 'Hooli'")
    job_id = cur.fetchone()[0]
    conn.close()

    # Invalid status
    bad_res = json.loads(update_application_state(job_id=job_id, new_status="UNKNOWN_STATUS"))
    assert bad_res["updated"] is False
    assert "Invalid status" in bad_res["error"]

    # Valid status RANKED_OUT
    ok_res = json.loads(update_application_state(job_id=job_id, new_status="RANKED_OUT"))
    assert ok_res["updated"] is True
    assert ok_res["new_status"] == "RANKED_OUT"

    # Valid status HALTED
    halt_res = json.loads(update_application_state(job_id=job_id, new_status="HALTED", blocker_note="CAPTCHA observed"))
    assert halt_res["updated"] is True
    assert halt_res["new_status"] == "HALTED"


def test_kill_switch_intercepts_all_tools(temp_db):
    """Verify that activating the kill switch immediately halts all tool execution."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute('UPDATE kill_switch SET "on" = 1, reason = "Emergency testing" WHERE id = 1;')
    conn.commit()
    conn.close()

    # Any tool must return HARD_STOP
    res = json.loads(start_session_with_capsule("CLAUDE"))
    assert res.get("HARD_STOP") is True
    assert "Kill switch is active" in res.get("reason", "")

    res2 = json.loads(acquire_lock("CHROME_BROWSER", "CLAUDE", "Browsing"))
    assert res2.get("HARD_STOP") is True


def test_lock_renewal_and_peer_conflict(temp_db):
    """Verify lock acquisition, peer exclusion, and renewal."""
    # CLAUDE acquires lock
    res1 = json.loads(acquire_lock("CHROME_BROWSER", "CLAUDE", "Initial run", ttl_minutes=10))
    assert res1["lock_acquired"] is True

    # ANTIGRAVITY attempts same lock -> LOCKED_BY_PEER
    res2 = json.loads(acquire_lock("CHROME_BROWSER", "ANTIGRAVITY", "Maintenance", ttl_minutes=5))
    assert res2["lock_acquired"] is False
    assert res2["status"] == "LOCKED_BY_PEER"
    assert res2["locked_by"] == "CLAUDE"

    # CLAUDE renews lock -> Success
    res3 = json.loads(acquire_lock("CHROME_BROWSER", "CLAUDE", "Extended run", ttl_minutes=15))
    assert res3["lock_acquired"] is True

    # CLAUDE releases lock
    rel = json.loads(release_lock("CHROME_BROWSER", "CLAUDE"))
    assert rel["released"] is True

    # ANTIGRAVITY can now acquire
    res4 = json.loads(acquire_lock("CHROME_BROWSER", "ANTIGRAVITY", "Maintenance", ttl_minutes=5))
    assert res4["lock_acquired"] is True


def test_lock_expiry_allows_new_agent(temp_db):
    """Verify that an expired lock is cleaned up and another agent can acquire it."""
    conn = sqlite3.connect(temp_db)
    # Insert an expired lock (expires 1 hour in the past)
    conn.execute("""
        INSERT INTO agent_locks (resource_id, locked_by, task_description, locked_at, expires_at)
        VALUES ('CHROME_BROWSER', 'OLD_AGENT', 'Old task', '2020-01-01T00:00:00', '2020-01-01T01:00:00')
    """)
    conn.commit()
    conn.close()

    # CLAUDE attempts to acquire -> should clean expired lock and succeed
    res = json.loads(acquire_lock("CHROME_BROWSER", "CLAUDE", "New task", ttl_minutes=10))
    assert res["lock_acquired"] is True
    assert res["owner"] == "CLAUDE"


def test_update_application_state_refuses_downgrading_applied(temp_db):
    """Verify update_application_state refuses to downgrade a job whose status is APPLIED."""
    add_sourced_job(
        company="Uber",
        role="Senior Backend Engineer",
        job_url="https://uber.com/jobs/777",
        platform="Direct",
        salary_lpa=40
    )
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT id FROM jobs WHERE company = 'Uber'")
    job_id = cur.fetchone()[0]
    conn.close()

    # Transition to APPLIED
    ok = json.loads(update_application_state(job_id=job_id, new_status="APPLIED"))
    assert ok["updated"] is True

    # Attempt to downgrade to BLOCKED_USER -> must be refused
    downgrade = json.loads(update_application_state(job_id=job_id, new_status="BLOCKED_USER", blocker_note="Oops"))
    assert downgrade["updated"] is False
    assert "Cannot downgrade job" in downgrade["error"]

    # Verify DB still has APPLIED
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
    assert cur.fetchone()[0] == "APPLIED"
    conn.close()


def test_get_or_save_screening_answer_migrated_keys(temp_db):
    """Verify get_or_save_screening_answer reads migrated keys, aliases, and saves new answers."""
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT OR REPLACE INTO screening_qa VALUES ('notice_period_days', '30 days')")
    conn.execute("INSERT OR REPLACE INTO screening_qa VALUES ('java_years', '3 years')")
    conn.commit()
    conn.close()

    # Exact key
    r1 = json.loads(get_or_save_screening_answer("notice_period_days"))
    assert r1["found"] is True
    assert r1["answer"] == "30 days"

    # Alias / fuzzy query
    r2 = json.loads(get_or_save_screening_answer("What is your notice period?"))
    assert r2["found"] is True
    assert r2["answer"] == "30 days"

    # Save new answer
    r3 = json.loads(get_or_save_screening_answer("kubernetes_years", "2 years"))
    assert r3["saved"] is True
    assert r3["answer"] == "2 years"

    # Read back newly saved
    r4 = json.loads(get_or_save_screening_answer("kubernetes_years"))
    assert r4["found"] is True
    assert r4["answer"] == "2 years"


def test_get_and_mark_application_answers(temp_db):
    """Verify get_application_answers and mark_application_answers_submitted tools."""
    conn = sqlite3.connect(temp_db)
    conn.execute("""
        INSERT INTO app_story_answers (application, question, answer, status, saved_at)
        VALUES
        ('Acme Corp - SDE-2 Backend', 'Describe system architecture', 'Platform migration ~20K req/s', 'DRAFT_NOT_SUBMITTED', '2026-11-01T00:00:00'),
        ('Acme Corp - SDE-2 Backend', 'Incident handled', 'Cold cache latency regression fixed', 'DRAFT_NOT_SUBMITTED', '2026-11-01T00:00:00')
    """)
    conn.commit()
    conn.close()

    # Query by substring 'Acme Corp'
    res = json.loads(get_application_answers("Acme Corp"))
    assert res["found"] is True
    assert res["count"] == 2
    assert len(res["answers"]) == 2
    assert res["answers"][0]["status"] == "DRAFT_NOT_SUBMITTED"

    # Mark as submitted
    sub = json.loads(mark_application_answers_submitted("Acme Corp"))
    assert sub["updated"] is True
    assert sub["rows_updated"] == 2

    # Verify status changed to SUBMITTED
    res2 = json.loads(get_application_answers("Acme Corp"))
    assert res2["answers"][0]["status"] == "SUBMITTED"
    assert res2["answers"][1]["status"] == "SUBMITTED"

