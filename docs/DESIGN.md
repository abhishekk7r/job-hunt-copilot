# High-level design

Diagrams are Mermaid; GitHub (private repo), VS Code and Obsidian render them.

## 1. System overview

```mermaid
flowchart LR
    You([You])
    subgraph Mac["Your Mac (everything local)"]
        DASH["Dashboard<br/>127.0.0.1:8766<br/>single point of contact"]
        LD["launchd<br/>every 6 hours"]
        CYC["bin/cycle.sh<br/>orchestrator"]
        CL["Headless Claude<br/>claude -p"]
        DB[("harness.db<br/>SQLite, WAL")]
        TOOLS["tools/*.py<br/>scoring, batch, bridge, digest"]
        CH["Your Chrome<br/>logged in, Claude in Chrome"]
    end
    LI["LinkedIn<br/>profiles and Connect"]
    PORTALS["Logged-out job sources<br/>linkedin guest pages, freehire"]

    You -->|"toggles, kill switch,<br/>Sent / Skipped"| DASH
    DASH <-->|"read, controlled writes"| DB
    DASH -->|"Run cycle now"| CYC
    LD --> CYC
    CYC -->|"guards: private repo,<br/>kill switch, lock"| DB
    CYC --> CL
    CL --> TOOLS
    TOOLS <--> DB
    CL -->|"jobs phase, no login"| PORTALS
    CL -->|"people phase"| CH
    CH --> LI
    CH -.->|"prefilled tabs, never Send"| You
    You ==>|"presses Send"| LI
```

## 2. The 6-hour cycle

```mermaid
sequenceDiagram
    autonumber
    participant L as launchd or Dashboard
    participant C as cycle.sh
    participant D as harness.db
    participant J as Claude: jobs phase
    participant PT as Claude: portals phase
    participant AP as Claude: apply phase
    participant P as Claude: people phase
    participant B as Chrome / LinkedIn / Simplify
    participant U as You

    L->>C: start (every 6h or Run now)
    C->>C: repo private? lock free?
    C->>D: should_run(): schedule on? kill switch off?
    alt paused or killed
        C-->>L: exit, nothing done
    end
    C->>D: run_log RUNNING: jobs
    opt Schedule ON
        C->>J: scrape logged-out sources, rank
        J->>D: bridge, tracker export, digest
        J-->>C: JOBS_DONE or CYCLE_HALT
    end
    opt Portals toggle ON (default OFF)
        C->>D: run_log RUNNING: portals
        C->>PT: read-only Chrome (Naukri, Instahyre)
        PT->>D: bridge eligible jobs
        PT-->>C: PORTALS_DONE or CYCLE_HALT (disables toggle)
    end
    opt Schedule ON
        C->>D: run_log RUNNING: apply
        C->>AP: next-jobs (caps: 25/day, 8/run)
        AP->>B: navigate JD in Chrome, Simplify autofill first
        AP->>D: write JSON to reports/cycle_work/, classify via decide.py --input
        AP->>D: log decision_log, insert pending decisions on ESCALATE
        alt Shadow mode (ctl:submit == 0)
            AP->>B: stop before submit, take screenshot if supported
            AP->>D: mark-job WOULD_SUBMIT --reason shadow_filled
        else Live mode (ctl:submit == 1)
            AP->>D: evaluate decide.py gate (fails unless ctl:submit == 1)
            AP->>D: on gate PASS, writes gate_pass to action_log
            AP->>B: click page native Submit button
            AP->>D: mark-job APPLIED --reason submitted (verifies gate_pass)
        end
        AP-->>C: APPLY_DONE or CYCLE_HALT (resets ctl:submit to 0)
    end
    opt People toggle ON
        C->>D: run_log RUNNING: people
        C->>P: start with caps (12 page loads, 7 tabs, 25/day)
        P->>D: reachout_data: who is already contacted
        P->>B: search people at target companies
        P->>D: save_candidates (score, reject executives, dedupe)
        P->>D: network_batch build (live "I've applied" check)
        loop each person in batch
            P->>B: open profile, Connect, Add a note, type note
            P->>D: mark PREFILLED
        end
        P-->>C: PEOPLE_DONE or CYCLE_HALT
    end
    alt CYCLE_HALT (CAPTCHA, challenge, rate limit, timeout)
        C->>D: run_log HALTED, disable offending phase
    else
        C->>D: run_log COMPLETED
    end
    U->>B: review tabs, press Send or close
    U->>D: Dashboard: I sent it / Skipped / Review decisions
```

