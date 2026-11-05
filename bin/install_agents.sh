#!/usr/bin/env bash
# bin/install_agents.sh [install|uninstall|status]
# Installs two launchd agents: the dashboard (always on, http://127.0.0.1:8766) and the 6-hourly cycle.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents"
UID_=$(id -u)
LABELS=(com.example.jobhuntcopilot.dashboard com.example.jobhuntcopilot.cycle)
case "${1:-status}" in
  install)
    mkdir -p "$DEST" "$ROOT/reports"
    for l in "${LABELS[@]}"; do
      sed -e "s|__REPO_ROOT__|$ROOT|g" -e "s|__HOME__|$HOME|g" "$ROOT/launchd/$l.plist" > "$DEST/$l.plist"
      launchctl bootout "gui/$UID_/$l" 2>/dev/null || true
      launchctl bootstrap "gui/$UID_" "$DEST/$l.plist"
      echo "installed $l"
    done ;;
  uninstall)
    for l in "${LABELS[@]}"; do
      launchctl bootout "gui/$UID_/$l" 2>/dev/null || true; rm -f "$DEST/$l.plist"; echo "removed $l"
    done ;;
  *) for l in "${LABELS[@]}"; do launchctl print "gui/$UID_/$l" >/dev/null 2>&1 && echo "$l: loaded" || echo "$l: not loaded"; done ;;
esac
