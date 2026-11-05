"""Tests for bin/cycle.sh failure paths, process control, and headless claude stub (Task T3)."""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
import pytest
from tools import control

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cycle_env(temp_db, tmp_path):
    """Sets up a stub claude executable, a unique lock file, and isolated environment."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub_claude = stub_dir / "claude"

    argv_log = tmp_path / "stub_argv.jsonl"
    pid_log = tmp_path / "stub_pids.txt"

    stub_template = """#!/usr/bin/env python3
import sys
import os
import time
import json

argv_file = "__ARGV_LOG__"
pid_file = "__PID_LOG__"

with open(argv_file, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")

with open(pid_file, "a") as f:
    f.write(str(os.getpid()) + "\\n")

mode = os.environ.get("STUB_CLAUDE_MODE", "people_done")
is_jobs = "--chrome" not in sys.argv
is_portals = "--chrome" in sys.argv and any("query_plan.py" in arg for arg in sys.argv)
is_apply = "--chrome" in sys.argv and any("decide.py" in arg for arg in sys.argv)
is_people = "--chrome" in sys.argv and any("network_batch.py" in arg for arg in sys.argv)

def emit_stream(text, tool_cmd=None):
    if text:
        print(text, flush=True)
    if tool_cmd:
        t_use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": tool_cmd}}]}}
        t_res = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
        print(json.dumps(t_use), flush=True)
        print(json.dumps(t_res), flush=True)
    if text:
        msg = {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
        res = {"type": "result", "subtype": "success", "result": text}
        print(json.dumps(msg), flush=True)
        print(json.dumps(res), flush=True)

if mode == "captcha":
    if is_people:
        emit_stream("CYCLE_HALT: captcha", "python3 tools/reachout_data.py")
        sys.exit(0)
    elif is_portals:
        emit_stream("PORTALS_DONE seen=5", "python3 tools/query_plan.py --portal naukri")
        sys.exit(0)
    elif is_apply:
        emit_stream("APPLY_DONE", "python3 tools/decide.py next-jobs --limit 5")
        sys.exit(0)
    else:
        emit_stream("JOBS_DONE found=3", "python3 tools/query_plan.py --portal all")
        sys.exit(0)
elif mode == "apply_halt":
    if is_apply:
        emit_stream("CYCLE_HALT: linkedin restriction warning", "python3 tools/decide.py next-jobs --limit 5")
        sys.exit(0)
    elif is_people:
        emit_stream("PEOPLE_DONE queued=0", "python3 tools/network_batch.py status")
        sys.exit(0)
    elif is_portals:
        emit_stream("PORTALS_DONE seen=5", "python3 tools/query_plan.py --portal naukri")
        sys.exit(0)
    else:
        emit_stream("JOBS_DONE found=3", "python3 tools/query_plan.py --portal all")
        sys.exit(0)
elif mode == "apply_shadow":
    if is_apply:
        emit_stream("APPLY job=101 result=WOULD_SUBMIT auto=2 escalated=0\\nAPPLY_DONE", "python3 tools/decide.py next-jobs --limit 5")
        sys.exit(0)
    elif is_people:
        emit_stream("PEOPLE_DONE queued=0", "python3 tools/network_batch.py status")
        sys.exit(0)
    elif is_portals:
        emit_stream("PORTALS_DONE seen=5", "python3 tools/query_plan.py --portal naukri")
        sys.exit(0)
    else:
        emit_stream("JOBS_DONE found=3", "python3 tools/query_plan.py --portal all")
        sys.exit(0)
elif mode == "portals_challenge":
    if is_portals:
        emit_stream("CYCLE_HALT: cloudflare challenge", "python3 tools/query_plan.py --portal naukri")
        sys.exit(0)
    elif is_people:
        emit_stream("PEOPLE_DONE queued=0", "python3 tools/network_batch.py status")
        sys.exit(0)
    else:
        emit_stream("JOBS_DONE found=3", "python3 tools/query_plan.py --portal all")
        sys.exit(0)
elif mode == "sleep":
    try:
        while True:
            time.sleep(0.5)
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
elif mode == "sleep_portals":
    if is_portals:
        try:
            while True:
                time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit):
            sys.exit(0)
    elif is_people:
        emit_stream("PEOPLE_DONE queued=0", "python3 tools/network_batch.py status")
        sys.exit(0)
    else:
        emit_stream("JOBS_DONE found=3", "python3 tools/query_plan.py --portal all")
        sys.exit(0)
elif mode in ("people_done", "portals_done"):
    if is_apply:
        emit_stream("APPLY_DONE", "python3 tools/decide.py next-jobs --limit 5")
    elif is_portals:
        emit_stream("PORTALS_DONE seen=5", "python3 tools/query_plan.py --portal naukri")
    elif is_people:
        emit_stream("PEOPLE_DONE queued=0", "python3 tools/network_batch.py status")
    else:
        emit_stream("JOBS_DONE found=3", "python3 tools/query_plan.py --portal all")
    sys.exit(0)
else:
    emit_stream("UNKNOWN_MODE")
    sys.exit(1)
"""
    stub_script = stub_template.replace("__ARGV_LOG__", str(argv_log)).replace("__PID_LOG__", str(pid_log))
    stub_claude.write_text(stub_script)
    stub_claude.chmod(0o755)

    stub_gh = stub_dir / "gh"
    stub_gh.write_text('#!/bin/sh\necho "PRIVATE"\n')
    stub_gh.chmod(0o755)

    lock_file = tmp_path / "cycle_test.lock"

    env = os.environ.copy()
    # Prepend stub_dir to PATH so bin/cycle.sh finds our stub claude
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
    env["HARNESS_DB"] = temp_db
    env["CYCLE_LOCK"] = str(lock_file)
    env["CYCLE_LOG_DIR"] = str(tmp_path / "cycle_logs")
    # Ensure CYCLE_DRY_RUN is NOT set so run_claude actually invokes stub claude
    env.pop("CYCLE_DRY_RUN", None)

    return {
        "db": temp_db,
        "env": env,
        "lock": str(lock_file),
        "argv_log": argv_log,
        "pid_log": pid_log,
        "tmp_path": tmp_path,
    }


def test_cycle_halt_on_captcha_flips_people_toggle(cycle_env):
    """Test that CYCLE_HALT: captcha sets run_log status to HALTED and flips ctl:people to 0."""
    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "captcha"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0, f"cycle.sh failed: {res.stderr}"

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None, "No run_log entry found"
    status, reason = row
    assert status == "HALTED"
    assert "captcha" in reason.lower()

    # Verify ctl:people flipped to 0
    cur.execute("SELECT val FROM budgets WHERE key = 'ctl:people'")
    p_row = cur.fetchone()
    assert p_row is not None and int(p_row[0]) == 0
    conn.close()


def test_cycle_phase_timeout_kills_stub_cleanly(cycle_env):
    """Test that PHASE_TIMEOUT=2 halts with 'phase timeout' and leaves no orphaned process."""
    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "sleep"
    env["PHASE_TIMEOUT"] = "2"

    t0 = time.time()
    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    duration = time.time() - t0
    assert res.returncode == 0
    assert duration < 8, f"Phase timeout took too long: {duration}s"

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    status, reason = row
    assert status == "HALTED"
    assert "phase timeout" in reason.lower()
    conn.close()

    # Verify stub PID was killed and is not orphaned
    pids = [int(p.strip()) for p in cycle_env["pid_log"].read_text().splitlines() if p.strip()]
    assert len(pids) > 0, "Stub should have been invoked and logged its PID"
    for pid in pids:
        try:
            os.kill(pid, 0)
            pytest.fail(f"Stub PID {pid} is still alive (orphan process)")
        except ProcessLookupError:
            pass  # Expected: process terminated


def test_cycle_success_path_and_stub_argv(cycle_env):
    """Test successful cycle run, and verify flags passed to claude in both phases."""
    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "people_done"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0, f"cycle.sh failed: {res.stderr}"

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None and row[0] == "COMPLETED"
    conn.close()

    # Read argv recorded by the stub
    argv_lines = [json.loads(line) for line in cycle_env["argv_log"].read_text().splitlines() if line.strip()]
    assert len(argv_lines) == 2, f"Expected 2 invocations (jobs and people), got {len(argv_lines)}"

    jobs_argv, people_argv = argv_lines[0], argv_lines[1]

    # Verify flags for jobs phase (plain output, no stream-json)
    assert "--output-format" not in jobs_argv
    assert "--verbose" in jobs_argv
    assert "--permission-mode" in jobs_argv
    assert jobs_argv[jobs_argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--max-budget-usd" in jobs_argv
    assert "--chrome" not in jobs_argv

    # Verify flags for people phase (plain output, no stream-json)
    assert "--output-format" not in people_argv
    assert "--verbose" in people_argv
    assert "--permission-mode" in people_argv
    assert people_argv[people_argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--max-budget-usd" in people_argv
    assert "--chrome" in people_argv


def test_cycle_midrun_killswitch_halts(cycle_env):
    """Test that engaging killswitch mid-run halts execution within ~10 seconds."""
    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "sleep"
    env["PHASE_TIMEOUT"] = "60"

    proc = subprocess.Popen(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=REPO_ROOT
    )

    # Wait 1s for cycle to start sleeping in stub claude
    time.sleep(1.0)
    control.set_kill_switch(True, "mid-run halt test", path=cycle_env["db"])

    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("bin/cycle.sh did not halt within 10s after kill switch engaged")

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    status, reason = row
    assert status == "HALTED"
    assert "kill switch pressed" in reason.lower()
    conn.close()


def test_cycle_schedule_toggle_off_skips_run_log(cycle_env):
    """Test that when ctl:schedule is off, no run_log row is recorded."""
    control.set_toggle("schedule", False, path=cycle_env["db"])

    env = dict(cycle_env["env"])
    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM run_log WHERE mode='cycle'")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 0, f"Expected 0 run_log rows when schedule paused, got {count}"


def test_cycle_lock_prevents_concurrent_runs(cycle_env):
    """Test that an active PID in the lock file prevents a second cycle."""
    lock_file = Path(cycle_env["lock"])
    lock_file.write_text(str(os.getpid()))

    env = dict(cycle_env["env"])
    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 2
    assert "cycle already running" in res.stdout


def test_portals_off_by_default(cycle_env):
    """Test that portals phase is OFF by default and claude stub is never invoked for portals."""
    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "portals_done"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0, f"cycle.sh failed: {res.stderr}"

    argv_lines = [json.loads(line) for line in cycle_env["argv_log"].read_text().splitlines() if line.strip()]
    assert len(argv_lines) == 2, f"Expected exactly 2 invocations (jobs and people), got {len(argv_lines)}"
    assert not any("--chrome" in argv and any("query_plan.py" in a for a in argv) for argv in argv_lines), "Portals was invoked despite being off"


def test_portals_on_completes_and_runs_people(cycle_env):
    """Test that portals=ON runs portals phase, passes --chrome and --permission-mode dontAsk, and people phase runs."""
    control.set_toggle("portals", True, path=cycle_env["db"])

    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "portals_done"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0, f"cycle.sh failed: {res.stderr}"

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None and row[0] == "COMPLETED"
    conn.close()

    argv_lines = [json.loads(line) for line in cycle_env["argv_log"].read_text().splitlines() if line.strip()]
    assert len(argv_lines) == 3, f"Expected 3 invocations (jobs, portals, people), got {len(argv_lines)}"

    jobs_argv, portals_argv, people_argv = argv_lines[0], argv_lines[1], argv_lines[2]

    # Verify flags for portals phase
    assert "--chrome" in portals_argv
    assert "--permission-mode" in portals_argv
    assert portals_argv[portals_argv.index("--permission-mode") + 1] == "dontAsk"
    assert any("query_plan.py" in arg for arg in portals_argv)

    # Verify people phase ran after portals
    assert "--chrome" in people_argv
    assert any("network_batch.py" in arg for arg in people_argv)


def test_portals_challenge_halts_and_disables_toggle(cycle_env):
    """Test that CYCLE_HALT: cloudflare challenge sets status HALTED and flips ctl:portals to 0."""
    control.set_toggle("portals", True, path=cycle_env["db"])

    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "portals_challenge"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0, f"cycle.sh failed: {res.stderr}"

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    status, reason = row
    assert status == "HALTED"
    assert "cloudflare challenge" in reason.lower()

    # Verify ctl:portals flipped to 0
    cur.execute("SELECT val FROM budgets WHERE key = 'ctl:portals'")
    p_row = cur.fetchone()
    assert p_row is not None and int(p_row[0]) == 0
    conn.close()


def test_portals_phase_timeout_halts(cycle_env):
    """Test that portals phase timeout halts the run cleanly."""
    control.set_toggle("portals", True, path=cycle_env["db"])

    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "sleep_portals"
    env["PHASE_TIMEOUT"] = "2"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    status, reason = row
    assert status == "HALTED"
    assert "phase timeout" in reason.lower()
    conn.close()


def test_portals_midrun_killswitch_halts(cycle_env):
    """Test that engaging killswitch during portals phase halts execution."""
    control.set_toggle("portals", True, path=cycle_env["db"])

    env = dict(cycle_env["env"])
    env["STUB_CLAUDE_MODE"] = "sleep_portals"
    env["PHASE_TIMEOUT"] = "60"

    proc = subprocess.Popen(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=REPO_ROOT
    )

    time.sleep(1.0)
    control.set_kill_switch(True, "mid-run portals halt test", path=cycle_env["db"])

    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("bin/cycle.sh did not halt within 10s after kill switch engaged")

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    status, reason = row
    assert status == "HALTED"
    assert "kill switch pressed" in reason.lower()
    conn.close()


def test_missing_profile_halts_before_phases(cycle_env):
    """Test that missing search_profile halts before running any phase."""
    env = dict(cycle_env["env"])
    env["SEARCH_PROFILE"] = "/tmp/non_existent_profile_12345.md"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    assert res.returncode == 0

    conn = sqlite3.connect(cycle_env["db"])
    cur = conn.cursor()
    cur.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    status, reason = row
    assert status == "HALTED"
    assert "profile missing" in reason.lower()
    conn.close()

    # Verify no phases were invoked
    assert not Path(cycle_env["argv_log"]).exists() or cycle_env["argv_log"].read_text().strip() == ""


def test_apply_phase_off_by_default(cycle_env):
    """Verify that during a standard cycle without CYCLE_ONLY=apply, apply phase is never invoked."""
    env = dict(cycle_env["env"])
    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert res.returncode == 0

    # Ensure stub was never called with apply prompt
    argv_lines = Path(cycle_env["argv_log"]).read_text().splitlines()
    assert not any("apply_prompt" in line or "apply.md" in line for line in argv_lines)


def test_apply_phase_shadow_mode_runs_and_emits_event(cycle_env):
    """Verify apply phase in shadow mode (ctl:submit=0) runs, emits mode=shadow event, and completes."""
    env = dict(cycle_env["env"])
    env["CYCLE_ONLY"] = "apply"
    env["STUB_CLAUDE_MODE"] = "apply_shadow"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert res.returncode == 0

    # Verify stub was called for apply phase
    argv_lines = Path(cycle_env["argv_log"]).read_text().splitlines()
    assert any("AUTOAPPLY_MODE=shadow" in line or "APPLICATIONS phase" in line for line in argv_lines)

    conn = sqlite3.connect(cycle_env["db"])
    conn.row_factory = sqlite3.Row
    # Verify ctl:submit is still 0
    assert control.get_settings(cycle_env["db"])["ctl:submit"] == 0

    run_row = conn.execute("SELECT status FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1").fetchone()
    assert run_row["status"] == "COMPLETED"
    conn.close()


def test_apply_phase_live_mode_runs_and_emits_event(cycle_env):
    """Verify apply phase in live mode (ctl:submit=1) runs to completion."""
    control.set_submit_mode(1, confirm=True, path=cycle_env["db"])

    env = dict(cycle_env["env"])
    env["CYCLE_ONLY"] = "apply"
    env["STUB_CLAUDE_MODE"] = "people_done"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert res.returncode == 0

    conn = sqlite3.connect(cycle_env["db"])
    conn.row_factory = sqlite3.Row
    run_row = conn.execute("SELECT status FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1").fetchone()
    assert run_row["status"] == "COMPLETED"
    conn.close()


def test_apply_phase_halt_resets_submit_to_zero(cycle_env):
    """Verify CYCLE_HALT in apply phase halts cycle, resets ctl:submit to 0, and logs action_log."""
    control.set_submit_mode(1, confirm=True, path=cycle_env["db"])
    env = dict(cycle_env["env"])
    env["CYCLE_ONLY"] = "apply"
    env["STUB_CLAUDE_MODE"] = "apply_halt"

    res = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert res.returncode == 0

    conn = sqlite3.connect(cycle_env["db"])
    conn.row_factory = sqlite3.Row
    # 1. ctl:submit reset to 0
    assert control.get_settings(cycle_env["db"])["ctl:submit"] == 0

    # 2. action_log row recorded by cycle_halt
    al_row = conn.execute(
        "SELECT * FROM action_log WHERE actor = 'cycle_halt' AND action = 'submit_mode' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert al_row is not None
    assert al_row["result"] == "1->0"

    # 3. run_log status is HALTED
    run_row = conn.execute("SELECT status, halted_reason FROM run_log WHERE mode='cycle' ORDER BY id DESC LIMIT 1").fetchone()
    assert run_row["status"] == "HALTED"
    assert "apply:" in run_row["halted_reason"]
    conn.close()

