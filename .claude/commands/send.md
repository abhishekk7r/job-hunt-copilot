# /send: Supervised Outreach Review and Dispatch

Review, customize, and deliver prepared outreach drafts (LinkedIn Connection Notes, InMails, and Gmail drafts) one by one with the user in the loop. The agent navigates and pastes text into Chrome tabs and stops; the user inspects and clicks Send.

## Core Rules

- **User Clicks Send:** Claude **NEVER** clicks Send, Connect-Send, or Send Now. Claude opens the tab, navigates to the profile/draft, pastes the message text, and **STOPS** for the user.
- **Daily Caps (Reset UTC day):**
  - LinkedIn Notes / Prefills: **25/day max**
  - InMail Credits: tracked in `budgets.inmail_credits`
- **Confirmation Loop:** For every draft, show the message text and ask the user: `"Send this one? (yes / edit / skip)"`.
- **Status Sync:** When the user confirms the message has been sent, run `tools/mark_outreach_sent.py --queue-id <id>` to update status to `SENT`, set follow-up date (default 6 days), and log to `action_log`.
- **Stop on Warning:** Cease immediately if LinkedIn or Gmail shows a rate limit, CAPTCHA, or challenge.

> **Windows:** run these tools as `python`, not `python3`.

---

## Execution Steps

### 1. Check Caps and Fetch Pending Drafts
Check today's outreach usage and pull all pending drafts from `outreach_queue`:
```bash
python3 tools/network_batch.py status
python3 tools/reachout_data.py --drafts
```
If today's daily cap is reached (25 notes), stop and notify the user.

### 2. Interactive Review Loop (One by One)

For each draft returned:

1. **Display Draft Details to User:**
   ```text
   ------------------------------------------------------------
   Draft ID: <id> | Channel: <channel>
   Target: <recruiter_name> (<company> - <role>)
   Profile: <recruiter_linkedin>
   Message (chars: <char_count>):
   "<rendered_message>"
   ------------------------------------------------------------
   ```
2. **Ask User:**
   `"Send this one? (yes / edit / skip)"`

3. **Handle Response:**

   - **If `skip`:**
     Mark the draft skipped in `outreach_queue`:
     ```bash
     python3 -c "import sqlite3; c=sqlite3.connect('harness.db'); c.execute(\"UPDATE outreach_queue SET approval_status='SKIPPED_BY_USER' WHERE id=?\", (<id>,)); c.commit()"
     ```
     Proceed to the next draft.

   - **If `edit`:**
     1. Prompt user for revised text or adjust based on their instructions.
     2. Save edited text to a temporary file (`/tmp/revised_msg.txt`).
     3. Revalidate message:
        ```bash
        python3 tools/outreach.py validate --channel <note|inmail|email> --job <job_id> --file /tmp/revised_msg.txt
        ```
     4. On successful validation, update `rendered_message` and `char_count` in `outreach_queue`, then continue to sending.

   - **If `yes`:**
     - **For LinkedIn Connection Note:**
       1. Run pre-action tick counter:
          ```bash
          python3 tools/network_batch.py tick note
          ```
       2. In **Claude in Chrome**, open candidate's LinkedIn `profile_url` in a new tab.
       3. Click `Connect` -> `Add a note`.
       4. Type the verified message text into the note input box.
       5. **STOP.** Leave the tab open. Prompt user:
          `"Note pasted in Chrome. Please review and click Send. Type 'sent' when done (or 'cancelled' to skip)."`
       6. Wait for user response.

     - **For LinkedIn InMail:**
       1. In **Claude in Chrome**, open candidate's LinkedIn `profile_url`.
       2. Click `Message` (InMail composer).
       3. Fill Subject and Body with the drafted InMail message.
       4. **STOP.** Leave tab open. Prompt user:
          `"InMail composed in Chrome. Please review and click Send. Type 'sent' when done (or 'cancelled' to skip)."`
       5. Wait for user response.

     - **For Email / Gmail Draft:**
       1. In **Claude in Chrome**, navigate to Gmail drafts (`https://mail.google.com/mail/u/0/#drafts`) or open the created draft.
       2. **STOP.** Prompt user:
          `"Gmail draft opened in Chrome. Please review and click Send. Type 'sent' when done (or 'cancelled' to skip)."`
       3. Wait for user response.

4. **Record Sent Status:**
   When user confirms `"sent"`:
   ```bash
   python3 tools/mark_outreach_sent.py --queue-id <id>
   ```
   This automatically:
   - Updates `outreach_queue.approval_status` to `SENT`.
   - Decrements InMail budget if channel was InMail.
   - Sets `jobs.outreach_state = 'SENT'` and calculates `next_followup` (default 6 days).
   - Syncs `contacts.status = 'SENT'`.
   - Appends audit event to `action_log`.

   If user indicates `"cancelled"`, leave draft in queue or mark skipped.

5. **Pacing:**
   Pause 15-45 seconds between messages to maintain human-like timing.

---

## 3. Session Summary
Output a table of actions taken:

| Draft ID | Recruiter | Company | Channel | Outcome | Follow-Up Date |
|---|---|---|---|---|---|
| 5 | Alex Example | Acme Corp | LinkedIn DM | SENT | 2026-11-11 |
| 6 | Priya Sample | Globex | InMail | SENT | 2026-11-11 |
| 7 | Sam Placeholder | Initech | InMail | SKIPPED | - |
