# /network - Daily 25-person networking batch (prefilled tabs, user presses Send)

Finds up to **25 people per day** who are most likely to help get the user hired, writes a ≤300-character connection note for each, and opens each one as a prefilled LinkedIn tab in the user's own Chrome. **The user decides who to send to. Claude never clicks Send.**

## Who to target (peers over leaders)
- Priority: Senior SDEs / SDE-2 peers on the hiring team, Engineering Managers, technical recruiters / TA leads.
- Same-stack people (Java, Spring Boot, AWS, Kafka, microservices) rank higher.
- Companies where a job is already `APPLIED` rank first (warm), then `TO_APPLY` targets, then tier-1/2 companies.
- **Never** VP, SVP, CTO, CEO, Director, Head of, Founder, President. `tools/contacts.py` rejects them (`is_executive`), and the batch builder skips them again.
- Reject ex-employees of the target company. Max 3 people per company.

## Hard rules
- Claude in Chrome only, in the user's own logged-in Chrome. Never Playwright, patchright, Selenium, Puppeteer or the `linkedin` MCP.
- Connection notes are deterministic (`render_connection_note`). "I've applied for…" only if the job is really `APPLIED`. Never invent shared history.
- Resume links: only the canonical URL in config. Banned link shorteners from config are rejected.
- Type the note into the "Add a note" box and STOP. **Never click Send / Connect-send / Message-send.**
- Stop the batch immediately on CAPTCHA, login challenge, rate-limit text or an unusual page. Record the reason and tell the user.
- Cap: 25 prefilled tabs per day (counted in `action_log`), max 20 people-search page loads per run, randomized pauses of a few seconds between page loads.
- Check the kill switch first (`bin/killswitch status`); the batch builder returns HALTED if it is on.

## Flow
1. **Discover** (Claude in Chrome): for each target company (APPLIED first, then TO_APPLY, then tier ≤ 2) run a LinkedIn people search in the user's Chrome for the roles above. Collect name, headline/title, profile URL, connection degree, mutual connections, location.
2. **Score and store**: pass candidates to `save_ranked_contacts(job_id, company, candidates, db_path, job_applied, role)` in `tools/contacts.py`. This scores them, rejects executives and ex-employees, dedupes by profile URL, and saves `PROPOSED` rows.
3. **Build the batch**: `python3 tools/network_batch.py build` selects up to 25 (minus today's already-prefilled), re-renders each note against live job status, validates length and banned links, and writes `reports/network-batch-YYYY-MM-DD.json` and `.md`.
4. **Prefill tabs**: for each item in the manifest, open `profile_url` in a new Chrome tab, click Connect → Add a note, type `note_text`, then stop. After each tab run `python3 tools/network_batch.py mark <contact_id> PREFILLED`. If Connect is not offered (Follow-only or Message-only profile), mark it `SKIPPED` with a detail and move on.
5. **User reviews the tabs** and presses Send on the ones they want, closing the rest.
6. **Record outcomes**: when the user says who they sent, run `python3 tools/network_batch.py mark <contact_id> SENT`; for ones they closed, `SKIPPED`. `python3 tools/network_batch.py status` shows today's count.

## Tracking
Contact statuses: `PROPOSED` → `PREFILLED` → `SENT` or `SKIPPED` (also `SKIPPED_TOO_SENIOR`). `SENT` is never downgraded. Every transition is logged in `action_log`. The dashboard shows today's batch and counts.
