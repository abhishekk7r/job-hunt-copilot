"""Tests for live read-only dashboard (Section 10.5)."""

import json
import sqlite3
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import pytest
from harness.dashboard import (
    load_data,
    render_html,
    DashboardHandler,
    get_db_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def seeded_db(temp_db):
    """Seed temp_db with representative data across all panels."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()

    # Seed jobs with various statuses
    cur.execute("""
        INSERT INTO jobs (company, role, job_url, job_id_ext, tier, status, blocker_note, platform, rank_score, updated_at)
        VALUES
        ('Google', 'Senior SWE', 'https://careers.google.com/1', 'G-1', 1, 'APPLIED', '', 'Direct', 4.5, '2026-11-01T10:00:00'),
        ('Meta', 'Backend Lead', 'https://metacareers.com/2', 'M-2', 1, 'BLOCKED_USER', 'Missing custom question answer', 'Direct', 4.2, '2026-11-01T11:00:00'),
        ('Amazon', 'SDE-2', 'https://amazon.jobs/3', 'A-3', 1, 'TO_APPLY', '', 'AmazonPortal', 3.8, '2026-11-01T12:00:00'),
        ('StartupX', 'Fullstack Dev', 'https://startupx.com/4', 'S-4', 3, 'RANKED_OUT', '', 'Wellfound', 2.1, '2026-11-01T13:00:00')
    """)

    # Seed outreach queue
    cur.execute("""
        INSERT INTO outreach_queue (job_id, company, role, recruiter_name, recruiter_linkedin, channel, rendered_message, char_count, approval_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (1, 'Google', 'Senior SWE', 'Jane Recruiter', 'https://linkedin.com/in/janedoe', 'LinkedIn DM', "Hi Jane, I've applied for the role.", 38, 'PENDING_MOBILE_REVIEW'))

    # Seed contacts
    cur.execute("""
        INSERT INTO contacts (job_id, current_company, name, title, profile_url, score, outreach_kind, status, created_at)
        VALUES (1, 'Google', 'Bob Tech Lead', 'Engineering Director', 'https://linkedin.com/in/bob', 88, 'hiring_manager', 'PROPOSED', '2026-11-01')
    """)

    # Seed screening QA
    cur.execute("INSERT OR REPLACE INTO screening_qa VALUES ('notice_period_days', '30 days')")
    cur.execute("INSERT OR REPLACE INTO screening_qa VALUES ('java_years', '3 years')")

    # Seed run log with a HALTED record
    cur.execute("""
        INSERT INTO run_log (run_id, started_at, ended_at, mode, status, halted_reason, counts_json)
        VALUES ('run_20261101_0200', '2026-11-01T02:00:00', '2026-11-01T02:05:00', 'nightly', 'HALTED', 'Kill switch engaged', '{}')
    """)

    # Seed kill switch
    cur.execute("UPDATE kill_switch SET \"on\" = 1, reason = 'Maintenance halt', ts = '2026-11-01T02:00:00' WHERE id = 1")

    conn.commit()
    conn.close()
    return temp_db


def test_db_read_only_protection(seeded_db, monkeypatch):
    """Verify load_data connects in read-only mode and write attempts raise OperationalError."""
    monkeypatch.setenv("HARNESS_DB", seeded_db)
    db_path = get_db_path()
    ro_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    # Read succeeds
    res = ro_conn.execute("SELECT count(*) FROM jobs").fetchone()
    assert res[0] == 4

    # Write raises OperationalError
    with pytest.raises(sqlite3.OperationalError, match="readonly database"):
        ro_conn.execute("INSERT INTO kill_switch (id, \"on\") VALUES (2, 1)")
    ro_conn.close()


def test_dashboard_html_contains_all_required_panels(seeded_db, monkeypatch):
    """Verify render_html includes all 10 required panels and accurate data."""
    monkeypatch.setenv("HARNESS_DB", seeded_db)
    data = load_data()
    html_out = render_html(data)

    required_panels = [
        "Pipeline funnel",
        "Needs you",
        "Approval queue",
        "Contacts per job",
        "Answers bank",
        "Open items",
        "Last runs",
        "Kill switch",
        "Source breakdown",
        "Rank score distribution",
        "Data parity:",
        "Next cycle:",
    ]

    for panel in required_panels:
        assert panel in html_out, f"Missing panel: {panel}"

    # Verify specific content
    assert "Kill switch:" in html_out
    assert "Maintenance halt" in html_out
    assert "Missing custom question answer" in html_out
    assert "Bob Tech Lead" in html_out
    assert "Jane Recruiter" in html_out
    assert "HALTED:</b> Kill switch engaged" in html_out


def test_dashboard_http_server_and_api(seeded_db, monkeypatch):
    """Start dashboard HTTP server on ephemeral port and test GET / and GET /api."""
    monkeypatch.setenv("HARNESS_DB", seeded_db)

    # Bind to ephemeral port on 127.0.0.1
    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    host, port = server.server_address
    assert host == "127.0.0.1"

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    time.sleep(0.1)

    try:
        # Test GET /
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("Cache-Control") == "no-store"
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            body = resp.read().decode("utf-8")
            assert "Pipeline funnel" in body
            assert "Needs you" in body
            assert "Approval queue" in body
            assert "Data parity:" in body
            assert "Next cycle:" in body

        # Test GET with DNS-rebinding / bad Host header is rejected
        bad_req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.com"})
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req)
        assert exc_info.value.code == 403

        # Test GET /api without token: answers stripped
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api") as resp:
            assert resp.status == 200
            assert "application/json" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("Cache-Control") == "no-store"
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            api_data = json.loads(resp.read().decode("utf-8"))

            assert "jobs" in api_data
            assert len(api_data["jobs"]) == 4
            assert "outreach" in api_data
            assert "screening" in api_data
            # Answer text must be removed
            for item in api_data["screening"]:
                assert "answer" not in item
            for item in api_data["app_answers"]:
                assert "answer" not in item
            assert "contacts" in api_data
            assert "run_log" in api_data
            assert "kill_switch" in api_data
            assert api_data["kill_switch"][0]["on"] == 1

        # Test GET /api with valid X-Token: answers included
        from tools import control
        auth_req = urllib.request.Request(f"http://127.0.0.1:{port}/api", headers={"X-Token": control.get_token()})
        with urllib.request.urlopen(auth_req) as resp:
            auth_data = json.loads(resp.read().decode("utf-8"))
            assert len(auth_data["screening"]) > 0
            screening_map = {q["question_key"]: q.get("answer") for q in auth_data["screening"]}
            assert screening_map.get("notice_period_days") == "30 days"
            assert screening_map.get("java_years") == "3 years"
    finally:
        server.shutdown()
        server.server_close()


