# /apply: Supervised Job Application Session

Supervised interactive job application command using Claude in Chrome, candidate facts, and the unified answers bank. Claude navigates, fills verified answers, and logs submissions with the owner nearby.

## Core Rules

- **Zero Invention:** Write answers only from `config/applicant_facts.local.md` or approved bank rows. Never invent employers, titles, metrics, or personal details.
- **Never Send / Bypass:** Never solve CAPTCHAs, never type passwords, never create accounts, never bypass bot walls.
- **Simplify Integration:** If the Simplify extension is present on the page, let it autofill (its resume is correct). **NEVER** click Simplify's own submit button.
- **Chrome Token Rule:** Read pages with `get_page_text`, `find`, or `read_page` first. Take a screenshot only when layout matters (a CAPTCHA, an unlabeled button, a visual-only check), and always at `scale: 0.5`. Batch predictable clicks and typing with `browser_batch`.
- **Pacing:** Pause 20 to 90 seconds between submissions (45 to 90 seconds on LinkedIn or Naukri). Stop immediately on any warning or restriction.

> **Windows:** run these tools as `python`, not `python3`.

---

## Execution Steps

### 1. Load Answers Bank and Candidate Facts
Export the answers bank once and hold it in context:
```bash
python3 tools/answers_bank.py export --status approved,drafted
```
Read `config/applicant_facts.local.md` for candidate personal details, skills, experience, and policies.

### 2. Fetch Eligible Jobs
Query next applications ready to be processed (skips `referral_first` jobs unless cleared):
```bash
python3 tools/decide.py next-jobs --limit 10
```

### 3. Application Loop (Per Job)
For each job returned by `next-jobs`:

1. **Re-run Gmail dedupe** for the company using Gmail MCP (`gmail_search`):
   ```text
   newer_than:60d ("thank you for applying" OR "application received" OR "received your application" OR "has your application")
   ```
   If an application confirmation exists for this company and role:
   ```bash
   python3 tools/decide.py mark-job --job <id> --status PARKED --reason already_applied --actor owner_session
   ```
   and proceed to the next job.

2. **Open Job Posting:** Open `job_url` in Claude in Chrome. Also open and read `reports/jobs/<id>.md` for role summary, ATS type, and pitch angle.

3. **Autofill & Manual Fill:**
   - If Simplify is active, let it autofill form fields. Do not click its submit button.
   - For every remaining blank or unconfirmed field, match against the exported answers bank or `config/applicant_facts.local.md`.

### 4. Handling Questions & Edge Cases

- **New Question Not in Bank:**
  Synthesize a concise, truthful answer strictly grounded in `applicant_facts.local.md`. Enter the answer into the form and save it as drafted:
  ```bash
  python3 tools/answers_bank.py add --question "<canonical question>" --answer "<answer text>" --kind fact --status drafted --source "job:<id>"
  ```
  (Choose `--kind` from: `fact`, `choice`, `story`, `policy`, `legal`).

- **Legal Questions Without Approved Row:**
  If a question is of kind `legal` (e.g. visa sponsorship, work authorization, non-compete, background checks) and no `approved` answer exists in the bank:
  - Fill all other form fields.
  - Leave the tab open for the owner.
  - Escalate:
    ```bash
    python3 tools/decide.py mark-job --job <id> --status NEEDS_INPUT --reason escalated --actor owner_session
    ```
  - Continue to the next job in a new tab.

- **Checkboxes & Consents:**
  - Mandatory consent, privacy policy, and terms of service checkboxes: tick them (owner-authorized).
  - Marketing opt-ins, promotional emails, and "follow company" checkboxes: leave unticked.

- **CAPTCHA / Challenge:**
  Fill all other fields, leave the tab open for owner resolution, record:
  ```bash
  python3 tools/decide.py mark-job --job <id> --status NEEDS_INPUT --reason challenge --actor owner_session
  ```
  Continue in a new tab.

- **Login / Account Creation / OTP:**
  Do not create accounts or type passwords. Mark as parked:
  ```bash
  python3 tools/decide.py mark-job --job <id> --status PARKED --reason login_required --actor owner_session
  ```
  Keep tab open and continue.

- **Naukri "Apply on company site":**
  Click only if the external company application form will be completed in this session.

### 5. Record Applied Details
Before submitting, write `reports/applied/<job_id>.md`:
- Every field label and the exact text/choice entered.
- List of bank row IDs used. For each row ID used, increment usage:
  ```bash
  python3 tools/answers_bank.py used <id>
  ```
- Resume file name used for the application.

### 6. Submission and Verification

- **Shadow Mode Check:** If running in shadow mode (`AUTOAPPLY_MODE=shadow`), stop before clicking Submit. Mark:
  ```bash
  python3 tools/decide.py mark-job --job <id> --status WOULD_SUBMIT --reason shadow_filled --actor owner_session
  ```
- **Live Submission:**
  Click the application Submit button.
  Verify the confirmation page/dialog using `get_page_text`.
  Append the confirmation message/text to `reports/applied/<job_id>.md`.
  Mark the job as applied:
  ```bash
  python3 tools/decide.py mark-job --job <id> --status APPLIED --reason submitted --actor owner_session
  ```
  *(Note: In automated cycle runs, use `--actor cycle`)*.

### 7. Pacing
Pause 20 to 90 seconds before starting the next application (45 to 90 seconds on LinkedIn or Naukri).
If any rate limit, warning, or unusual activity notice appears, stop the session immediately.

### 8. Session Summary
Output a markdown summary table of all processed jobs:

| Job ID | Company | Role | Status | Blocker / Tab Title | Drafted Answers Added |
|---|---|---|---|---|---|
| 104 | Stripe | Backend Engineer | APPLIED | Submitted successfully | #42 ("Years of Kafka") |
| 105 | Datadog | Systems Engineer | NEEDS_INPUT | Tab: "Security Verification" (CAPTCHA) | None |
| 106 | Figma | Core Infra SDE | PARKED | Tab: "Workday Sign-In" (login_required) | None |

<!-- Canonical tracker header:
date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source,deadline
-->
