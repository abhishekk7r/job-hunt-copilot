"""Tests for overnight orchestration, nightly.sh, killswitch CLI, and digest generation (Section 10.6)."""

import os
import sqlite3
import subprocess
from pathlib import Path
import pytest
from tools.digest import generate_digest_content

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def nightly_env(temp_db, tmp_path):
    """Setup temporary environment for testing nightly orchestration without side effects."""
    lock_file = tmp_path / "test_nightly.lock"
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Seed initial test data in temp_db
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO jobs (company, role, job_url, source_key, platform, status, rank_score, rank_verdict, updated_at)
        VALUES
        ('Stark Industries', 'SDE-2 Backend', 'https://starkindustries.com/1', 'stark:1', 'Direct', 'TO_APPLY', 4.8, 'High', '2026-11-01T02:00:00'),
        ('Hooli', 'Backend Lead', 'https://hooli.com/2', 'hooli:2', 'Direct', 'BLOCKED_USER', 4.2, 'High', '2026-11-01T02:00:00')
    """)
    cur.execute("""
        UPDATE jobs SET blocker_note = 'OTP verification required on Hooli careers' WHERE company = 'Hooli'
    """)
    conn.commit()
    conn.close()

    env = os.environ.copy()
    env["HARNESS_DB"] = temp_db
    env["NIGHTLY_LOCKFILE"] = str(lock_file)
    env["CYCLE_LOG_DIR"] = str(reports_dir / "cycle_logs")
    return {
        "db": temp_db,
        "lock": str(lock_file),
        "reports": reports_dir,
        "env": env
    }


def test_killswitch_cli(nightly_env):
    """Test bin/killswitch on|off|status CLI operations."""
    cli = str(REPO_ROOT / "bin" / "killswitch")
    env = nightly_env["env"]

    # Initial state should be OFF
    res = subprocess.run([cli, "status"], env=env, capture_output=True, text=True)
    assert "Kill switch: OFF" in res.stdout

    # Turn ON with reason
    res_on = subprocess.run([cli, "on", "Investigating API anomaly"], env=env, capture_output=True, text=True)
    assert res_on.returncode == 0
    assert "Kill switch ENGAGED (ON): Investigating API anomaly" in res_on.stdout

    # Status should report ON
    res_stat = subprocess.run([cli, "status"], env=env, capture_output=True, text=True)
    assert "Kill switch: ON (HALTED) - Reason: Investigating API anomaly" in res_stat.stdout

    # Turn OFF
    res_off = subprocess.run([cli, "off"], env=env, capture_output=True, text=True)
    assert res_off.returncode == 0
    assert "Kill switch DISENGAGED (OFF)" in res_off.stdout


def test_digest_content_generation(nightly_env):
    """Verify digest contains all required sections, funnel counts, blockers, and ranked jobs."""
    conn = sqlite3.connect(nightly_env["db"])
    conn.row_factory = sqlite3.Row
    digest = generate_digest_content(conn, "2026-11-01")
    conn.close()

    assert "Daily Job Search Digest — 2026-11-01" in digest
    assert "Pipeline Funnel" in digest
    assert "Blocked Applications (Action Required)" in digest
    assert "Hooli" in digest
    assert "OTP verification required" in digest
    assert "Top Ranked Jobs" in digest
    assert "Stark Industries" in digest
    assert "Skipped & Ranked Out" in digest
    assert "Halted Runs & System Errors" in digest


def test_nightly_happy_path(nightly_env):
    """Simulate successful overnight run producing run_log record and digest."""
    script = str(REPO_ROOT / "bin" / "nightly.sh")
    res = subprocess.run([script], env=nightly_env["env"], capture_output=True, text=True)

    assert res.returncode == 0
    assert "Starting Nightly Orchestration" in res.stdout
    assert "Nightly Orchestration Finished Successfully" in res.stdout

    # Check run_log in DB
    conn = sqlite3.connect(nightly_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, mode FROM run_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row[0] == "COMPLETED"
    assert row[1] == "nightly"
    conn.close()


def test_nightly_halts_immediately_when_killswitch_engaged(nightly_env):
    """Verify kill switch halts execution within one step and logs HALTED status."""
    cli = str(REPO_ROOT / "bin" / "killswitch")
    script = str(REPO_ROOT / "bin" / "nightly.sh")
    env = nightly_env["env"]

    # Engage kill switch
    subprocess.run([cli, "on", "Scheduled maintenance halt"], env=env, check=True)

    res = subprocess.run([script], env=env, capture_output=True, text=True)
    assert res.returncode == 3
    assert "HALTED: Kill switch is ENGAGED" in res.stderr

    # Check run_log was marked HALTED with reason
    conn = sqlite3.connect(nightly_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row[0] == "HALTED"
    assert "Scheduled maintenance halt" in row[1]
    conn.close()


def test_nightly_halts_on_simulated_captcha_or_challenge(nightly_env):
    """Verify simulated login/CAPTCHA challenge aborts overnight run and records reason."""
    script = str(REPO_ROOT / "bin" / "nightly.sh")
    env = dict(nightly_env["env"])
    env["SIMULATE_CHALLENGE"] = "CAPTCHA"

    res = subprocess.run([script], env=env, capture_output=True, text=True)
    assert res.returncode == 4
    assert "HALTED: Challenge detected (CAPTCHA)" in res.stderr

    # Check run_log
    conn = sqlite3.connect(nightly_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row[0] == "HALTED"
    assert "CAPTCHA" in row[1]
    conn.close()


def test_nightly_lock_prevents_concurrent_runs(nightly_env):
    """Verify run lock rejects simultaneous execution while active PID is alive."""
    script = str(REPO_ROOT / "bin" / "nightly.sh")
    lock_file = Path(nightly_env["lock"])

    # Write current test runner process ID into lockfile
    lock_file.write_text(str(os.getpid()))

    res = subprocess.run([script], env=nightly_env["env"], capture_output=True, text=True)
    assert res.returncode == 2
    assert "Another nightly run is currently active" in res.stderr


def test_nightly_idempotency_no_duplicate_jobs_or_queue(nightly_env):
    """Verify re-running nightly pipeline does not duplicate rows."""
    script = str(REPO_ROOT / "bin" / "nightly.sh")
    env = nightly_env["env"]

    # First run
    res1 = subprocess.run([script], env=env, capture_output=True, text=True)
    assert res1.returncode == 0

    conn = sqlite3.connect(nightly_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM jobs")
    count1 = cur.fetchone()[0]
    conn.close()

    # Second run immediately after
    res2 = subprocess.run([script], env=env, capture_output=True, text=True)
    assert res2.returncode == 0

    conn = sqlite3.connect(nightly_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM jobs")
    count2 = cur.fetchone()[0]
    conn.close()

    assert count1 == count2, "Duplicate rows detected on repeated nightly run"