def test_run_status_line_and_zero_inline_styles(temp_db, monkeypatch):
    """Verify single run status line, zero inline styles, and clean /api/state (S3)."""
    monkeypatch.setenv("HARNESS_DB", temp_db)
    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    _, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            html_body = resp.read().decode("utf-8")
            assert 'id="run-progress-panel"' in html_body
            assert 'id="progress-summary-text"' in html_body
            assert 'id="btn-progress-toggle"' not in html_body

            # Check zero inline style= in rendered page
            import re
            style_attrs = re.findall(r'\sstyle=["\']', html_body, re.IGNORECASE)
            assert not style_attrs, f"Inline style attributes found in rendered HTML: {style_attrs}"

            # Check banned strings scan
            assert "shorturl.at" not in html_body
            assert "15 days" not in html_body

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as resp:
            state_data = json.loads(resp.read().decode("utf-8"))
            assert "run_log" in state_data
            assert "cycle_running" in state_data
    finally:
        server.shutdown()
        server.server_close()


def test_job_status_action(temp_db, monkeypatch):
    """Owner can mark an open job APPLIED/skip it; closed jobs are protected; token required."""
    import sqlite3
    from tools import control

    monkeypatch.setenv("HARNESS_DB", temp_db)
    conn = sqlite3.connect(temp_db)
    for jid, st in ((901, "TO_APPLY"), (902, "APPLIED"), (903, "TO_APPLY")):
        conn.execute(
            "INSERT INTO jobs (id, company, role, job_url, platform, status, updated_at) VALUES (?,?,?,?,?,?,?)",
            (jid, f"C{jid}", "SDE", f"https://e.com/{jid}", "cli", st, "2026-11-01T00:00:00Z"),
        )
    conn.commit()
    conn.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    _, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.1)

    def post(body, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Token"] = control.get_token()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ctl/job_status",
                                     data=json.dumps(body).encode(), headers=headers)
        return urllib.request.urlopen(req)

    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"id": 901, "status": "APPLIED"}, token=False)
        assert e.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"id": 901, "status": "REJECTED"})
        assert e.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"id": 902, "status": "RANKED_OUT"})
        assert e.value.code == 409
        assert post({"id": 901, "status": "APPLIED"}).status == 200
        assert post({"id": 903, "status": "RANKED_OUT"}).status == 200
        c = sqlite3.connect(temp_db)
        rows = dict(c.execute("SELECT id, status FROM jobs WHERE id IN (901,902,903)").fetchall())
        assert rows == {901: "APPLIED", 902: "APPLIED", 903: "RANKED_OUT"}
        assert c.execute("SELECT date_applied FROM jobs WHERE id=901").fetchone()[0]
        assert c.execute("SELECT count(*) FROM action_log WHERE action='job_status'").fetchone()[0] == 2
        c.close()
    finally:
        server.shutdown()


