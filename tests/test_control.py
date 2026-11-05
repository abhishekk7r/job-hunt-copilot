"""Tests for tools/control.py, dashboard POST auth, and bin/cycle.sh dry-run."""

import json
import os
import sqlite3
import subprocess
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tools import control

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def token(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "TOKEN_FILE", tmp_path / "tok")
    return control.get_token()


def test_toggles_and_should_run(temp_db):
    sr = control.should_run(temp_db)
    assert sr["run"] is True
    assert "jobs" not in sr
    control.set_toggle("schedule", False, temp_db)
    r = control.should_run(temp_db)
    assert r["run"] is False and r["reason"] == "schedule paused"
    control.set_toggle("schedule", True, temp_db)
    control.set_toggle("people", False, temp_db)
    assert control.should_run(temp_db)["people"] is False
    with pytest.raises(ValueError):
        control.set_toggle("jobs", False, temp_db)
    with pytest.raises(ValueError):
        control.set_toggle("bogus", True, temp_db)


def test_submit_mode_and_audit(temp_db):
    # 1. Default value is 0
    s = control.get_settings(temp_db)
    assert s["ctl:submit"] == 0
    assert control.should_run(temp_db)["submit"] == 0

    # 2. Strict type validation: reject non-0/1 or bad types
    for bad in (-1, 2, 99, 2.0, "1", "0", "invalid", None, 1.5):
        with pytest.raises(ValueError):
            control.set_submit_mode(bad, path=temp_db)

    # 3. Transition: 0 -> 1 without confirmation is refused
    with pytest.raises(ValueError) as exc:
        control.set_submit_mode(1, confirm=False, path=temp_db)
    assert "switching to Live mode requires explicit confirmation" in str(exc.value)

    # 4. Transition: 0 -> 1 with confirm=True SUCCEEDS
    s1 = control.set_submit_mode(1, confirm=True, path=temp_db)
    assert s1["ctl:submit"] == 1
    assert control.should_run(temp_db)["submit"] == 1

    # Check action_log has 0->1 transition row
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    al_rows = conn.execute("SELECT * FROM action_log WHERE action = 'submit_mode'").fetchall()
    assert len(al_rows) == 1
    assert al_rows[0]["result"] == "0->1"
    conn.close()

    # 5. Downward transition: 1 -> 0 allowed without confirm
    s0 = control.set_submit_mode(0, path=temp_db)
    assert s0["ctl:submit"] == 0
    assert control.should_run(temp_db)["submit"] == 0

    conn = sqlite3.connect(temp_db)
    al_rows = conn.execute("SELECT result FROM action_log WHERE action = 'submit_mode' ORDER BY id").fetchall()
    assert [r[0] for r in al_rows] == ["0->1", "1->0"]
    conn.close()


def test_kill_switch_blocks_run(temp_db):
    control.set_kill_switch(True, "t", temp_db)
    r = control.should_run(temp_db)
    assert r["run"] is False and r["reason"] == "kill switch on"
    control.set_kill_switch(False, path=temp_db)
    assert control.should_run(temp_db)["run"] is True


def test_token_file_mode_and_check(token):
    assert oct(os.stat(control.TOKEN_FILE).st_mode)[-3:] == "600"
    assert control.check_token(token) and not control.check_token("nope") and not control.check_token(None)


