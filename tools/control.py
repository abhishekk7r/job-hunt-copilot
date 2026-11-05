"""Control plane shared by the dashboard and bin/cycle.sh.

Settings live in the existing `budgets` key/val table (no migration):
  ctl:schedule   1/0   master on/off for the 6-hourly cycle (jobs always on with schedule)
  ctl:portals    1/0   portals (naukri/instahyre) phase on/off
  ctl:people     1/0   people + tab-prefill phase on/off
  ctl:run_now    1/0   one-shot request from the dashboard
  ctl:interval_min     minutes between scheduled cycles (default 360)
  ctl:next_due         epoch seconds of the next scheduled cycle (system clock, survives sleep)
  ctl:submit     1/0   live application submission toggle (default 0: shadow only)
The dashboard token lives in a git-ignored 0600 file.
"""

import os
import secrets
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = REPO_ROOT / "config" / "dashboard_token"
DEFAULTS = {"ctl:schedule": 1, "ctl:portals": 0, "ctl:people": 1, "ctl:run_now": 0, "ctl:interval_min": 360, "ctl:submit": 0}
NEXT_DUE_KEY = "ctl:next_due"  # epoch seconds (system clock) of the next scheduled cycle
SUBMIT_KEY = "ctl:submit"
TOGGLES = {"schedule": "ctl:schedule", "portals": "ctl:portals", "people": "ctl:people"}


def db_path() -> str:
    return os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))


def _rw(path: Optional[str] = None) -> sqlite3.Connection:
    c = sqlite3.connect(path or db_path(), timeout=10.0)
    c.row_factory = sqlite3.Row
    return c


def get_settings(path: Optional[str] = None) -> Dict[str, int]:
    conn = _rw(path)
    try:
        out = dict(DEFAULTS)
        for r in conn.execute("SELECT key, val FROM budgets WHERE key LIKE 'ctl:%'"):
            out[r["key"]] = int(r["val"])
        return out
    finally:
        conn.close()


def set_toggle(name: str, on: bool, path: Optional[str] = None) -> Dict[str, int]:
    if name not in TOGGLES:
        raise ValueError(f"unknown toggle {name}")
    conn = _rw(path)
    try:
        conn.execute("INSERT INTO budgets (key, val) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET val = excluded.val",
                     (TOGGLES[name], 1 if on else 0))
        conn.commit()
    finally:
        conn.close()
    return get_settings(path)


def set_submit_mode(
    mode: Any,
    confirm: bool = False,
    path: Optional[str] = None,
    actor: str = "user",
) -> Dict[str, int]:
    """Set the 1-bit submit switch: 0 (Off / Shadow only) or 1 (Live submit).

    Switching to Live (1) requires explicit confirmation (confirm=True).
    Turning Off (0) needs no confirmation.
    Audits transitions in action_log (action='submit_mode', detail='from->to').
    """
    if type(mode) is bool:
        mode = 1 if mode else 0
    if type(mode) is not int or mode not in (0, 1):
        raise ValueError(f"invalid submit mode: {mode!r} (must be int 0 or 1)")

    conn = _rw(path)
    try:
        row = conn.execute("SELECT val FROM budgets WHERE key = ?", (SUBMIT_KEY,)).fetchone()
        cur_mode = int(row["val"]) if row else 0

        if cur_mode == mode:
            return get_settings(path)

        if mode == 1 and not confirm:
            raise ValueError("switching to Live mode requires explicit confirmation")

        now_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO budgets (key, val) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET val = excluded.val",
            (SUBMIT_KEY, mode),
        )
        conn.execute(
            "INSERT INTO action_log (run_id, ts, actor, action, target, result, detail) "
            "VALUES ('', ?, ?, 'submit_mode', 'submit', ?, ?)",
            (now_ts, actor, f"{cur_mode}->{mode}", f"mode changed from {cur_mode} to {mode}"),
        )
        conn.commit()
    finally:
        conn.close()

    return get_settings(path)


set_submit = set_submit_mode


def set_kill_switch(on: bool, reason: str = "", path: Optional[str] = None) -> None:
    conn = _rw(path)
    try:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute('INSERT OR IGNORE INTO kill_switch (id, "on", reason, ts) VALUES (1, 0, "", "")')
        conn.execute('UPDATE kill_switch SET "on" = ?, reason = ?, ts = ? WHERE id = 1',
                     (1 if on else 0, reason if on else "", ts))
        conn.commit()
    finally:
        conn.close()


