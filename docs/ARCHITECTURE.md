# System Architecture & Technical Specifications

This repository combines the upstream AI Job Search framework with the robust Job Harness infrastructure into a private, unified, and hardened job search automation platform.

```
+-----------------------------------------------------------------------------------+
|                                  DATA SOURCES                                     |
|  - LinkedIn Search (Bun CLI)                                                      |
|  - Freehire.me Search (Bun CLI)                                                   |
|  - Naukri.com (Supervised In-Chrome; Plain HTTP dropped)                          |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                              EVALUATION & RANKING                                 |
|  - Posting Integrity Guard (tools/posting_guard.py - prompt-injection safety)     |
|  - SDE-2 / Senior Backend Scoring (tools/rank_state.py)                           |
|  - Hard CTC Filters (min 22 LPA, target 24-32 LPA)                                |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                           STATE BRIDGE & PERSISTENCE                              |
|  - tools/bridge.py: Ingests seen_jobs.json -> harness.db (idempotent, no downgrade)|
|  - tools/export_tracker.py: Exports harness.db -> job_search_tracker.csv          |
|  - SQLite Database (harness.db with schema.sql and migrations/)                   |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                       APPLICATION & SCREENING (/fill)                             |
|  - Simplify Chrome Extension Autofill first                                       |
|  - Agent audits form inputs against Identity Capsule (config/local.toml)          |
|  - Mismatches overwritten with capsule; missing fields filled from screening_qa   |
|  - Unseen mandatory questions park as BLOCKED_USER; never guesses                  |
|  - Submits on site button ONLY (never clicks Simplify submit)                     |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                    RECRUITER & NETWORKING DISCOVERY (/network)                    |
|  - tools/contacts.py: Deterministic scoring (degree, title, region, Ex- penalty)  |
|  - Curates top 25 high-value contacts (Senior SDEs, EMs, Talent Leads)            |
|  - Copy-ready <=300 character connection notes stored in contacts table           |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                        OUTREACH & APPROVALS (/outreach)                           |
|  - Channels: LinkedIn DM, InMail, Connection Note (<=300 chars), Email            |
|  - Deterministic Python rendering via harness/outreach.py & config/templates/    |
|  - Experience bullets from config/local.toml (bullets[])                          |
|  - Email channel creates Gmail draft only (outreach_emails/); NEVER sends         |
|  - Stored in outreach_queue as PENDING_MOBILE_REVIEW; jobs.status preserved       |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                            COORDINATION & DASHBOARD                               |
|  - FastMCP Server (harness/server.py): global DB call budget, locks, kill switch  |
|  - Live Dashboard (harness/dashboard.py): control plane, 127.0.0.1:8766           |
|  - Cycle Orchestration (bin/cycle.sh, bin/killswitch, tools/digest.py)            |
|  - Cross-Agent Bridge (agent-bridge MCP: Antigravity <-> Claude Code)             |
+-----------------------------------------------------------------------------------+
```

---

## 1. Key Components

### 1.1 FastMCP Server (`harness/server.py`)
Provides tool endpoints for autonomous agents:
- `add_sourced_job`: Ingests posting with salary/stack storage.
- `claim_job_for_application`: Atomically claims a job lock with TTL.
- `update_application_state`: Validates status transitions (`TO_APPLY`, `APPLIED`, `BLOCKED_USER`, `RANKED_OUT`, `HALTED`).
- `get_screening_answers`: Retrieves answer bank and story patterns.
- `draft_outreach_for_mobile_review`: Generates outreach via `harness/outreach.py` without mutating `jobs.status`.
- `process_mobile_approvals`: Transitions review queue items to `APPROVED_TO_SEND`.
- **Global Budget:** Enforces `MAX_CALLS_PER_SESSION = 20` using database table `budgets` keyed by session.
- **Kill Switch:** Checks `kill_switch` table on every tool invocation; halts immediately if engaged.

### 1.2 Form Filling & Audit (`harness/answers.py`)
- Audits autofilled inputs from Chrome extensions (Simplify).
- Replaces incorrect defaults (e.g. 15-day notice period replaced with 30-day notice).
- Detects banned URL shorteners (configured in `banned_links`) and replaces with canonical resume URL.
- Matches screening questions against exact keys, normalized keys, and fuzzy phrasing.
- If an unanswerable mandatory question is encountered, the job is parked as `BLOCKED_USER` and the browser never clicks submit.

### 1.3 Recruiter Discovery & Networking (`tools/contacts.py`)
- Deterministic scoring:
  - Title keyword matches: +40 for Engineering Manager / Director / Talent Lead; +25 for Senior / Staff Engineer.
  - Connection degree: 1st (+30), 2nd (+15), 3rd (+0).
  - Region matching: Bangalore bonus (+15).
  - Ex-employee penalty: -100 (discards past employees at other companies).
- Caps: 20 people-searches per run.
- Generates copy-ready connection notes strictly under 300 characters.

### 1.4 Outreach Engine (`harness/outreach.py`)
- Templates stored in `config/templates/*.txt`.
- Guarantees "I've applied for..." phrasing for applied roles.
- Strict <= 300 character enforcement for LinkedIn connection notes.
- Email drafts created locally in `outreach_emails/` for user inspection; never sent automatically.

### 1.5 Local Live Dashboard (`harness/dashboard.py`)
- Python standard library only (zero external JavaScript or CSS dependencies).
- Connects using SQLite URI mode `mode=ro` (read-only); database writes are rejected at connection level.
- Binds strictly to `127.0.0.1:8765` (localhost only).
- Features 10 operational panels: Pipeline Funnel, Needs You, Approval Queue, Contacts per Job, Answers Bank, Open Items, Last Runs, Kill Switch Banner, Source Breakdown, and Rank Distribution.
