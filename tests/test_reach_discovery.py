"""Tests for Reach discovery, daily caps, executive filtering, and contact quotas (Step S6)."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest

from tools import network_batch, contacts, reachout_data

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_network_batch_tick_caps_and_reset(temp_db):
    """Verify daily caps on search (15), profile (40), and prefill (25), resetting by UTC day."""
    conn = network_batch._connect(temp_db)
    day1 = "2026-11-04"
    day2 = "2026-11-05"

    # 1. Search cap = 15
    for i in range(1, 16):
        assert network_batch.tick(conn, "search", day=day1) is True
    # 16th call hits CAP
    assert network_batch.tick(conn, "search", day=day1) is False

    # Day 2 resets search cap
    assert network_batch.tick(conn, "search", day=day2) is True

    # 2. Profile cap = 40
    for i in range(1, 41):
        assert network_batch.tick(conn, "profile", day=day1) is True
    assert network_batch.tick(conn, "profile", day=day1) is False

    # 3. Prefill cap = 25
    for i in range(1, 26):
        assert network_batch.tick(conn, "prefill", day=day1) is True
    assert network_batch.tick(conn, "prefill", day=day1) is False

    conn.close()


def test_tick_cli_output(temp_db, monkeypatch):
    """Verify CLI prints OK n/cap or CAP."""
    monkeypatch.setenv("HARNESS_DB", temp_db)

    # Initial tick
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "network_batch.py"), "tick", "search", "--day", "2026-11-04"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "OK 1/15" in res.stdout

    # Fill up cap
    conn = network_batch._connect(temp_db)
    for _ in range(14):
        network_batch.tick(conn, "search", day="2026-11-04")
    conn.close()

    # Next CLI call prints CAP
    res_cap = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "network_batch.py"), "tick", "search", "--day", "2026-11-04"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "CAP" in res_cap.stdout


def test_executive_filter_in_save_contacts(temp_db):
    """Verify VP, Director, CTO, CEO, and Head of are rejected."""
    candidates = [
        {"name": "Alice Exec", "title": "VP of Engineering", "profile_url": "https://linkedin.com/in/alice"},
        {"name": "Bob Director", "title": "Director of Software", "profile_url": "https://linkedin.com/in/bob"},
        {"name": "Charlie Founder", "title": "Co-Founder & CTO", "profile_url": "https://linkedin.com/in/charlie"},
        {"name": "Dan Head", "title": "Head of Engineering", "profile_url": "https://linkedin.com/in/dan"},
        {"name": "Eve Peer", "title": "Senior Software Engineer", "profile_url": "https://linkedin.com/in/eve"},
    ]

    saved = contacts.save_ranked_contacts(
        job_id=1,
        company="Acme Corp",
        candidates=candidates,
        db_path=temp_db,
    )

    saved_names = [c["name"] for c in saved]
    assert "Eve Peer" in saved_names
    assert "Alice Exec" not in saved_names
    assert "Bob Director" not in saved_names
    assert "Charlie Founder" not in saved_names
    assert "Dan Head" not in saved_names


def test_max_per_job_quotas(temp_db):
    """Verify quota: at most 2 engineers, 1 manager, 1 recruiter (max 4 per job)."""
    candidates = [
        {"name": "Eng 1", "title": "Senior Software Engineer", "profile_url": "https://linkedin.com/in/eng1", "kind": "senior_sde"},
        {"name": "Eng 2", "title": "Backend SDE-2", "profile_url": "https://linkedin.com/in/eng2", "kind": "senior_sde"},
        {"name": "Eng 3", "title": "Staff Engineer", "profile_url": "https://linkedin.com/in/eng3", "kind": "senior_sde"},
        {"name": "Mgr 1", "title": "Engineering Manager", "profile_url": "https://linkedin.com/in/mgr1", "kind": "hiring_manager"},
        {"name": "Mgr 2", "title": "Software Development Manager", "profile_url": "https://linkedin.com/in/mgr2", "kind": "hiring_manager"},
        {"name": "Rec 1", "title": "Technical Recruiter", "profile_url": "https://linkedin.com/in/rec1", "kind": "recruiter"},
        {"name": "Rec 2", "title": "Talent Partner", "profile_url": "https://linkedin.com/in/rec2", "kind": "recruiter"},
    ]

    saved = contacts.save_ranked_contacts(
        job_id=42,
        company="Acme Corp",
        candidates=candidates,
        db_path=temp_db,
        top_n=4,
    )

    assert len(saved) == 4
    kinds = [c["kind"] for c in saved]
    assert kinds.count("senior_sde") == 2
    assert kinds.count("hiring_manager") == 1
    assert kinds.count("recruiter") == 1


def test_already_contacted_skip(temp_db):
    """Verify profiles already in already_contacted are skipped."""
    conn = sqlite3.connect(temp_db)
    conn.execute("""
        INSERT INTO contacts (job_id, name, title, profile_url, current_company, status, created_at)
        VALUES (1, 'Old Contact', 'Senior SWE', 'https://linkedin.com/in/oldcontact', 'Acme Corp', 'SENT', '2026-11-01')
    """)
    conn.commit()
    conn.close()

    candidates = [
        {"name": "Old Contact", "title": "Senior SWE", "profile_url": "https://linkedin.com/in/oldcontact"},
        {"name": "New Contact", "title": "Senior SWE", "profile_url": "https://linkedin.com/in/newcontact"},
    ]

    saved = contacts.save_ranked_contacts(
        job_id=1,
        company="Acme Corp",
        candidates=candidates,
        db_path=temp_db,
    )

    saved_names = [c["name"] for c in saved]
    assert "New Contact" in saved_names
    assert "Old Contact" not in saved_names
