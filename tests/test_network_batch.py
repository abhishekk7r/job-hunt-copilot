"""Tests for tools/network_batch.py and the peer-first scoring rules."""

import sqlite3
import pytest

from tools.contacts import score_contact, categorize_kind, is_executive, save_ranked_contacts
from tools import network_batch as nb

DAY = "2026-11-03"


def _conn(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def _add_job(conn, company, status="APPLIED", role="SDE-2 Backend"):
    conn.execute(
        "INSERT INTO jobs (company, role, job_url, platform, status, updated_at) VALUES (?,?,?,?,?,'2026-11-02')",
        (company, role, f"https://x/{company}/{role}", "linkedin", status),
    )
    conn.commit()


def _add_contact(conn, name, title, company, score, url=None, status="PROPOSED"):
    conn.execute(
        """INSERT INTO contacts (name, title, profile_url, current_company, score, kind, status, created_at)
           VALUES (?,?,?,?,?,?,?,'2026-11-02')""",
        (name, title, url or f"https://linkedin.com/in/{name.replace(' ', '')}", company, score,
         categorize_kind(title), status),
    )
    conn.commit()


def test_executives_rejected_and_peers_preferred():
    vp = {"name": "V", "title": "VP Engineering", "current_company": "Acme", "connection_degree": 1}
    cto = {"name": "C", "title": "Co-founder & CTO", "current_company": "Acme"}
    director = {"name": "D", "title": "Director of Engineering", "current_company": "Acme"}
    peer = {"name": "P", "title": "Senior Software Engineer - Java, Spring Boot", "current_company": "Acme", "connection_degree": 2}
    for c in (vp, cto, director):
        assert score_contact(c, "Acme") < 0
        assert categorize_kind(c["title"]) == "executive"
    assert score_contact(peer, "Acme") > 0
    assert categorize_kind("Senior Software Engineer") == "senior_sde"


def test_applied_company_and_stack_bonus():
    c = {"name": "P", "title": "Senior Software Engineer Java AWS", "current_company": "Acme", "connection_degree": 2}
    plain = {"name": "Q", "title": "Senior Software Engineer", "current_company": "Acme", "connection_degree": 2}
    assert score_contact(c, "Acme") == score_contact(plain, "Acme") + 10.0
    assert score_contact(plain, "Acme", job_applied=True) == score_contact(plain, "Acme") + 15.0


def test_save_ranked_contacts_dedupes_profiles(temp_db):
    cands = [{"name": "A", "title": "Engineering Manager", "current_company": "G", "profile_url": "u1"}]
    assert len(save_ranked_contacts(None, "G", cands, temp_db)) == 1
    assert save_ranked_contacts(None, "G", cands, temp_db) == []


def test_batch_caps_per_company_and_daily_limit(temp_db):
    conn = _conn(temp_db)
    for i in range(30):
        _add_contact(conn, f"Person{i}", "Senior Software Engineer", f"Co{i // 3}", 90 - i)
    batch = nb.build_batch(conn, limit=25, per_company=2, day=DAY)
    assert len(batch["items"]) <= 25
    per = {}
    for it in batch["items"]:
        per[it["company"]] = per.get(it["company"], 0) + 1
    assert max(per.values()) <= 2
    assert all(it["note_chars"] <= 300 for it in batch["items"])


def test_batch_skips_executives_and_non_proposed(temp_db):
    conn = _conn(temp_db)
    _add_contact(conn, "Boss", "VP Engineering", "Acme", 99)
    _add_contact(conn, "Done", "Senior Software Engineer", "Acme", 90, status="SENT")
    _add_contact(conn, "Peer", "Senior Software Engineer", "Acme", 80)
    batch = nb.build_batch(conn, day=DAY)
    assert [i["name"] for i in batch["items"]] == ["Peer"]
    assert any(s["name"] == "Boss" for s in batch["skipped"])


def test_ive_applied_only_when_job_is_applied(temp_db):
    conn = _conn(temp_db)
    _add_job(conn, "Globex", "APPLIED", "Senior Software Engineer - Java")
    _add_job(conn, "Initech", "TO_APPLY")
    _add_contact(conn, "Priya Sample", "Senior Software Engineer", "Globex", 70)
    _add_contact(conn, "Sam Placeholder", "Senior Software Engineer", "Initech", 95)
    batch = nb.build_batch(conn, day=DAY)
    notes = {i["name"]: i for i in batch["items"]}
    assert "I've applied" in notes["Priya Sample"]["note_text"]
    assert "I've applied" not in notes["Sam Placeholder"]["note_text"]
    # warm company ordered first even with a lower score
    assert batch["items"][0]["name"] == "Priya Sample"


def test_kill_switch_halts_batch(temp_db):
    conn = _conn(temp_db)
    _add_contact(conn, "Peer", "Senior Software Engineer", "Acme", 80)
    conn.execute('INSERT OR REPLACE INTO kill_switch (id, "on", reason, ts) VALUES (1, 1, "test", "now")')
    conn.commit()
    batch = nb.build_batch(conn, day=DAY)
    assert batch["items"] == [] and batch["halted"]


def test_mark_lifecycle_and_daily_cap(temp_db):
    conn = _conn(temp_db)
    _add_contact(conn, "Peer", "Senior Software Engineer", "Acme", 80)
    cid = conn.execute("SELECT id FROM contacts").fetchone()["id"]
    today = nb._utc_now()[:10]
    nb.mark(conn, str(cid), "PREFILLED")
    assert nb.used_today(conn, today) == 1
    nb.mark(conn, str(cid), "SENT")
    assert conn.execute("SELECT status FROM contacts").fetchone()[0] == "SENT"
    with pytest.raises(ValueError):
        nb.mark(conn, str(cid), "SKIPPED")  # no downgrade from SENT
    with pytest.raises(ValueError):
        nb.mark(conn, str(cid), "BOGUS")
    with pytest.raises(LookupError):
        nb.mark(conn, "99999", "SENT")


def test_remaining_slots_shrink_after_prefill(temp_db):
    conn = _conn(temp_db)
    today = nb._utc_now()[:10]
    for i in range(3):
        _add_contact(conn, f"P{i}", "Senior Software Engineer", f"Co{i}", 80 - i)
    ids = [r[0] for r in conn.execute("SELECT id FROM contacts")]
    nb.mark(conn, str(ids[0]), "PREFILLED")
    batch = nb.build_batch(conn, limit=2, day=today)
    assert len(batch["items"]) == 1


def test_manifest_written(temp_db, tmp_path):
    conn = _conn(temp_db)
    _add_contact(conn, "Peer", "Senior Software Engineer", "Acme", 80)
    batch = nb.build_batch(conn, day=DAY)
    paths = nb.write_manifest(batch, tmp_path)
    assert (tmp_path / "network-batch-2026-11-03.json").exists()
    assert "Peer" in (tmp_path / "network-batch-2026-11-03.md").read_text()
    assert set(paths) == {"json", "md"}


def test_validate_note_rejects_banned_and_long():
    assert nb.validate_note("hi https://shorturl.at/x", ["shorturl.at"])
    assert nb.validate_note("x" * 301, [])
    assert nb.validate_note("fine note", ["shorturl.at"]) is None
