#!/usr/bin/env bash
# bin/supervised.sh - Morning Supervised Execution Guide
#
# Prints instructions and status for interactive, in-Chrome workflows.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

TODAY="$(date +'%Y-%m-%d')"
DIGEST_FILE="reports/digest-${TODAY}.md"

echo "=========================================================="
echo "         JOB SEARCH — SUPERVISED MORNING WORKFLOW         "
echo "=========================================================="
echo ""
echo "1. LIVE DASHBOARD:"
echo "   URL: http://127.0.0.1:8766 (managed by launchd or bin/start.sh)"
echo "   Run manually if stopped: python3 harness/dashboard.py"
echo ""
echo "2. CHECK NIGHTLY DIGEST:"
if [[ -f "$DIGEST_FILE" ]]; then
  echo "   Report ready at: $DIGEST_FILE"
else
  echo "   Generate latest report: python3 tools/digest.py"
fi
echo ""
echo "3. SUPERVISED ACTIONS REQUIRING CHROME:"
echo "   a) Unblock Applications:"
echo "      Review any jobs marked 'BLOCKED_USER' on the dashboard."
echo "   b) Auto-Fill Applications (/fill):"
echo "      Keep your personal logged-in Chrome open."
echo "      Claude audits Simplify autofill and submits on target job sites."
echo "      Cap: 20 applications/run."
echo "   c) Technical Networking & Recruiter Discovery (/network & /find-contacts):"
echo "      Finds up to 25 peers/EMs/recruiters per day (no VP/Director), warm companies first."
echo "      Builds the batch:  python3 tools/network_batch.py build"
echo "      Claude prefills one Chrome tab per person (<=300 char note); YOU press Send or close."
echo "      Record results:    python3 tools/network_batch.py mark <id> SENT|SKIPPED"
echo "      Caps: 25 prefilled/day, 20 people-searches/run."
echo "   d) Review & Approve Outreach (/outreach):"
echo "      Review queued messages on dashboard or mobile app."
echo "      Approved messages can be sent manually or draft-created."
echo ""
echo "4. KILL SWITCH:"
echo "   To halt everything instantly:"
echo "     bin/killswitch on \"Reason for pause\""
echo "   To resume:"
echo "     bin/killswitch off"
echo "=========================================================="
