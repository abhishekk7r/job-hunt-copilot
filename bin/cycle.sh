#!/usr/bin/env bash
# bin/cycle.sh - the 6-hourly cycle: jobs phase, then people + tab-prefill phase.
# Started by launchd (every 6h) or the dashboard "Run cycle now". Controlled from the dashboard.
# CYCLE_DRY_RUN=1 skips the two headless Claude calls (used by tests).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
[ -d .venv ] && source .venv/bin/activate
for p in "$HOME/.local/bin" "$HOME/.bun/bin" /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in
    *":$p:"*) ;;
    *) PATH="$PATH:$p" ;;
  esac
done
export PATH

LOCK="${CYCLE_LOCK:-/tmp/jobsearch_cycle.lock}"
DB="${HARNESS_DB:-$ROOT/harness.db}"
export HARNESS_DB="$DB"
RUN_ID="cycle_$(date -u +%Y%m%d_%H%M%S)"
LOGDIR="${CYCLE_LOG_DIR:-$ROOT/reports/cycle_logs}"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/$RUN_ID.log"
PHASE_TIMEOUT="${PHASE_TIMEOUT:-1500}"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }
sql() { python3 - "$@" <<'PY'
import sqlite3,sys,os
db=os.environ.get("HARNESS_DB","harness.db")
c=sqlite3.connect(db); c.execute(sys.argv[1], tuple(sys.argv[2:])); c.commit()
PY
}
end_run() {  # status reason
  if [ -z "${CYCLE_NO_LOG:-}" ]; then
    sql "UPDATE run_log SET status=?, halted_reason=?, ended_at=? WHERE run_id=?" "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RUN_ID" 2>/dev/null
  fi
  log "END $1 $2"
}
set_status() {  # status
  if [ -z "${CYCLE_NO_LOG:-}" ]; then
    sql "UPDATE run_log SET status=? WHERE run_id=?" "$1" "$RUN_ID" 2>/dev/null
  fi
  log "STATUS $1"
}

# lock
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then echo "cycle already running"; exit 2; fi
echo $$ > "$LOCK"; command -v caffeinate >/dev/null && { caffeinate -i -w $$ >/dev/null 2>&1 & }
trap 'rm -f "$LOCK" "$LOGDIR/$RUN_ID.apply_prompt.md" 2>/dev/null' EXIT

# launchd is only a nudge: run only when the DB schedule says a cycle is due (system clock).
if [ "${CYCLE_TRIGGER:-}" = "launchd" ]; then
  python3 -c "import sys;from tools import control;sys.exit(0 if control.claim_due_slot() else 1)" \
    || { log "skipped: not due"; exit 0; }
fi

DECISION="$(python3 -c "import json;from tools import control;print(json.dumps(control.should_run()))")"
RUN=$(echo "$DECISION" | python3 -c "import json,sys;print(json.load(sys.stdin)['run'])")
if [ "$RUN" != "True" ] && [ "${CYCLE_TRIGGER:-}" != "dashboard" ]; then log "skipped: $DECISION"; exit 0; fi
if echo "$DECISION" | grep -q 'kill switch on'; then log "skipped: kill switch on"; exit 0; fi
DO_JOBS=True
DO_PORTALS=$(echo "$DECISION" | python3 -c "import json,sys;print(json.load(sys.stdin).get('portals', False))")
DO_PEOPLE=$(echo "$DECISION" | python3 -c "import json,sys;print(json.load(sys.stdin)['people'])")
# Dashboard "Apply to pending jobs": run only the applications phase
if [ "${CYCLE_ONLY:-}" = "apply" ]; then DO_JOBS=False; DO_PORTALS=False; DO_PEOPLE=False; fi
if [ "${CYCLE_ONLY:-}" = "portals" ]; then DO_JOBS=False; DO_PORTALS=True; DO_PEOPLE=False; fi

CYCLE_NUMBER=$(python3 - <<'PY'
import sqlite3, os
db = os.environ.get("HARNESS_DB", "harness.db")
try:
    c = sqlite3.connect(db)
    cur = c.cursor()
    cur.execute("SELECT count(*) FROM run_log WHERE mode='cycle'")
    print(cur.fetchone()[0])
except Exception:
    print(0)
PY
)

if [ -z "${CYCLE_NO_LOG:-}" ]; then
  sql "INSERT INTO run_log (run_id, started_at, mode, status) VALUES (?,?,?,?)" "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${CYCLE_MODE:-cycle}" "RUNNING"
fi
log "START $RUN_ID jobs=$DO_JOBS portals=$DO_PORTALS people=$DO_PEOPLE trigger=${CYCLE_TRIGGER:-launchd}"

