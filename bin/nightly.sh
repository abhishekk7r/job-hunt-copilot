#!/usr/bin/env bash
# bin/nightly.sh - Overnight orchestration wrapper delegating to bin/cycle.sh
#
# Preserves run locks, kill-switch checks, challenge detection, and delegates
# execution to bin/cycle.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

LOCKFILE="${NIGHTLY_LOCKFILE:-/tmp/jobsearch_nightly.lock}"
DB_PATH="${HARNESS_DB:-$REPO_ROOT/harness.db}"
RUN_ID="nightly_$(date -u +'%Y%m%d_%H%M%S')"
START_TIME="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

# 1. Run Lock (Concurrency guard)
if [[ -f "$LOCKFILE" ]]; then
  OLD_PID="$(cat "$LOCKFILE" 2>/dev/null || echo "")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "ERROR: Another nightly run is currently active (PID $OLD_PID). Exiting." >&2
    exit 2
  fi
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

# Helper: record run log in DB
record_run_start() {
  python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
conn.execute('INSERT INTO run_log (run_id, started_at, mode, status) VALUES (?, ?, ?, ?)', ('$RUN_ID', '$START_TIME', 'nightly', 'RUNNING'))
conn.commit()
conn.close()
" 2>/dev/null || true
}

record_run_end() {
  local status="$1"
  local reason="${2:-}"
  local end_time="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
conn.execute('UPDATE run_log SET status = ?, halted_reason = ?, ended_at = ? WHERE run_id = ?', ('$status', '$reason', '$end_time', '$RUN_ID'))
conn.commit()
conn.close()
" 2>/dev/null || true
}

# Helper: check kill switch
check_killswitch() {
  local step_name="${1:-init}"
  local is_on
  is_on="$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
cur = conn.cursor()
cur.execute('SELECT \"on\", reason FROM kill_switch WHERE id = 1')
row = cur.fetchone()
conn.close()
if row and row[0]:
    print(f'ON:{row[1]}')
else:
    print('OFF')
" 2>/dev/null || echo "OFF")"

  if [[ "$is_on" =~ ^ON:(.*) ]]; then
    local reason="${BASH_REMATCH[1]}"
    echo "HALTED: Kill switch is ENGAGED before step '$step_name'. Reason: $reason" >&2
    record_run_end "HALTED" "Kill switch engaged at $step_name: $reason"
    exit 3
  fi
}

echo "=== Starting Nightly Orchestration [$RUN_ID] ==="
record_run_start

# Step 1: Pre-run Kill Switch Check
check_killswitch "init"

# Check for simulated CAPTCHA/Login Challenge in tests or environment
if [[ "${SIMULATE_CHALLENGE:-}" == "CAPTCHA" || "${SIMULATE_CHALLENGE:-}" == "LOGIN_CHALLENGE" ]]; then
  echo "HALTED: Challenge detected (${SIMULATE_CHALLENGE}). Halting overnight pipeline." >&2
  record_run_end "HALTED" "Simulated ${SIMULATE_CHALLENGE} challenge detected"
  exit 4
fi

# Step 2: Delegate real pipeline execution to bin/cycle.sh
export CYCLE_TRIGGER="${CYCLE_TRIGGER:-dashboard}"
export CYCLE_DRY_RUN="${CYCLE_DRY_RUN:-1}"
export CYCLE_NO_LOG=1
"$REPO_ROOT/bin/cycle.sh"

# Step 3: Completion
record_run_end "COMPLETED" "Nightly pipeline completed successfully"
echo "=== Nightly Orchestration Finished Successfully ==="
exit 0
