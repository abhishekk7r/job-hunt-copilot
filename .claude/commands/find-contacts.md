# /find-contacts - Discover Recruiters and Hiring Managers

Searches LinkedIn in the user's Chrome for recruiters, engineering managers, and talent acquisition leads for `APPLIED` jobs.

## Guidelines
1. **Current Company Must Match:** Always verify candidate currently works at the employer. Exclude "Ex-<company>" or former staff.
2. **Cap:** Up to 20 people-searches per run (Addendum A cap).
3. **No Messaging Here:** This command only discovers and ranks contacts. It does not send messages.

## Execution Flow

1. Check agent bridge messages:
   ```json
   {"tool": "agent-bridge:check_messages", "arguments": {"wait_seconds": 0}}
   ```
2. Identify up to 20 `APPLIED` jobs in `harness.db` that currently have no entry in `contacts`.
3. In **Claude in Chrome**, for each job:
   - Search LinkedIn: `<company> technical recruiter OR engineering manager OR talent acquisition`.
   - Extract up to 5 matching profiles: name, title, current company, profile URL, connection degree, mutual connections, location.
   - Run deterministic scoring and save top 3 candidates to `contacts` using `tools/contacts.py`.
4. If rate limit or CAPTCHA text is seen, immediately halt and message the bridge:
   ```json
   {"tool": "agent-bridge:send_message", "arguments": {"text": "HALTED: LinkedIn rate limit in /find-contacts", "to": "all"}}
   ```