PROFILE_FILE="${SEARCH_PROFILE:-}"
if [ -z "$PROFILE_FILE" ]; then
  if [ -f "config/search_profile.local.md" ]; then
    PROFILE_FILE="config/search_profile.local.md"
  elif [ -f "config/search_profile.example.md" ]; then
    PROFILE_FILE="config/search_profile.example.md"
  else
    PROFILE_FILE="config/search_profile.local.md"
  fi
fi
if [ ! -f "$PROFILE_FILE" ]; then
  log "HALT profile missing"
  end_run HALTED "profile missing"
  exit 0
fi

ks_on() { python3 -c "from tools import control;import sys;sys.exit(0 if control.should_run()['reason']=='kill switch on' else 1)"; }

# run_claude <prompt-file> <outfile> <extra args...>; enforces timeout, narrow tools, spend cap
run_claude() {
  local prompt="$1" out="$2"; shift 2
  local phase
  case "$(basename "$prompt" .md)" in
    *apply*) phase="apply" ;;
    *portals*) phase="portals" ;;
    *people*) phase="people" ;;
    *jobs*) phase="jobs" ;;
    *) phase="$(basename "$prompt" .md)" ;;
  esac
  if [ -n "${CYCLE_DRY_RUN:-}" ]; then echo "DRY RUN: would run claude with $prompt" | tee "$out"; return 0; fi
  local prompt_text
  if [ -f "$prompt" ]; then
    prompt_text="$(printf 'CYCLE_NUMBER=%s\n\n%s' "$CYCLE_NUMBER" "$(cat "$prompt")")"
  else
    prompt_text="CYCLE_NUMBER=$CYCLE_NUMBER"
  fi
  local before_pids
  before_pids=" $(pgrep -P $$ 2>/dev/null | tr '\n' ' ') "
  claude -p "$prompt_text" --verbose --permission-mode dontAsk --max-budget-usd "${PHASE_BUDGET_USD:-3}" "$@" >"$out" 2>&1 &
  local claude_pid=$! waited=0
  while kill -0 "$claude_pid" 2>/dev/null; do
    sleep 1; waited=$((waited+1))
    if ks_on; then
      for p in $(pgrep -P $$ 2>/dev/null); do
        case "$before_pids" in *" $p "*) ;; *) kill "$p" 2>/dev/null ;; esac
      done
      echo "CYCLE_HALT: kill switch pressed" >>"$out"
      break
    fi
    if [ "$waited" -ge "$PHASE_TIMEOUT" ]; then
      for p in $(pgrep -P $$ 2>/dev/null); do
        case "$before_pids" in *" $p "*) ;; *) kill "$p" 2>/dev/null ;; esac
      done
      echo "CYCLE_HALT: phase timeout" >>"$out"
      break
    fi
  done
  wait "$claude_pid" 2>/dev/null; return 0
}
halted() { grep -h '^CYCLE_HALT:' "$1" 2>/dev/null | head -1; }

if [ "$DO_JOBS" = "True" ]; then
  log "--- jobs phase"
  set_status "RUNNING: jobs"
  run_claude docs/cycle_prompts/jobs.md "$LOGDIR/$RUN_ID.jobs.out" \
    --allowedTools "Read" "Grep" "Glob" "Write" "Edit" "Skill" "WebSearch" \
      "Bash(bun run .agents/skills/linkedin-search/cli/src/cli.ts:*)" \
      "Bash(bun run .agents/skills/freehire-search/cli/src/cli.ts:*)" \
      "Bash(bun run .agents/skills/wellfound-search/cli/src/cli.ts:*)" \
      "Bash(python3 tools/query_plan.py:*)" \
      "Bash(python3 tools/posting_guard.py:*)" "Bash(python3 tools/fetch_postings.py:*)" \
      "Bash(python3 tools/rank_state.py:*)" "Bash(python3 tools/scrape_state.py:*)" \
      "Bash(python3 tools/bridge.py:*)" "Bash(python3 tools/export_tracker.py:*)" "Bash(python3 tools/digest.py:*)" \
      "Bash(python3 tools/decide.py:*)"
  H="$(halted "$LOGDIR/$RUN_ID.jobs.out")"
  if [ -n "$H" ]; then
    end_run HALTED "jobs: $H"; exit 0
  fi
  python3 tools/bridge.py >>"$LOG" 2>&1 || true
fi

if ks_on; then end_run HALTED "kill switch pressed"; exit 0; fi

