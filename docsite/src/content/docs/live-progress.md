---
title: Live progress
description: How the dashboard provides real-time visibility into the running cycle.
---

Cycles run unattended in the background. The dashboard displays the real-time status of the cycle in the header directly from `/api/state`.

## Status States

| State | Description |
|---|---|
| **IDLE** | No cycle is currently executing. The header displays the last run's result and timestamp. |
| **RUNNING: &lt;phase&gt;** | An active cycle is currently executing the named phase (`jobs`, `portals`, `apply`, or `people`). |
| **COMPLETED** | The last cycle completed all configured phases successfully. |
| **HALTED: &lt;reason&gt;** | The cycle halted early due to a rate limit, security challenge, timeout, or kill switch engagement. |

## How It Works

1. **Cycle Script Execution (`bin/cycle.sh`):** As each phase starts, the script updates the status to `RUNNING: <phase>`.
2. **State Endpoint (`/api/state`):** The dashboard polls `/api/state` every 2 seconds while a cycle is running, and displays the current phase in the header status line.
3. **Completion & Halts:** When all phases finish, the status transitions to `COMPLETED`. If any phase encounters a challenge or error, `bin/cycle.sh` captures the `CYCLE_HALT:` reason and records `HALTED: <reason>`.
4. **Efficiency:** Polling pauses when the dashboard browser tab is in the background or minimized, saving CPU and battery.
