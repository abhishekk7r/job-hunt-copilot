---
title: Daily use
description: How to use the dashboard and what to do when something halts.
---

## Daily routine
1. Open `http://127.0.0.1:8766` (always on through launchd).
2. **Today**: review the prefilled tabs in Chrome, press Send yourself on the ones you want, then click **Sent** or **Skip** on the dashboard. Handle the **Needs you** items.
3. **Pipeline**: jobs by status. **Library**: contacts, drafts, queued messages, answers, run history.
4. Run on demand with **Run cycle now**, or let launchd run it every 6 hours.
5. **Schedule** menu: schedule, jobs, people toggles. The **Kill switch** stops everything.

## When a cycle halts
A CAPTCHA or login challenge halts the cycle and turns **People** off. Open LinkedIn yourself, resolve it, then re-enable People on the dashboard.

## Commands

| Task | Command |
|---|---|
| Run all tests | `make test` |
| Kill switch | `bin/killswitch on \| off \| status` |
| Watch the latest run | `tail -f reports/cycle_logs/$(ls -t reports/cycle_logs \| head -1)` |
| These docs | `cd docsite && npm run dev` |

## Where things are
`bin/` scripts · `tools/` Python logic · `harness/` dashboard and MCP server · `docs/cycle_prompts/` the two prompts · `.claude/commands/` slash commands · `config/` (`example.toml` tracked; `local.toml` and `dashboard_token` ignored) · `reports/`, `backups/`, `reviews/` outputs.
