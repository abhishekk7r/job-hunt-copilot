---
title: Go-live checklist
description: Step-by-step checklist for the owner to safely run the autonomous system.
---

Follow this numbered checklist in order to safely configure, verify, and run the job search engine.

## Step-by-step checklist

1. **Accept Claude Code Workspace Trust Once:**
   Open a terminal and run:
   ```bash
   cd ~/Projects/jobsearch && claude
   ```
   Accept the workspace trust prompt when prompted, then exit Claude. If this is not done, Claude Code will ignore `--allowedTools` and deny Bash execution in unattended cycles.

2. **Verify Configuration Files:**
   Confirm that both personal configuration files exist and are populated with your preferences and background:
   - `config/search_profile.local.md`: role targets, locations, minimum CTC floor, and ranking rubric.
   - `config/applicant_facts.local.md`: your employment history (used for "have you worked at ...?" questions) and standing answers such as referral, relocation and equal-opportunity rules. Notice period is 30 days.

3. **Turn the Schedule ON:**
   On the dashboard header, open the schedule menu and set it to **Active** (`ctl:schedule = 1`).

4. **Observe the First Cycle (Jobs Phase):**
   Leave Portals and Live Submit turned **Off**. Watch the cycle progress on the dashboard status line in the header. It will execute logged-out searches (LinkedIn, Freehire, Wellfound), score listings, and populate the jobs pipeline.

5. **Read Cycle Logs on Halt:**
   If any phase halts, inspect the corresponding raw log in:
   ```bash
   reports/cycle_logs/<run_id>.<phase>.out
   ```
   Look for `CYCLE_HALT:` lines to see the exact challenge or timeout reason.

6. **Enable Portals Phase & Supervise One Run:**
   Turn Portals **ON** (`ctl:portals = 1`) via the dashboard settings. Observe one run in your logged-in Chrome browser to confirm Naukri and Instahyre searches execute smoothly without bot challenges.

7. **Verify Applications in Shadow Mode:**
   With Live Submit **Off** (`ctl:submit = 0`, the default), the apply phase runs in shadow mode:
   - Fills application forms without submitting.
   - Saves screenshots to `reports/apply_shadow/`.
   - Records pending questions in the dashboard review dialog.
   - Review pending questions in the review dialog, edit drafts if needed, or use "Skip this job" for unwanted roles.
   - Ensure `WOULD_SUBMIT` actions in `action_log` reflect accurate answers.

8. **Enable Live Submit:**
   Only after verifying shadow runs, turn Live Submit **ON** (`ctl:submit = 1`) in dashboard settings:
   - The submit toggle confirms live submission is active.
   - Applications will now submit automatically when `tools/decide.py gate` outputs PASS, capped at 25/day and 8/run.

9. **Handling Phase Halts & Re-Enabling:**
   - **Portals halt:** Indicates a CAPTCHA, challenge, or navigation error. Portals automatically toggles OFF. Resolve the issue in your Chrome tab, then toggle Portals back ON.
   - **Apply halt:** Any challenge or restriction resets `ctl:submit` to 0 (Off). Check cycle logs, verify browser state, and re-enable only after resolving the blocker.
   - **People halt:** Indicates a LinkedIn restriction, verification notice, or daily limit. People automatically toggles OFF. Resolve the notice in LinkedIn, then re-enable the People toggle.

10. **Emergency Stop (How to Stop Everything):**
    - **One-click Submit Stop:** Toggle Live Submit to OFF (`0`) in dashboard settings to immediately prevent live submissions.
    - **System-wide Kill Switch:** Hold the red **Kill Switch** button in the dashboard command bar for 600 ms (or run `./bin/killswitch on` in terminal). This immediately aborts all running phases and blocks all future cycles until disengaged.
