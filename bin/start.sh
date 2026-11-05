#!/usr/bin/env bash
# One-command start: privacy/killswitch checks, dashboard, then Claude Code.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
PORT="${HARNESS_DASH_PORT:-8766}"
export HARNESS_DASH_PORT="$PORT"

[ -d .venv ] && source .venv/bin/activate

echo "== 1/3 Kill switch =="
KS="$(python3 bin/killswitch status 2>&1)"; echo "$KS"
if echo "$KS" | grep -qi 'on' && ! echo "$KS" | grep -qi 'off'; then
  echo "Kill switch is ON. Run 'python3 bin/killswitch off' first if intended."; exit 1
fi

if [ "${RUN_TESTS:-0}" = "1" ]; then
  echo "== Running tests (RUN_TESTS=1) =="
  pytest tests/ -q -x 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "STOP: tests failing. Fix before running."; exit 1; }
fi

echo "== 2/3 Dashboard on http://127.0.0.1:$PORT =="
if lsof -i ":$PORT" >/dev/null 2>&1; then
  echo "Dashboard is already running on port $PORT"
else
  nohup python3 harness/dashboard.py >/tmp/jobsearch_dashboard.log 2>&1 &
  sleep 1
fi
open "http://127.0.0.1:$PORT" 2>/dev/null || true

echo "== 3/3 Claude Code =="
echo "Say:  /network   (or: run the networking batch, 5 people first)"
echo "Make sure Chrome is open, logged in to LinkedIn, with the Claude extension connected."
[ -n "${NO_CLAUDE:-}" ] && { echo "(NO_CLAUDE set, not launching)"; exit 0; }
exec claude