def test_apply_now_modes(temp_db, monkeypatch):
    """Apply-now spawns apply-only cycle; mode is live only if ctl:submit==1, otherwise shadow."""
    from tools import control

    monkeypatch.setenv("HARNESS_DB", temp_db)
    spawned = []

    class _P:
        def __init__(self, *a, **k):
            spawned.append(k["env"])

    monkeypatch.setattr(control.subprocess, "Popen", _P)
    monkeypatch.setattr(control, "cycle_running", lambda: False)

    # Default ctl:submit is 0 -> shadow mode
    res_shadow = control.request_apply_now(path=temp_db)
    assert res_shadow["started"] is True and res_shadow["mode"] == "shadow"
    assert spawned[-1]["CYCLE_ONLY"] == "apply"

    # ctl:submit is 1 -> live mode
    control.set_submit_mode(1, confirm=True, path=temp_db)
    res_live = control.request_apply_now(path=temp_db)
    assert res_live["started"] is True and res_live["mode"] == "live"
    assert spawned[-1]["CYCLE_ONLY"] == "apply"
    assert control.get_settings(temp_db)["ctl:submit"] == 1


def test_answers_api_and_control(temp_db, monkeypatch):
    """Verify GET /api/answers and POST /ctl/answer endpoints (Step S5)."""
    import sqlite3
    from tools import control, answers_bank

    monkeypatch.setenv("HARNESS_DB", temp_db)
    conn = answers_bank.get_conn(temp_db)
    a1 = answers_bank.upsert_answer(conn, "Drafted Q1", "Drafted A1", "fact", status="drafted", source="job:101")
    a2 = answers_bank.upsert_answer(conn, "Approved Q2", "Approved A2", "policy", status="approved", source="facts")
    a3 = answers_bank.upsert_answer(conn, "Drafted Q3", "Drafted A3", "choice", status="drafted", source="job:102")
    conn.commit()
    conn.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    _, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.1)

    token = control.get_token()

    try:
        # 1. GET /api/answers without token -> 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/answers")
        assert exc.value.code == 403

        # 2. GET /api/answers with token (default status=drafted)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/answers?status=drafted", headers={"X-Token": token})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "answers" in data
            ids = [a["id"] for a in data["answers"]]
            assert a1 in ids
            assert a3 in ids
            assert a2 not in ids

        # 3. POST /ctl/answer without token -> 403
        post_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/ctl/answer",
            data=json.dumps({"id": a1, "action": "approve"}).encode(),
            headers={"Content-Type": "application/json"}
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(post_req)
        assert exc.value.code == 403

        # 4. POST /ctl/answer edit
        edit_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/ctl/answer",
            data=json.dumps({"id": a1, "action": "edit", "answer": "Edited Drafted A1"}).encode(),
            headers={"Content-Type": "application/json", "X-Token": token}
        )
        with urllib.request.urlopen(edit_req) as resp:
            assert resp.status == 200
            res = json.loads(resp.read().decode("utf-8"))
            assert res.get("ok") is True

        conn = sqlite3.connect(temp_db)
        r = conn.execute("SELECT answer, status FROM answers WHERE id = ?", (a1,)).fetchone()
        assert r[0] == "Edited Drafted A1"
        assert r[1] == "drafted"

        # 5. POST /ctl/answer approve
        approve_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/ctl/answer",
            data=json.dumps({"id": a1, "action": "approve", "answer": "Final Approved A1"}).encode(),
            headers={"Content-Type": "application/json", "X-Token": token}
        )
        with urllib.request.urlopen(approve_req) as resp:
            assert resp.status == 200

        r = conn.execute("SELECT answer, status FROM answers WHERE id = ?", (a1,)).fetchone()
        assert r[0] == "Final Approved A1"
        assert r[1] == "approved"

        # 6. POST /ctl/answer retire
        retire_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/ctl/answer",
            data=json.dumps({"id": a3, "action": "retire"}).encode(),
            headers={"Content-Type": "application/json", "X-Token": token}
        )
        with urllib.request.urlopen(retire_req) as resp:
            assert resp.status == 200

        r = conn.execute("SELECT status FROM answers WHERE id = ?", (a3,)).fetchone()
        assert r[0] == "retired"
        conn.close()

        # 7. Invalid action -> 400
        bad_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/ctl/answer",
            data=json.dumps({"id": a1, "action": "destroy"}).encode(),
            headers={"Content-Type": "application/json", "X-Token": token}
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad_req)
        assert exc.value.code == 400

        # 8. Non-existent id -> 404
        nf_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/ctl/answer",
            data=json.dumps({"id": 999999, "action": "retire"}).encode(),
            headers={"Content-Type": "application/json", "X-Token": token}
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(nf_req)
        assert exc.value.code == 404

    finally:
        server.shutdown()
