# /reach: Find People & Draft Custom Outreach

> **Safer note:** Automating LinkedIn, even read-only, breaks LinkedIn's terms of service and can
> get your account restricted or banned. The same goes for other job sites. Use these features at
> your own risk, keep the daily limits low, and stop at the first warning. This project never
> sends messages or connection requests for you; you press Send.

Discover the right team members, engineering managers, and recruiters for recent applications and referral-first jobs, and prepare custom outreach drafts.

## Core Rules

- **Targets:**
  1. Jobs with status `APPLIED` submitted in the last 14 days with no contacts saved yet (highest rank score first).
  2. Jobs with status `TO_APPLY` flagged as `referral_first: yes`.
- **Target Roles (Max 4 contacts per job):**
  - **Engineers (max 2):** Same level or one level above in the same team/org (e.g., SDE-2, Senior Backend Engineer, Staff Engineer).
  - **Manager (max 1):** Engineering Manager or Software Development Manager for the team.
  - **Recruiter (max 1):** Technical Recruiter or Talent Acquisition Partner aligned with the role.
- **Strictly Excluded Roles:** **NEVER** target VP, SVP, EVP, Director, Head of, CTO, CEO, Founder, or General Manager. Executive candidates are automatically filtered out.
- **Affinity Preferences:** Prefer 1st/2nd degree connections, shared past employers or schools from `config/applicant_facts.local.md`, and same location/city.
- **Deduplication:** Always skip anyone already listed in `tools/reachout_data.py` `already_contacted`.
- **Rate Limits & Caps (Reset daily by UTC day):**
  - LinkedIn people searches: **15/day**
  - LinkedIn profile reads: **40/day**
  - Prefilled outreach / notes: **25/day**
  - Apollo email matches (optional with `--with-email`): **5 per run**, EM and Recruiter contacts only.

> **Windows:** run these tools as `python`, not `python3`.

---

## Execution Steps

### 1. Check Reach State & Targets
Retrieve targets needing contacts and review people already contacted:
```bash
python3 tools/reachout_data.py --targets
python3 tools/reachout_data.py
python3 tools/network_batch.py status
```

### 2. Rate Limit Check Before Reads
Before performing **any** LinkedIn search or profile read, execute the appropriate tick counter:
- For search queries:
  ```bash
  python3 tools/network_batch.py tick search
  ```
- For profile detail views:
  ```bash
  python3 tools/network_batch.py tick profile
  ```
**HARD STOP:** If the command output prints `CAP`, immediately cease further LinkedIn queries and stop the phase.

### 3. Contact Discovery
For each target job:
1. Search people using `linkedin` MCP read tools:
   - `search_people` (search by company and role keywords)
   - `get_company_employees`
   - `get_person_profile`
   *(Or Claude in Chrome as fallback using `get_page_text` and `find`)*.
2. Select up to 4 contacts matching the role quota (2 engineers, 1 manager, 1 recruiter).
3. Formulate a 1-line reason `note` grounded in verified facts (e.g. "Platform team peer, 2nd degree, shared AWS experience").

### 4. Save Discovered Contacts
Save candidates into `contacts` table using `tools/save_candidates.py`:
```bash
cat << 'EOF' | python3 tools/save_candidates.py
{
  "job_id": 101,
  "company": "Acme Corp",
  "candidates": [
    {
      "name": "Alex Smith",
      "title": "Senior Software Engineer",
      "profile_url": "https://www.linkedin.com/in/alexsmith",
      "connection_degree": 2,
      "mutual_connections": 2,
      "location": "Bengaluru",
      "kind": "senior_sde",
      "note": "Peer engineer on core backend team, shared Distributed Systems background"
    },
    {
      "name": "Sarah Connor",
      "title": "Engineering Manager",
      "profile_url": "https://www.linkedin.com/in/sarahconnor",
      "connection_degree": 2,
      "location": "Bengaluru",
      "kind": "hiring_manager",
      "note": "EM for Payments Infra team"
    }
  ]
}
EOF
```

### 5. Optional Email Discovery (`--with-email`)
If invoked with `--with-email` (default OFF):
- Run Apollo MCP `apollo_people_match` for at most 5 candidates per run.
- Restrict to Engineering Manager and Recruiter contacts.
- Report Apollo credits consumed in the summary.

### 6. Custom Outreach Drafting & Validation

For each saved contact, draft a message across the appropriate channel:
- **Connection Note:** $\le 300$ characters.
- **InMail:** subject $\le 200$ chars, body $\le 1900$ chars (only if `inmail_credits` > 0 and not connected).
- **Email:** subject $\le 200$ chars, only if verified email is present.

#### Message Construction Rules:
- **Who you are in one line.**
- **Exact role applied for:** When the job is `APPLIED`, the message body must state `"I have applied"`.
- **One specific reason** tied to this person or team (from contact note and job research note).
- **One concrete fact** from `config/applicant_facts.local.md` that matches the role.
- **One clear ask:** Ask for a referral for `referral_first` jobs; a quick chat or passing resume to hiring team otherwise.
- **Canonical resume link:** Required for Email and InMail. No other resume links permitted.
- **Strict plain text:** Zero markdown, zero emojis, zero link shorteners.
- **No invented metrics:** Every number or percentage in the message must appear in `config/applicant_facts.local.md` or `reports/jobs/<job_id>.md`.

#### Mandatory Validation:
Write each prospective message to a temporary file and validate it:
```bash
python3 harness/outreach.py validate --channel note --job <job_id> --file <path>
```
*(Choose channel: `note`, `inmail`, or `email`). The command must exit with code 0 before saving.*

### 7. Output Prefills and Drafts
- **Connection Note:** Claude in Chrome opens the profile, clicks Connect -> Add a note, types the message, and **STOPS**. Never click Send.
  ```bash
  python3 tools/network_batch.py mark <contact_id> PREFILLED
  ```
- **InMail:** Open compose, fill subject and body, and **STOPS**. Mark `PREFILLED`.
- **Email:** Create draft via Gmail MCP `gmail_create_draft` only. Record in `outreach_email_drafts`.
- All drafts are queued in `outreach_queue` with `approval_status = PENDING_MOBILE_REVIEW` for the owner to review and send.

### 8. Summary Table
Output a clean markdown table of discovered contacts:

| Job ID | Company | Role | Contact Name | Title | Channel | Status | Note / Draft Summary |
|---|---|---|---|---|---|---|---|
| 101 | Acme Corp | Senior Backend Engineer | Alex Smith | Senior Software Engineer | Connection Note | PREFILLED | Tab left open for owner |
| 101 | Acme Corp | Senior Backend Engineer | Sarah Connor | Engineering Manager | Email | DRAFTED | Gmail draft created |
|---|---|---|---|---|---|---|
| 101 | Acme Corp | Senior Backend Engineer | Alex Smith | Senior Software Engineer | senior_sde | Peer engineer on core backend team |
| 101 | Acme Corp | Senior Backend Engineer | Sarah Connor | Engineering Manager | hiring_manager | EM for Payments Infra team |