## 3. Data model

```mermaid
erDiagram
    jobs ||--o{ contacts : "job_id"
    jobs ||--o{ outreach_queue : "job_id"
    jobs ||--o{ outreach_email_drafts : "company"
    jobs {
        int id PK
        text company
        text role
        text job_url UK
        text status "TO_APPLY, APPLIED, BLOCKED_USER, RANKED_OUT"
        text blocker_note
        text recruiter_name
        real rank_score
        int salary_lpa
        text source
    }
    contacts {
        int id PK
        int job_id FK
        text name
        text title
        text profile_url UK
        text current_company
        real score
        text kind
        text status "PROPOSED, PREFILLED, SENT, SKIPPED, JOB_CONTACT"
        text note_text "max 300 chars"
    }
    outreach_queue {
        int id PK
        int job_id FK
        text channel
        text rendered_message
        text approval_status
    }
    outreach_email_drafts {
        int id PK
        text company
        text contact_name
        text to_email
        text subject
        text body
        text status
    }
    screening_qa {
        text question_key PK
        text answer
    }
    app_story_answers {
        int id PK
        text application
        text question
        text answer
        text status "DRAFT_NOT_SUBMITTED, SUBMITTED"
    }
    open_items {
        int id PK
        text area
        text item
        text status
    }
    gmail_drafts_snapshot {
        int id PK
        text account
        text draft_message_id UK
        text subject
    }
    run_log {
        int id PK
        text run_id
        text mode "cycle"
        text status "RUNNING, COMPLETED, HALTED"
        text halted_reason
    }
    action_log {
        int id PK
        text ts
        text action "network_prefill"
        text target
        text result
    }
    kill_switch {
        int id PK
        int on
        text reason
    }
    budgets {
        text key PK "ctl:schedule, ctl:portals, ctl:people, ctl:submit"
        int val
    }
    agent_locks {
        text resource_id PK
        text locked_by
        text expires_at
    }
```

## 4. Contact lifecycle

```mermaid
stateDiagram-v2
    [*] --> PROPOSED: save_candidates scores and stores
    PROPOSED --> SKIPPED_TOO_SENIOR: VP / Director / CTO / Head of
    PROPOSED --> PREFILLED: batch build, note typed in tab, Send NOT pressed
    PREFILLED --> SENT: you press Send, then click "I sent it"
    PREFILLED --> SKIPPED: you close the tab, click "Skipped"
    PROPOSED --> SKIPPED: no Connect button on profile
    SENT --> [*]: never downgraded, never re-contacted
    SKIPPED --> [*]
    SKIPPED_TOO_SENIOR --> [*]
    note right of PREFILLED
        Cap: 25 per day.
        Counted in action_log.
    end note
```

## 5. Safety and control layers

```mermaid
flowchart TD
    START([cycle starts]) --> G1{"Repo still<br/>PRIVATE?"}
    G1 -- no --> X1[abort]
    G1 -- yes --> G2{"Another cycle<br/>running? lock"}
    G2 -- yes --> X2[exit]
    G2 -- no --> G3{"Kill switch<br/>ON?"}
    G3 -- yes --> X3[exit]
    G3 -- no --> G4{"Schedule<br/>ON?"}
    G4 -- no --> X4[exit]
    G4 -- yes --> RUN[run phases]
    RUN --> C1["Per-phase caps:<br/>$3 spend, 25 min timeout"]
    RUN --> C2["Tools allow-list only<br/>dontAsk permission mode"]
    RUN --> C3["Kill switch re-checked<br/>every 5 seconds"]
    RUN --> C4["No Send click, ever<br/>you decide each message"]
    RUN --> H{"CAPTCHA, challenge,<br/>rate limit seen?"}
    H -- yes --> HALT["HALTED: reason logged,<br/>People toggle switched OFF,<br/>you re-enable on dashboard"]
    H -- no --> OK[COMPLETED]
```

