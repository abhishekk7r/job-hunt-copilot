"""Tests for tools/contacts.py ranking, Ex-rejection, and <=300 char note rendering."""

import sqlite3
import pytest
from pathlib import Path

from tools.contacts import score_contact, render_connection_note, save_ranked_contacts, categorize_kind

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_score_contact_rejects_ex_employees():
    """Verify that 'Ex-<company>' or 'Former <company>' headlines are rejected."""
    cand_ex = {
        "name": "Jane Doe",
        "title": "Ex-Amazon SDE-2 | Software Engineer at StartupX",
        "current_company": "StartupX",
        "connection_degree": 2,
        "location": "Bengaluru"
    }
    assert score_contact(cand_ex, target_company="Amazon") < 0, "Ex-employee must be rejected"


def test_score_contact_degree_and_location_ranking():
    """Verify deterministic ranking based on degree, location, and title."""
    cand1 = {
        "name": "Arun Kumar",
        "title": "Engineering Manager",
        "current_company": "Amazon",
        "connection_degree": 1,
        "location": "Bengaluru",
        "mutual_connections": 5
    }
    cand2 = {
        "name": "Vikram Singh",
        "title": "Technical Recruiter",
        "current_company": "Amazon",
        "connection_degree": 2,
        "location": "Bengaluru",
        "mutual_connections": 2
    }
    cand3 = {
        "name": "John Smith",
        "title": "Recruiter",
        "current_company": "Amazon",
        "connection_degree": 3,
        "location": "Seattle",
        "mutual_connections": 0
    }

    s1 = score_contact(cand1, "Amazon")
    s2 = score_contact(cand2, "Amazon")
    s3 = score_contact(cand3, "Amazon")

    assert s1 > s2 > s3
    assert s1 >= 80.0  # EM (+35), company (+40), 1st degree (+20), city (+10)


def test_render_connection_note_300_char_limit_and_phrasing():
    """Verify connection notes never exceed 300 characters and enforce 'I've applied' condition."""
    cand = {"name": "Siddharth Nair", "current_company": "Flipkart"}

    # Case A: Job applied
    note_applied = render_connection_note(cand, job_applied=True, role="SDE-2 Backend", company="Flipkart")
    assert len(note_applied) <= 300
    assert "I've applied for the SDE-2 Backend role at Flipkart" in note_applied
    assert "backend engineer" in note_applied

    # Case B: Networking (not applied yet)
    note_net = render_connection_note(cand, job_applied=False, company="Flipkart")
    assert len(note_net) <= 300
    assert "I've applied" not in note_net
    assert "backend engineer" in note_net


def test_save_ranked_contacts_persists_top_candidates(temp_db):
    """Verify save_ranked_contacts filters and saves top candidates to DB."""
    candidates = [
        {"name": "Cand A", "title": "Engineering Manager", "current_company": "Google", "profile_url": "https://linkedin.com/in/a", "connection_degree": 2},
        {"name": "Cand B (Ex)", "title": "Ex-Google Senior SDE", "current_company": "Uber", "profile_url": "https://linkedin.com/in/b", "connection_degree": 1},
        {"name": "Cand C", "title": "Technical Recruiter", "current_company": "Google", "profile_url": "https://linkedin.com/in/c", "connection_degree": 2},
        {"name": "Cand D", "title": "Senior Software Engineer", "current_company": "Google", "profile_url": "https://linkedin.com/in/d", "connection_degree": 2},
    ]

    saved = save_ranked_contacts(
        job_id=None,
        company="Google",
        candidates=candidates,
        db_path=temp_db,
        job_applied=False
    )
    # Cand B must be rejected, remaining 3 saved
    assert len(saved) == 3
    names = [c["name"] for c in saved]
    assert "Cand B (Ex)" not in names
    assert names[0] == "Cand A"

    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM contacts")
    assert cur.fetchone()[0] == 3
    conn.close()