def _spawn_cycle(trigger: str) -> bool:
    if cycle_running():
        return False
    env = dict(os.environ, CYCLE_TRIGGER=trigger)
    subprocess.Popen(["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")], env=env, cwd=str(REPO_ROOT),
                     stdout=open("/tmp/jobsearch_cycle.log", "a"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    return True


def request_run_now(path: Optional[str] = None) -> bool:
    """Manual run from the dashboard. Does NOT move the schedule (next_due is untouched)."""
    return _spawn_cycle("dashboard")


def request_apply_now(start_shadow: bool = False, path: Optional[str] = None) -> Dict[str, Any]:
    """Dashboard "Apply to pending jobs": run only the apply phase.

    Mode is Live only when ctl:submit is 1, otherwise Shadow (fill, screenshot, no submit).
    """
    mode = "live" if int(get_settings(path).get(SUBMIT_KEY, 0)) == 1 else "shadow"
    if cycle_running():
        return {"started": False, "mode": mode, "reason": "a cycle is already running"}
    env = dict(os.environ, CYCLE_TRIGGER="dashboard", CYCLE_ONLY="apply")
    subprocess.Popen(["/bin/bash", str(REPO_ROOT / "bin" / "cycle.sh")], env=env, cwd=str(REPO_ROOT),
                     stdout=open("/tmp/jobsearch_cycle.log", "a"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    return {"started": True, "mode": mode}


def get_schedule(now: Optional[float] = None, path: Optional[str] = None) -> Dict[str, Any]:
    s = get_settings(path)
    conn = _rw(path)
    try:
        row = conn.execute("SELECT val FROM budgets WHERE key = ?", (NEXT_DUE_KEY,)).fetchone()
    finally:
        conn.close()
    return {"interval_min": int(s["ctl:interval_min"]), "next_due": int(row["val"]) if row else None,
            "enabled": bool(s["ctl:schedule"]), "now": int(now if now is not None else time.time())}


def claim_due_slot(now: Optional[float] = None, path: Optional[str] = None) -> bool:
    """Atomically decide whether a scheduled cycle is due by the SYSTEM clock.

    True (and next_due moves to now + interval) only if now >= next_due. A long sleep produces
    exactly one catch-up run, not one per missed interval. First call just sets next_due.
    """
    now = int(now if now is not None else time.time())
    interval = int(get_settings(path)["ctl:interval_min"]) * 60
    conn = _rw(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT val FROM budgets WHERE key = ?", (NEXT_DUE_KEY,)).fetchone()
        due = int(row["val"]) if row else None
        if due is not None and now >= due:
            conn.execute("UPDATE budgets SET val = ? WHERE key = ?", (now + interval, NEXT_DUE_KEY))
            conn.commit()
            return True
        if due is None:
            conn.execute("INSERT INTO budgets (key, val) VALUES (?, ?)", (NEXT_DUE_KEY, now + interval))
        conn.commit()
        return False
    finally:
        conn.close()


def reap_stale_runs(path: Optional[str] = None) -> int:
    """Mark RUNNING cycle rows HALTED if no cycle process is alive (crash, reboot, power loss)."""
    if cycle_running():
        return 0
    conn = _rw(path)
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = conn.execute(
            "UPDATE run_log SET status='HALTED', halted_reason='interrupted: process ended without finishing', ended_at=? "
            "WHERE status='RUNNING' AND mode='cycle'", (ts,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def scheduler_tick(now: Optional[float] = None, path: Optional[str] = None, spawn=None) -> str:
    """One scheduler step. Called every ~30 s by the dashboard process. Returns what it did."""
    spawn = spawn or (lambda: _spawn_cycle("schedule"))
    reap_stale_runs(path)
    d = should_run(path)
    if not d["run"]:
        return d["reason"] or "paused"
    if cycle_running():
        return "cycle running"
    if claim_due_slot(now, path):
        return "started" if spawn() else "spawn refused"
    return "not due"


def cycle_running(lockfile: str = "/tmp/jobsearch_cycle.lock") -> bool:
    try:
        pid = int(Path(lockfile).read_text().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def last_runs(limit: int = 6, path: Optional[str] = None):
    conn = _rw(path)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT run_id, started_at, ended_at, mode, status, halted_reason FROM run_log "
            "WHERE mode = 'cycle' ORDER BY id DESC LIMIT ?", (limit,))]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def get_token() -> str:
    """Create (once) and return the dashboard token. File is 0600 and git-ignored."""
    if not TOKEN_FILE.exists():
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    return TOKEN_FILE.read_text().strip()


def check_token(supplied: Optional[str]) -> bool:
    return bool(supplied) and secrets.compare_digest(supplied, get_token())


def should_run(path: Optional[str] = None) -> Dict[str, Any]:
    """Used by cycle.sh: decide what phases may run right now."""
    s = get_settings(path)
    conn = _rw(path)
    try:
        ks = conn.execute('SELECT "on", reason FROM kill_switch WHERE id = 1').fetchone()
    except sqlite3.Error:
        ks = None
    finally:
        conn.close()
    killed = bool(ks and ks["on"])
    return {
        "run": bool(s["ctl:schedule"]) and not killed,
        "portals": bool(s.get("ctl:portals", 0)),
        "people": bool(s["ctl:people"]),
        "submit": int(s.get(SUBMIT_KEY, 0)),
        "reason": "kill switch on" if killed else ("schedule paused" if not s["ctl:schedule"] else ""),
    }
