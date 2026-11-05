"""Tests for unified answer bank (tools/answers_bank.py) - Step S1."""

import sqlite3
from pathlib import Path
import pytest

from tools import answers_bank

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_import_is_idempotent(temp_db):
    """Importing multiple times produces identical row counts and never duplicates."""
    conn = answers_bank.get_conn(temp_db)
    # Seed screening_qa and app_story_answers
    conn.execute("INSERT OR REPLACE INTO screening_qa VALUES ('java_years', '3 years')")
    conn.execute("INSERT OR REPLACE INTO screening_qa VALUES ('notice_period_days', '30 days')")
    conn.execute("""
        INSERT INTO app_story_answers (application, question, answer, status, saved_at)
        VALUES ('App1', 'Describe hardest system', 'Region migration 20K req/s', 'APPROVED', '2026-11-01')
    """)
    conn.commit()

    c1 = answers_bank.import_all(conn)
    count1 = conn.execute("SELECT count(*) FROM answers").fetchone()[0]
    assert count1 >= 3

    # Run import second time
    c2 = answers_bank.import_all(conn)
    count2 = conn.execute("SELECT count(*) FROM answers").fetchone()[0]
    assert count1 == count2, "Import is not idempotent: row count changed"

    # Verify canonical question mapping
    r = conn.execute("SELECT answer FROM answers WHERE question = 'Years of Java experience'").fetchone()
    assert r is not None and r[0] == "3 years"
    conn.close()


def test_approved_never_overwritten_by_drafted(temp_db):
    """An approved answer must never be downgraded or overwritten by a drafted answer."""
    conn = answers_bank.get_conn(temp_db)

    # Insert an approved answer
    aid = answers_bank.upsert_answer(
        conn,
        question="What is your notice period?",
        answer="30 days",
        kind="fact",
        status="approved",
        source="owner",
    )
    conn.commit()

    # Attempt to upsert with drafted status and different answer
    aid2 = answers_bank.upsert_answer(
        conn,
        question="What is your notice period?",
        answer="15 days (wrong)",
        kind="fact",
        status="drafted",
        source="job:99",
    )
    conn.commit()
    assert aid == aid2

    row = conn.execute("SELECT answer, status FROM answers WHERE id = ?", (aid,)).fetchone()
    assert row["status"] == "approved"
    assert row["answer"] == "30 days", "Approved answer was overwritten by drafted!"
    conn.close()


def test_export_scoping(temp_db):
    """Company-scoped rows print only for that company, while global rows print for all."""
    conn = answers_bank.get_conn(temp_db)
    answers_bank.upsert_answer(conn, "Global question?", "Global answer", "fact", scope="global", status="approved")
    answers_bank.upsert_answer(conn, "Initech question?", "Initech specific answer", "fact", scope="company:initech", status="approved")
    answers_bank.upsert_answer(conn, "Globex question?", "Globex specific answer", "fact", scope="company:globex", status="approved")
    conn.commit()

    # Export without company: only global
    exp_global = answers_bank.export_markdown(conn, statuses=["approved"])
    assert "Global question?" in exp_global
    assert "Initech question?" not in exp_global
    assert "Globex question?" not in exp_global

    # Export for Initech: global + Initech, no Globex
    exp_initech = answers_bank.export_markdown(conn, statuses=["approved"], company="Initech")
    assert "Global question?" in exp_initech
    assert "Initech question?" in exp_initech
    assert "Globex question?" not in exp_initech

    # Export for Globex: global + Globex, no Initech
    exp_globex = answers_bank.export_markdown(conn, statuses=["approved"], company="Globex")
    assert "Global question?" in exp_globex
    assert "Globex question?" in exp_globex
    assert "Initech question?" not in exp_globex
    conn.close()


def test_legal_rows_exported_with_kind(temp_db):
    """Legal kind questions are exported under the Legal heading and preserve kind."""
    conn = answers_bank.get_conn(temp_db)
    answers_bank.upsert_answer(
        conn,
        question="Yes, I acknowledge and agree to terms of Nondisclosure Agreement.",
        answer="Yes",
        kind="legal",
        scope="global",
        status="approved",
    )
    conn.commit()

    exp = answers_bank.export_markdown(conn, statuses=["approved"])
    assert "## Legal" in exp
    assert "[legal] Yes, I acknowledge and agree to terms of Nondisclosure Agreement. -> Yes" in exp
    conn.close()


def test_approve_retire_used_commands(temp_db):
    """Verify approve, retire, and used helpers."""
    conn = answers_bank.get_conn(temp_db)
    aid = answers_bank.upsert_answer(conn, "Test Q", "Test A", "fact", status="drafted")
    conn.commit()

    # Approve
    assert answers_bank.cmd_approve(conn, aid, answer="Approved A") is True
    row = conn.execute("SELECT status, answer FROM answers WHERE id = ?", (aid,)).fetchone()
    assert row["status"] == "approved"
    assert row["answer"] == "Approved A"

    # Used
    assert answers_bank.cmd_used(conn, aid) is True
    row = conn.execute("SELECT uses, last_used_at FROM answers WHERE id = ?", (aid,)).fetchone()
    assert row["uses"] == 1
    assert row["last_used_at"] is not None

    # Retire
    assert answers_bank.cmd_retire(conn, aid) is True
    row = conn.execute("SELECT status FROM answers WHERE id = ?", (aid,)).fetchone()
    assert row["status"] == "retired"
    conn.close()


def test_cmd_edit_and_get_answers(temp_db):
    """Verify edit helper and get_answers query helper."""
    conn = answers_bank.get_conn(temp_db)
    aid = answers_bank.upsert_answer(conn, "Edit Q", "Initial A", "fact", status="drafted")
    conn.commit()

    assert answers_bank.cmd_edit(conn, aid, "Updated A") is True
    row = conn.execute("SELECT answer FROM answers WHERE id = ?", (aid,)).fetchone()
    assert row["answer"] == "Updated A"

    drafts = answers_bank.get_answers(conn, status="drafted")
    assert len(drafts) >= 1
    assert any(d["id"] == aid and d["answer"] == "Updated A" for d in drafts)
    conn.close()
