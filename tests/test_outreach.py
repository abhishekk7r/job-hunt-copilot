"""Tests for outreach generation, templates, deterministic rendering, and Gmail drafts."""

import json
import sqlite3
import sys
import pytest
from pathlib import Path
from harness.outreach import (
    render_outreach,
    determine_channel,
    create_gmail_draft,
    load_template,
)
from harness.server import draft_outreach_for_mobile_review, process_mobile_approvals

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def mock_capsule():
    return {
        "candidate_name": "Test Candidate",
        "email_primary": "candidate@example.com",
        "resume_url": "https://example.com/resume",
        "notice_period": "30 days",
        "bullets": [
            "Built backend services in Java and Spring Boot",
            "Led a platform migration that cut CPU use by 25% at Acme Corp",
            "Ran on-call for high-traffic APIs"
        ],
        "forbidden_links": ["shorturl.at"]
    }


@pytest.fixture
def sample_job():
    return {
        "id": 1,
        "company": "Acme Corp",
        "role": "SDE-2 Backend",
        "job_url": "https://acme.com/jobs/123",
        "job_id_ext": "REQ-101",
        "tier": 1,
        "status": "APPLIED"
    }


def test_channel_selection_logic():
    """Verify channel determination across degree, tier, and email availability."""
    # 1st degree -> LinkedIn DM
    assert determine_channel(connection_degree=1, tier=1, inmail_credits=5) == "LinkedIn DM"

    # 2nd degree, tier 1, credits available -> InMail
    assert determine_channel(connection_degree=2, tier=1, inmail_credits=2) == "InMail"

    # 2nd degree, tier 3, credits available -> Connection Note (credits reserved for tier 1-2)
    assert determine_channel(connection_degree=2, tier=3, inmail_credits=2) == "Connection Note"

    # 2nd degree, zero credits, no email -> Connection Note
    assert determine_channel(connection_degree=2, tier=1, inmail_credits=0) == "Connection Note"

    # Contact has email and preferred -> Email
    assert determine_channel(connection_degree=2, tier=1, inmail_credits=0, has_email=True, prefer_email=True) == "Email"


def test_templates_load_cleanly():
    """Verify templates load and contain required placeholders without hard wraps."""
    for slug in ["dm", "inmail", "connection_note", "email"]:
        tmpl = load_template(slug)
        assert "{opener}" in tmpl
        assert "{bullets}" in tmpl
        assert "{resume_url}" in tmpl
        # No artificial 80-char mid-sentence wraps
        lines = tmpl.splitlines()
        for line in lines:
            if line and not line.startswith("Subject:"):
                # Paragraphs can be long, but should not have broken hyphenations
                assert not line.endswith("- ")


def test_linkedin_dm_rendering(mock_capsule, sample_job):
    """Verify DM rendering honours custom_opener, contains 'I\\'ve applied for', and resume URL."""
    contact = {"name": "Jane Doe", "linkedin_url": "https://linkedin.com/in/janedoe"}

    # Default opener
    out = render_outreach("LinkedIn DM", sample_job, contact, mock_capsule)
    body = out["body"]
    assert "Hi Jane," in body
    assert "I've applied for the SDE-2 Backend position at Acme Corp" in body
    assert "https://example.com/resume" in body
    assert "Notice period: 30 days" in body

    # Custom opener honoured and ensures 'I\'ve applied for'
    custom = "I saw your engineering team is expanding rapidly."
    out_custom = render_outreach("LinkedIn DM", sample_job, contact, mock_capsule, custom_opener=custom)
    assert "I saw your engineering team is expanding rapidly" in out_custom["body"]
    assert "I've applied for" in out_custom["body"]


def test_connection_note_character_cap(mock_capsule, sample_job):
    """Verify connection note strictly enforces <= 300 characters."""
    contact = {"name": "Alex Recruiter", "linkedin_url": "https://linkedin.com/in/alex"}

    out = render_outreach("Connection Note", sample_job, contact, mock_capsule)
    assert out["char_count"] <= 300
    assert "https://example.com/resume" in out["body"]

    # Even with excessively long custom opener, must enforce <= 300
    long_opener = "I have been following Acme Corp's exceptional distributed systems journey for several years and noticed the open SDE-2 role."
    out_long = render_outreach("Connection Note", sample_job, contact, mock_capsule, custom_opener=long_opener)
    assert out_long["char_count"] <= 300
    assert len(out_long["body"]) <= 300


