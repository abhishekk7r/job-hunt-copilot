"""DB-backed scheduler: system-clock due time, one catch-up after sleep, manual runs don't move it."""
import sqlite3

from tools import control

H = 3600


def _db(temp_db):
    return str(temp_db)


def test_first_call_sets_next_due_and_does_not_run(temp_db):
    p = _db(temp_db)
    assert control.claim_due_slot(now=1000, path=p) is False
    assert control.get_schedule(now=1000, path=p)["next_due"] == 1000 + 6 * H


def test_not_due_then_due(temp_db):
    p = _db(temp_db)
    control.claim_due_slot(now=0, path=p)
    assert control.claim_due_slot(now=6 * H - 1, path=p) is False
    assert control.claim_due_slot(now=6 * H, path=p) is True
    assert control.get_schedule(now=6 * H, path=p)["next_due"] == 12 * H


def test_long_sleep_gives_exactly_one_catch_up_run(temp_db):
    p = _db(temp_db)
    control.claim_due_slot(now=0, path=p)
    wake = 6 * H * 5 + 600  # asleep for 30 h, awake 10 min
    assert control.claim_due_slot(now=wake, path=p) is True
    assert control.claim_due_slot(now=wake + 60, path=p) is False  # not one per missed interval
    assert control.get_schedule(now=wake, path=p)["next_due"] == wake + 6 * H


def test_tick_spawns_when_due_and_respects_pause_and_kill(temp_db, monkeypatch):
    p = _db(temp_db)
    monkeypatch.setattr(control, "cycle_running", lambda *a, **k: False)
    spawned = []
    control.claim_due_slot(now=0, path=p)
    assert control.scheduler_tick(now=10, path=p, spawn=lambda: spawned.append(1) or True) == "not due"
    control.set_toggle("schedule", False, p)
    assert control.scheduler_tick(now=7 * H, path=p, spawn=lambda: spawned.append(1) or True) == "schedule paused"
    control.set_toggle("schedule", True, p)
    control.set_kill_switch(True, "t", p)
    assert control.scheduler_tick(now=7 * H, path=p, spawn=lambda: spawned.append(1) or True) == "kill switch on"
    control.set_kill_switch(False, "", p)
    assert control.scheduler_tick(now=7 * H, path=p, spawn=lambda: spawned.append(1) or True) == "started"
    assert spawned == [1]


def test_manual_run_does_not_move_schedule(temp_db, monkeypatch):
    p = _db(temp_db)
    control.claim_due_slot(now=0, path=p)
    before = control.get_schedule(now=1, path=p)["next_due"]
    monkeypatch.setattr(control, "_spawn_cycle", lambda trigger: True)
    assert control.request_run_now(p) is True
    assert control.get_schedule(now=2, path=p)["next_due"] == before


def test_reap_marks_orphaned_running_rows(temp_db, monkeypatch):
    p = _db(temp_db)
    monkeypatch.setattr(control, "cycle_running", lambda *a, **k: False)
    c = sqlite3.connect(p)
    c.execute("INSERT INTO run_log (run_id, started_at, mode, status) VALUES ('x','2026-01-01T00:00:00Z','cycle','RUNNING')")
    c.commit(); c.close()
    assert control.reap_stale_runs(p) == 1
    c = sqlite3.connect(p)
    assert c.execute("SELECT status FROM run_log WHERE run_id='x'").fetchone()[0] == "HALTED"