## 6. Dashboard control surface: "Control Room" (http://127.0.0.1:8766)

The web dashboard is the single point of contact for the entire system: monitoring the 6-hour cycle, toggling automation phases, and deciding outbound contact messages.

```mermaid
flowchart LR
    subgraph Client["Control Room Web Client (harness/web/)"]
        CMD["Command Bar (56px sticky)<br/>Cycle Ring · Schedule Menu · Kill Switch (600ms)"]
        VIEWS["Three Views (1, 2, 3)<br/>#today · #pipeline · #library"]
        TODAY["1. Today View<br/>Hero Numerals · Compact Send Queue (&le;64px) · Needs You"]
        PIPE["2. Pipeline View<br/>Funnel Bar · Jobs Table (Sortable, Searchable)"]
        LIB["3. Library View<br/>Accordions (Contacts, Drafts, Answers, QA, Runs)"]
    end
    subgraph Server["Dashboard Server (harness/dashboard.py)"]
        AUTH["Security Layer<br/>Host: 127.0.0.1 · X-Token · Strict CSP"]
        STATIC["Static File Server<br/>Path-traversal check · ETag · Gzip"]
        API["JSON API<br/>/api/state (compact) · /api/answers/<id>"]
        CTL["Control Router<br/>/ctl/toggle · /ctl/kill · /ctl/run_now · /ctl/mark"]
    end
    subgraph Backend["Harness Engine"]
        DB[("harness.db<br/>PRAGMA query_only = ON")]
        CTRL["tools/control.py"]
        NB["tools/network_batch.mark"]
        CYC["bin/cycle.sh"]
    end

    Client -->|"GET / · GET /css/* · GET /js/*"| STATIC
    Client -->|"GET /api/state (If-None-Match)"| API
    Client -->|"GET /api/answers/<id> (X-Token)"| API
    Client -->|"POST /ctl/* (X-Token + Host check)"| CTL
    API -->|"query_only reads"| DB
    CTL --> CTRL
    CTL --> NB
    CTRL --> DB
    NB --> DB
    CTRL -->|spawns| CYC
```

### Architectural Principles
1. **Zero Runtime Network Calls:** All fonts (Instrument Serif, Geist, Geist Mono) and assets are served locally from `harness/web/`. Works 100% offline with Wi-Fi disabled.
2. **Strict Security Model:** Binds strictly to `127.0.0.1`. Host header checks reject DNS-rebinding attacks. Sensitive answers are omitted from bulk payloads and only revealed on-demand via authenticated `/api/answers/{id}` with `X-Token`. Strict Content Security Policy (`default-src 'none'; script-src 'self'; ...`).
3. **Safe DOM Manipulation:** Zero `innerHTML` on untrusted database content; all elements are constructed using safe DOM methods (`createElement`, `textContent`).
4. **Safety Windows & In-Page Confirmations:** Marking a prefilled contact as `SENT` or `SKIPPED` invokes a 6-second in-page undo delay before the irreversible POST is dispatched. Destructive kill-switch activation requires a 600ms hold-to-confirm press.
5. **High Performance & Low Latency:** Initial paint transfer sizes are strictly budgeted (HTML $\le 8\text{ KB}$, CSS $\le 24\text{ KB}$, JS $\le 45\text{ KB}$ gzip). Polling every 5s on `/api/state` uses ETag/304 validation and pauses when the document is hidden.