def test_banned_shorteners_strictly_rejected(mock_capsule, sample_job):
    """Verify outreach rendering rejects banned shorteners like shorturl.at."""
    contact = {"name": "Recruiter Bob"}

    # Banned link in custom opener
    with pytest.raises(ValueError, match="Banned link 'shorturl.at' detected"):
        render_outreach("LinkedIn DM", sample_job, contact, mock_capsule, custom_opener="Check my profile at https://shorturl.at/abc")

    # Banned link in capsule resume_url
    bad_capsule = dict(mock_capsule)
    bad_capsule["resume_url"] = "https://shorturl.at/xyz"
    with pytest.raises(ValueError, match="Banned link 'shorturl.at' detected"):
        render_outreach("LinkedIn DM", sample_job, contact, bad_capsule)


def test_gmail_draft_creation_never_sends(tmp_path, mock_capsule, sample_job):
    """Verify email channel renders draft, writes to outreach_emails/, and NEVER sends."""
    contact = {"name": "Hiring Lead", "email": "lead@acme.com"}
    out = render_outreach("Email", sample_job, contact, mock_capsule)

    draft_res = create_gmail_draft(
        to_email=contact["email"],
        subject=out["subject"],
        body=out["body"],
        draft_dir=tmp_path
    )

    assert draft_res["draft_created"] is True
    assert draft_res["sent"] is False
    assert draft_res["to"] == "lead@acme.com"

    draft_file = Path(draft_res["draft_path"])
    assert draft_file.exists()
    content = draft_file.read_text(encoding="utf-8")
    assert "Status: DRAFT_ONLY (NEVER SENT AUTOMATICALLY)" in content
    assert "lead@acme.com" in content
    assert "https://example.com/resume" in content