def _serve(temp_db):
    from harness import dashboard
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _post(port, path, body, token=None, host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Token", token)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_dashboard_post_requires_token_and_local_host(temp_db, token):
    srv, port = _serve(temp_db)
    try:
        assert _post(port, "/ctl/toggle", {"name": "schedule", "on": False})[0] == 403
        assert _post(port, "/ctl/toggle", {"name": "schedule", "on": False}, token="bad")[0] == 403
        assert _post(port, "/ctl/toggle", {"name": "schedule", "on": False}, token=token, host="evil.com")[0] == 403
        code, body = _post(port, "/ctl/toggle", {"name": "schedule", "on": False}, token=token)
        assert code == 200 and body["ctl:schedule"] == 0
        assert _post(port, "/ctl/kill", {"on": True}, token=token)[0] == 200
        assert control.should_run(temp_db)["reason"] == "kill switch on"
        assert _post(port, "/ctl/mark", {"id": 1, "status": "BOGUS"}, token=token)[0] == 400
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "Run cycle now" in page and "KILL SWITCH" in page and "Submit for real" in page
    finally:
        srv.shutdown()


def test_dashboard_post_submit(temp_db, token):
    srv, port = _serve(temp_db)
    try:
        # Auth and host check
        assert _post(port, "/ctl/submit", {"on": True, "confirm": True})[0] == 403
        assert _post(port, "/ctl/submit", {"on": True, "confirm": True}, token="bad")[0] == 403
        assert _post(port, "/ctl/submit", {"on": True, "confirm": True}, token=token, host="evil.com")[0] == 403

        # Turning on without confirm is refused (400)
        c_noconf, b_noconf = _post(port, "/ctl/submit", {"on": True}, token=token)
        assert c_noconf == 400
        assert "switching to Live mode requires explicit confirmation" in b_noconf["error"]

        # Turning on with confirm succeeds (200)
        code1, body1 = _post(port, "/ctl/submit", {"on": True, "confirm": True}, token=token)
        assert code1 == 200
        assert body1["ok"] is True
        assert body1["submit"] == 1
        assert control.get_settings(temp_db)["ctl:submit"] == 1

        # Turning off requires no confirm (200)
        code0, body0 = _post(port, "/ctl/submit", {"on": False}, token=token)
        assert code0 == 200
        assert body0["submit"] == 0
        assert control.get_settings(temp_db)["ctl:submit"] == 0
    finally:
        srv.shutdown()


def test_cycle_dry_run_logs_and_respects_pause(temp_db, tmp_path):
    env = dict(os.environ, HARNESS_DB=temp_db, CYCLE_DRY_RUN="1", CYCLE_LOCK=str(tmp_path / "lock"), CYCLE_LOG_DIR=str(tmp_path / "cycle_logs"))
    r = subprocess.run(["bash", str(REPO_ROOT / "bin" / "cycle.sh")], env=env, capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0, r.stderr
    conn = sqlite3.connect(temp_db)
    assert conn.execute("SELECT status FROM run_log WHERE mode='cycle'").fetchone()[0] == "COMPLETED"
    control.set_toggle("schedule", False, temp_db)
    conn.execute("DELETE FROM run_log"); conn.commit()
    subprocess.run(["bash", str(REPO_ROOT / "bin" / "cycle.sh")], env=env, capture_output=True, text=True, cwd=REPO_ROOT)
    assert conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 0


def test_dashboard_get_security_headers_and_rebinding_protection(temp_db):
    srv, port = _serve(temp_db)
    try:
        # Host header check on GET: evil.com should return 403
        req_evil = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.com"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req_evil)
        assert exc.value.code == 403

        # Standard GET should succeed with security headers
        req_ok = urllib.request.Request(f"http://127.0.0.1:{port}/")
        with urllib.request.urlopen(req_ok) as resp:
            assert resp.status == 200
            assert resp.headers.get("Cache-Control") == "no-store"
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            body = resp.read().decode()
            assert "Data parity:" in body
            assert "Next cycle:" in body
    finally:
        srv.shutdown()


def test_dashboard_get_api_token_sanitization(temp_db, token):
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT OR REPLACE INTO screening_qa VALUES ('java_exp', '5 years')")
    conn.execute("INSERT INTO app_story_answers (application, question, answer, status, saved_at) VALUES ('Acme', 'Tell us about Java', 'Used Java 21', 'SAVED', '2026-11-01')")
    conn.commit()
    conn.close()

    srv, port = _serve(temp_db)
    try:
        # Unauthenticated GET /api: answer text stripped
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api") as resp:
            assert resp.status == 200
            assert resp.headers.get("Cache-Control") == "no-store"
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            data = json.loads(resp.read().decode())
            qa_keys = [q["question_key"] for q in data["screening"]]
            assert "java_exp" in qa_keys
            for q in data["screening"]:
                assert "answer" not in q
            for a in data["app_answers"]:
                assert "answer" not in a
                assert "question" in a

        # Authenticated GET /api: answer text included
        req_auth = urllib.request.Request(f"http://127.0.0.1:{port}/api", headers={"X-Token": token})
        with urllib.request.urlopen(req_auth) as resp:
            data = json.loads(resp.read().decode())
            assert any(q.get("answer") == "5 years" for q in data["screening"])
            assert any(a.get("answer") == "Used Java 21" for a in data["app_answers"])
    finally:
        srv.shutdown()


def test_dashboard_parity_and_next_cycle_render(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO run_log (run_id, started_at, mode, status) VALUES ('cycle_test', '2026-11-02T12:00:00Z', 'cycle', 'COMPLETED')")
    from datetime import datetime, timezone
    due = int(datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc).timestamp())
    conn.execute("INSERT OR REPLACE INTO budgets (key, val) VALUES ('ctl:next_due', ?)", (due,))
    conn.commit()
    conn.close()

    srv, port = _serve(temp_db)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            html = resp.read().decode()
            assert "Data parity:" in html
            assert "Next cycle:" in html
            # Next run is the stored schedule time (system clock), not last start + 6h
            assert "2026-11-02 18:00 UTC" in html
    finally:
        srv.shutdown()