if [ "$DO_PORTALS" = "True" ]; then
  log "--- portals phase"
  set_status "RUNNING: portals"
  run_claude docs/cycle_prompts/portals.md "$LOGDIR/$RUN_ID.portals.out" --chrome \
    --allowedTools "Read" "Grep" "Glob" "Write" "mcp__claude-in-chrome__*" \
      "Bash(python3 tools/query_plan.py:*)" "Bash(python3 tools/scrape_state.py:*)" \
      "Bash(python3 tools/posting_guard.py:*)" "Bash(python3 tools/rank_state.py:*)" \
      "Bash(python3 tools/bridge.py:*)" "Bash(python3 tools/decide.py:*)"
  H="$(halted "$LOGDIR/$RUN_ID.portals.out")"
  if [ -n "$H" ]; then
    # A challenge or halt turns the portals phase OFF until the user re-enables it on the dashboard.
    python3 -c "from tools import control;control.set_toggle('portals', False)"
    end_run HALTED "portals: $H (portals phase switched OFF; re-enable on dashboard)"; exit 0
  fi
  python3 tools/bridge.py --min-verdict Medium >>"$LOG" 2>&1 || true
fi

if ks_on; then end_run HALTED "kill switch pressed"; exit 0; fi

# Applications phase: runs when CYCLE_ONLY is apply
if [ "${CYCLE_ONLY:-}" = "apply" ]; then
  SUBMIT_VAL=$(python3 -c "from tools import control;print(control.get_settings().get('ctl:submit', 0))")
  if [ "$SUBMIT_VAL" = "1" ]; then
    APPLY_MODE="live"
  else
    APPLY_MODE="shadow"
  fi

  log "--- apply phase (mode=$APPLY_MODE)"
  set_status "RUNNING: apply ($APPLY_MODE)"

  mkdir -p "reports/cycle_work/$CYCLE_NUMBER"

  TMP_APPLY_PROMPT="$LOGDIR/$RUN_ID.apply_prompt.md"
  cat <<EOF > "$TMP_APPLY_PROMPT"
RUN_ID=$RUN_ID
CYCLE_NUMBER=$CYCLE_NUMBER
AUTOAPPLY_MODE=$APPLY_MODE
DAILY_APPLICATION_CAP=25
RUN_APPLICATION_CAP=8

EOF
  cat docs/cycle_prompts/apply.md >> "$TMP_APPLY_PROMPT"

  run_claude "$TMP_APPLY_PROMPT" "$LOGDIR/$RUN_ID.apply.out" --chrome \
    --allowedTools "Read" "Write" "Grep" "Glob" "mcp__claude-in-chrome__*" \
      "mcp__gmail-multi__gmail_search" \
      "Bash(python3 tools/decide.py:*)" "Bash(python3 tools/answers_bank.py:*)"

  rm -f "$TMP_APPLY_PROMPT"

  H="$(halted "$LOGDIR/$RUN_ID.apply.out")"
  if [ -n "$H" ]; then
    # A challenge, warning, or halt turns submit back to 0 and records action_log
    python3 -c "from tools import control;control.set_submit_mode(0, actor='cycle_halt')"
    end_run HALTED "apply: $H (submit reset to 0; re-enable on dashboard)"; exit 0
  fi
fi

if ks_on; then end_run HALTED "kill switch pressed"; exit 0; fi

if [ "$DO_PEOPLE" = "True" ]; then
  log "--- people + tabs phase"
  set_status "RUNNING: people"
  run_claude docs/cycle_prompts/people.md "$LOGDIR/$RUN_ID.people.out" --chrome \
    --allowedTools "Read" "Grep" "Glob" "mcp__claude-in-chrome__*" \
      "mcp__linkedin__search_people" "mcp__linkedin__get_company_employees" \
      "mcp__linkedin__get_person_profile" "mcp__linkedin__get_job_details" \
      "mcp__linkedin__search_jobs" "mcp__linkedin__get_company_profile" \
      "Bash(python3 tools/network_batch.py:*)" "Bash(python3 tools/save_candidates.py:*)" "Bash(python3 tools/reachout_data.py:*)" "Bash(sqlite3 -readonly harness.db:*)"
  H="$(halted "$LOGDIR/$RUN_ID.people.out")"
  if [ -n "$H" ]; then
    # A challenge turns the people phase OFF until the user re-enables it on the dashboard.
    python3 -c "from tools import control;control.set_toggle('people', False)"
    end_run HALTED "people: $H (people phase switched OFF; re-enable on dashboard)"; exit 0
  fi
fi

set_status "RUNNING: digest"
python3 tools/digest.py >>"$LOG" 2>&1 || true
end_run COMPLETED ""