def test_mcp_draft_outreach_and_approval_flow(temp_db, monkeypatch, tmp_path):
    """Integration test: draft outreach in MCP server, verify queue and status preservation."""
    monkeypatch.setenv("HARNESS_DB", temp_db)

    # Seed job in temp_db
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO jobs (company, role, job_url, job_id_ext, tier, status, outreach_state, platform, updated_at)
        VALUES ('Globex', 'Backend Engineer', 'https://globex.com/job/456', 'REQ-999', 1, 'APPLIED', 'NONE', 'GlobexCareers', '2026-11-01T00:00:00')
    """)
    job_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Draft outreach
    res_raw = draft_outreach_for_mobile_review(
        job_id=job_id,
        recruiter_name="Sarah Talent",
        recruiter_title="Lead Recruiter",
        recruiter_linkedin="https://linkedin.com/in/sarah",
        connection_degree=1,
        custom_opener="I saw your backend scaling post."
    )
    res = json.loads(res_raw)

    assert res["queued_for_mobile_review"] is True
    assert res["channel"] == "LinkedIn DM"
    queue_id = res["queue_id"]

    # Verify database state: jobs.status stays 'APPLIED', outreach_state is 'DRAFTED'
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT status, outreach_state FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    assert row[0] == "APPLIED"  # Status preserved (Bug 3 fix)
    assert row[1] == "DRAFTED"

    # Verify queue entry is PENDING_MOBILE_REVIEW
    cur.execute("SELECT approval_status, rendered_message FROM outreach_queue WHERE id = ?", (queue_id,))
    q_row = cur.fetchone()
    assert q_row[0] == "PENDING_MOBILE_REVIEW"
    assert "I've applied for" in q_row[1]
    conn.close()

    # User approves via mobile review
    appr_res_raw = process_mobile_approvals(approve_queue_ids=[queue_id])
    appr_res = json.loads(appr_res_raw)
    assert len(appr_res["approved_items_to_send_now"]) == 1

    # Check updated queue status
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT approval_status FROM outreach_queue WHERE id = ?", (queue_id,))
    assert cur.fetchone()[0] == "APPROVED_TO_SEND"
    conn.close()


def test_template_skeletons_present():
    """Verify fixed template skeletons exist for connection_note, inmail, and email."""
    templates_dir = REPO_ROOT / "config" / "templates"
    assert templates_dir.is_dir()
    for channel in ("connection_note", "inmail", "email"):
        t_path = templates_dir / f"{channel}.txt"
        assert t_path.is_file(), f"Missing template: {channel}.txt"
        content = t_path.read_text(encoding="utf-8")
        assert "{first_name}" in content
        assert "{opener}" in content


def test_validator_cases(temp_db, tmp_path, monkeypatch):
    """Verify validator catches: too long, missing 'I have applied', wrong resume link, shortener, markdown, invented number."""
    from harness.outreach import validate_outreach
    monkeypatch.setenv("HARNESS_DB", temp_db)

    # Insert job 77 with status APPLIED
    conn = sqlite3.connect(temp_db)
    conn.execute("""
        INSERT INTO jobs (id, company, role, job_url, status, platform, updated_at)
        VALUES (77, 'Acme Corp', 'Backend Engineer', 'https://acme.com/job/77', 'APPLIED', 'Direct', '2026-11-01T00:00:00Z')
    """)
    conn.commit()
    conn.close()

    # Create dummy research note with legitimate numbers
    job_dir = REPO_ROOT / "reports" / "jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    note_file = job_dir / "77.md"
    note_file.write_text("Acme Corp Backend Engineer. Requires 3 years experience. Stack: Java 17.", encoding="utf-8")

    resume_url = "https://example.com/resume"

    # 1. Valid email draft
    valid_email = (
        f"Subject: Application for Backend Engineer - Candidate Name\n\n"
        f"Hi Alex,\n\n"
        f"I have applied for the Backend Engineer position at Acme Corp. "
        f"I bring 3 years of backend experience building high-throughput systems.\n\n"
        f"Resume: {resume_url}\nNotice Period: 30 days\n\nBest regards,\nCandidate Name"
    )
    p_valid = tmp_path / "valid.txt"
    p_valid.write_text(valid_email, encoding="utf-8")
    errs = validate_outreach("email", 77, p_valid, db_path=temp_db)
    assert not errs, f"Expected valid email, got errors: {errs}"

    # 2. Too long connection note (> 300 chars)
    p_long = tmp_path / "long_note.txt"
    p_long.write_text("Hi Alex, " + "I have applied for Backend Engineer at Acme Corp. " * 8, encoding="utf-8")
    assert len(p_long.read_text(encoding="utf-8")) > 300
    errs = validate_outreach("note", 77, p_long, db_path=temp_db)
    assert any("exceeds 300 characters" in e for e in errs)

    # 3. Missing 'I have applied' when job is APPLIED
    p_missing = tmp_path / "missing_applied.txt"
    p_missing.write_text("Hi Alex, hope you are well. Would love to chat about Acme Corp.", encoding="utf-8")
    errs = validate_outreach("note", 77, p_missing, db_path=temp_db)
    assert any("must explicitly state 'I have applied'" in e for e in errs)

    # 4. Wrong resume link in InMail
    wrong_resume_mail = (
        f"Subject: Application for Backend Engineer\n\n"
        f"Hi Alex,\n\n"
        f"I have applied for the role. Here is my resume: https://drive.google.com/file/d/123/view\n\n"
        f"Notice: 30 days"
    )
    p_wrong_link = tmp_path / "wrong_link.txt"
    p_wrong_link.write_text(wrong_resume_mail, encoding="utf-8")
    errs = validate_outreach("inmail", 77, p_wrong_link, db_path=temp_db)
    assert any("Unauthorized resume link" in e or "missing" in e for e in errs)

    # 5. Link shortener / banned link
    p_shortener = tmp_path / "shortener.txt"
    p_shortener.write_text(f"Hi Alex, I have applied for Backend Engineer. Check https://bit.ly/my-cv", encoding="utf-8")
    errs = validate_outreach("note", 77, p_shortener, db_path=temp_db)
    assert any("shortener" in e.lower() for e in errs)

    # 6. Markdown detected
    p_md = tmp_path / "markdown.txt"
    p_md.write_text(f"Hi Alex, I have applied for **Backend Engineer** at Acme Corp. Would love to connect!", encoding="utf-8")
    errs = validate_outreach("note", 77, p_md, db_path=temp_db)
    assert any("Markdown" in e for e in errs)

    # 7. Invented number (e.g. 99% or 1000000)
    p_invented = tmp_path / "invented_num.txt"
    p_invented.write_text(f"Hi Alex, I have applied for Backend Engineer. I improved performance by 99% at past company.", encoding="utf-8")
    errs = validate_outreach("note", 77, p_invented, db_path=temp_db)
    assert any("Invented number" in e and "99%" in e for e in errs)

    # 8. Clean up note file
    note_file.unlink(missing_ok=True)


def test_validator_cli(temp_db, tmp_path):
    """Test CLI exit codes for validate subcommand."""
    import subprocess
    p_file = tmp_path / "test_note.txt"
    p_file.write_text("Hi Alex, I have applied for Backend Engineer at Acme. 3 yrs Java experience.", encoding="utf-8")

    # Success case (returns 0)
    res = subprocess.run(
        [sys.executable, "-m", "harness.outreach", "validate", "--channel", "note", "--job", "1", "--file", str(p_file), "--db", temp_db],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0
    assert "VALID" in res.stdout

    # Failure case (e.g. too long note -> returns 1)
    p_long = tmp_path / "test_long.txt"
    p_long.write_text("Hi Alex, " + "too long " * 50, encoding="utf-8")
    res_fail = subprocess.run(
        [sys.executable, "-m", "harness.outreach", "validate", "--channel", "note", "--job", "1", "--file", str(p_long), "--db", temp_db],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res_fail.returncode == 1
    assert "Validation failed" in res_fail.stderr
