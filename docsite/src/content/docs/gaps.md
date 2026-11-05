---
title: Known gaps
description: What is not done or not yet proven.
---

:::note
These are documented operational gaps and risks, not yet resolved in production.
:::

1. **Workspace trust confirmation required.** When running Claude Code for the first time in this workspace, the owner must run `cd ~/Projects/jobsearch && claude` in terminal and accept the trust prompt once; otherwise, the `--allowedTools` allow-list is ignored and Bash execution is denied.
2. **No live end-to-end run has completed in production.** Only dry-run and stub-`claude` automated tests have run. Headless `claude -p --chrome` on your real logged-in Chrome session is untested end-to-end.
3. **Simplify autofill and Chrome interaction are UNVERIFIED until the first shadow run.** The prompt rules and CLI tools are unit-tested and verified, but Simplify extension autofill behavior, custom popup dismissal, and form field interaction inside unattended Chrome remain unverified in production until an operator observes the first shadow run.
4. **Instahyre URL pattern and Naukri selectors are unverified.** Real listing navigation and DOM selectors on Instahyre and Naukri have not been exercised in a live cycle.
5. **Account-protection risk from automation.** While rate limits, random delays (45–90s on LinkedIn/Naukri), and unticked marketing boxes are enforced, automated activity in logged-in sessions still carries site-detection risk.
6. **Claude Code MCP configuration.** Claude Code's project MCP config still points to the old `~/job_harness` server path rather than the repository's native FastMCP server.
7. **Jobs phase allow-list includes Edit tool.** The cycle allow-list for the jobs phase still permits the `Edit` tool; this should be narrowed to read-only tools once the ingest pipeline is fully mature.
8. **PATH resolution under launchd.** Dashboard-spawned cycles inherit a stripped-down launchd PATH environment. `bin/cycle.sh` manually prepends `~/.local/bin` and `~/.bun/bin`, which must exist on the host.
9. **Hidden-tab polling pause.** When the dashboard tab is in the background or minimized, progress polling is paused via `document.visibilityState` to avoid CPU and battery drain; polling resumes instantly when the tab is focused.
