"""Tests for /fill command logic, answers bank matcher, and Simplify form audit."""

import re
import sqlite3
import pytest
from pathlib import Path
from harness.answers import match_screening_answer, match_story_answer, audit_field_value

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_screening_answer_exact_and_fuzzy_matches(temp_db):
    """Test exact, normalized, and alias matching in screening_qa."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO screening_qa VALUES ('java_years', '3 years')")
    cur.execute("INSERT OR REPLACE INTO screening_qa VALUES ('notice_period_days', '30 days')")
    cur.execute("INSERT OR REPLACE INTO screening_qa VALUES ('expected_ctc', '24-32 LPA')")
    conn.commit()

    # Exact key
    assert match_screening_answer("java_years", conn) == "3 years"

    # Natural phrasing with punctuation / stop words
    assert match_screening_answer("How many years of experience do you have in Java?", conn) == "3 years"

    # Alias pattern
    assert match_screening_answer("What is your official notice period?", conn) == "30 days"

    # Unseen question
    assert match_screening_answer("Do you have experience in COBOL?", conn) is None
    conn.close()


def test_story_answer_matching(temp_db):
    """Test behavioral story prompt matching."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO story_answers (topic, question_pattern, answer_text, key_metrics, updated_at)
        VALUES ('microservices_migration', 'microservice.*migrat|migrat.*microservice|routing.*layer',
                'Engineered 20K req/s routing layer across 8 services at Acme Corp',
                '20K req/s, 8 microservices, 25% CPU reduction', '2026-11-01')
    """)
    conn.commit()

    ans = match_story_answer("Tell me about a time you handled a complex microservices migration.", conn)
    assert ans is not None
    assert ans["topic"] == "microservices_migration"
    assert "20K req/s" in ans["answer_text"]

    assert match_story_answer("Tell me about a time you failed a sales quota.", conn) is None
    conn.close()


def test_simplify_audit_overwrites_mismatches():
    """Verify audit_field_value corrects Simplify's incorrect autofill values."""
    capsule = {
        "candidate_name": "Candidate Name",
        "email_primary": "candidate@example.com",
        "resume_url": "https://example.com/resume",
        "notice_period": "30 days",
        "expected_ctc": 30,
        "total_experience": "3 years",
        "forbidden_links": ["shorturl.at"]
    }

    # Simplify incorrectly fills 25 for expected salary -> must overwrite with 30
    ok, corrected = audit_field_value("expected_salary", "25", capsule)
    assert ok is False
    assert corrected == "30"

    # Simplify fills 15 days notice -> must overwrite with 30 days
    ok, corrected = audit_field_value("notice_period", "15 days", capsule)
    assert ok is False
    assert corrected == "30 days"

    # Banned link filled -> must overwrite with canonical URL
    ok, corrected = audit_field_value("resume_link", "https://shorturl.at/xyz", capsule)
    assert ok is False
    assert corrected == "https://example.com/resume"

    # Correct value passes unchanged
    ok, corrected = audit_field_value("name", "Candidate Name", capsule)
    assert ok is True
    assert corrected == "Candidate Name"


class FakeBrowserAdapter:
    """Mock browser adapter recording actions executed against an HTML form."""
    def __init__(self, html_path: Path):
        self.html = html_path.read_text(encoding="utf-8")
        self.actions = []

    def autofill_simplify(self):
        self.actions.append("SIMPLIFY_TRIGGERED")

    def set_input(self, field_id: str, value: str):
        self.actions.append(f"FILL:{field_id}:{value}")

    def click(self, button_id: str):
        self.actions.append(f"CLICK:{button_id}")


def test_dry_run_form_fill_with_simplify_audit(temp_db):
    """Walkthrough of Easy Apply form: Simplify fills -> audit fixes -> submit."""
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "forms" / "easy_apply.html"
    browser = FakeBrowserAdapter(fixture_path)
    capsule = {"expected_ctc": 30, "notice_period": "30 days", "resume_url": "https://example.com/resume"}

    # 1. Trigger Simplify
    browser.autofill_simplify()

    # 2. Audit fields and fix mismatches
    notice_ok, notice_val = audit_field_value("notice", "15 days", capsule)
    if not notice_ok:
        browser.set_input("notice", notice_val)

    sal_ok, sal_val = audit_field_value("expected_salary", "25", capsule)
    if not sal_ok:
        browser.set_input("expected_salary", sal_val)

    # 3. Fill required empty field
    browser.set_input("resume", "documents/resume.pdf")

    # 4. Click site submit (NEVER click simplify submit)
    browser.click("site-submit")

    assert "SIMPLIFY_TRIGGERED" in browser.actions
    assert "FILL:notice:30 days" in browser.actions
    assert "FILL:expected_salary:30" in browser.actions
    assert "CLICK:site-submit" in browser.actions
    assert "CLICK:simplify-submit" not in browser.actions


def test_dry_run_form_blocked_on_unseen_mandatory_question(temp_db):
    """Walkthrough of Eightfold form with unanswerable question -> parks as BLOCKED_USER, no submit."""
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "forms" / "eightfold.html"
    browser = FakeBrowserAdapter(fixture_path)

    conn = sqlite3.connect(temp_db)
    ans = match_screening_answer("Do you hold an active Top Secret clearance?", conn)
    conn.close()

    assert ans is None, "Question is unknown"

    # Because question is required and unknown, mark BLOCKED_USER and abort
    status = "BLOCKED_USER"
    blocker_reason = "Unseen mandatory question: Do you hold an active Top Secret clearance?"

    # Assert no submit action was executed
    assert "CLICK:site-submit" not in browser.actions
    assert status == "BLOCKED_USER"
