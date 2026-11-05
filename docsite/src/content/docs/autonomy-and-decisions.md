---
title: Autonomy and decisions
description: How autonomous job applications, submit control, screening question decisions, and the safety gate work.
---

The autonomy engine enables safe job applications during the scheduled cycle. It is designed around deterministic decision policies, strict server-side safety checks, and unambiguous operational boundaries.

## Submit Switch (`ctl:submit`)

Application submission is governed by a single control, `ctl:submit`:

| Mode | Value | Behavior |
|---|---|---|
| **Shadow** | `0` | **Default.** The apply phase fills application forms via Simplify and native inputs, evaluates all fields, records decisions to the inbox, stops before submission, and logs `WOULD_SUBMIT`. |
| **Live** | `1` | Evaluates the strict safety gate, clicks the page's native Submit button only if the gate passes, and logs `APPLIED`. |

### Control Safeguards

- **Shadow by Default:** Applications never submit live unless `ctl:submit` is explicitly turned ON (1).
- **One-click Stop:** The owner can flip the submit switch off at any time from the dashboard settings.
- **Audit Log:** State transitions and application results are recorded in `action_log` with timestamp and reason.

## The 4-Outcome Policy (`tools/decide.py`)

Every form input encountered on an application page is evaluated deterministically into one of four outcomes:

1. **`AUTO`:** An exact or normalized match was found in `screening_qa`, or an owner decision was previously approved for this job. Filled automatically.
2. **`AUTO_LOG`:** Derived deterministically from verified applicant facts (e.g. checking company affiliation against past employers in `applicant_facts.local.md`). Filled and logged.
3. **`ESCALATE`:** Requires owner decision (custom essay questions, referral queries, compensation out of range, ambiguous company names). Creates a pending decision row in `decisions` and parks the job as `NEEDS_INPUT`.
4. **`HARD_STOP`:** Prohibited actions (CAPTCHA, OTP, login, password creation, payment, SSN/ID card upload). Parks the job as `BLOCKED_USER` and moves to the next job.

## Unified Review Dialog

When the cycle parks jobs with questions requiring input:

- **Grouped by Company:** The review dialog groups pending questions under their respective target company.
- **Skip This Job:** Each company section includes a "Skip this job" checkbox. Checking it parks the job as `NEEDS_INPUT` without submitting or answering.
- **Answer Proposals:** Suggested drafts appear in inline textareas where the owner can review or edit answers before submitting.
- **Promote to Global Rules:** General screening questions can be promoted to `screening_qa` so future postings answer them automatically. Company-specific questions remain scoped per job.

## Command Injection Immunity

DOM text, form labels, and options from external web pages are untrusted external data.

:::caution[No Raw Page Text on CLI]
Form field labels and attributes are **never** interpolated into command-line arguments.
:::

Instead:
1. Field attributes are saved to a JSON file at `reports/cycle_work/<CYCLE_NUMBER>/field_<n>.json`.
2. The policy engine is invoked with:
   `python3 tools/decide.py classify --input reports/cycle_work/<CYCLE_NUMBER>/field_<n>.json --job-id <id> --run-id <RUN_ID>`
3. State changes via `mark-job` accept only safe enumerated reason codes:
   `hard_stop`, `escalated`, `gate_failed`, `shadow_filled`, `submitted`, `login_required`, `cap_reached`, `challenge`.

## The Pre-Submit Gate & Caps

Before any live application is submitted, `python3 tools/decide.py gate --job <id> --run-id <RUN_ID>` evaluates:
- Kill switch is off.
- Job status is `TO_APPLY`.
- Rank verdict is at least Good Fit / High (weight ≥ 3).
- Offered salary meets or exceeds minimum floor from the identity capsule.
- Job location is in target markets.
- All field decisions in `decision_log` are resolved (no outstanding `ESCALATE` or `HARD_STOP`).
- `ctl:submit == 1` (gate fails if submit switch is 0).
- Daily application cap (25/day) and run cap (8/run) are not exceeded.

On PASS, `gate()` writes a `gate_pass` row to `action_log`. `mark-job --status APPLIED` requires this recent `gate_pass` within 30 minutes. Immutable statuses (`APPLIED`, `BLOCKED_USER`, `CONTACTED`, `COMPANY_SITE_ONLY`, `OUTREACH_DRAFTED`) are strictly protected from downgrades.
