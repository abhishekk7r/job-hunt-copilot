# Manager runbook: supervising Antigravity (Claude's role)

Claude is the manager and senior reviewer. Antigravity (agy) implements. The owner does not interact with either.

## Sequence
1. **Run 1 (portals)** on `feat/india-portals` from `docs/ANTIGRAVITY_PORTALS_PROMPT.md`. Done when a commit subject contains `(T7`.
2. **Review run 1** against `docs/design/PORTALS_AND_JD_MATCHING.md` section 5 (acceptance): `make test`, the removal grep, `lint_skills.py`, `security_guards.py`, privacy and no-bot-browser tests, real `harness.db` row counts unchanged, `adversarial-review` on `git diff feat/india-portals~N..HEAD`. Send fixes through agent-bridge (`REVIEW T<n>: FAIL ...`). Only continue when green.
3. **Run 2 (autonomy and progress)**: `git checkout -b feat/autonomy-progress` from the reviewed branch, then launch in the background:
   `agy -p "Read docs/ANTIGRAVITY_AUTONOMY_PROMPT.md fully and execute tasks A1 to A8 in order ..." --add-dir ~/Projects/jobsearch --mode accept-edits --print-timeout 0`
   (print mode runs shell commands without prompts; `--mode auto` is not available on this account; never use `--dangerously-skip-permissions`).
4. **Supervise run 2**: for each `TASK_DONE A<n>` message, review the commit, run `make test`, verify the task's acceptance, then reply `REVIEW A<n>: PASS` or `FAIL` with numbered items. Re-check fixes. At `FINAL`, run the full review again.
5. **Owner hand-off**: summary of what changed, what to switch on (`Portals`, `Auto-apply: Shadow`), what to watch on the first runs, and the push command. Never push without the owner's say-so.

## Review checklist (every task)
- Does the diff do what the design says, no more? Any file changed that was not needed?
- Tests: new behaviour covered, edge cases, failure paths; real database untouched.
- Rules: no bot browsers, no network, no send/apply/submit, no inline styles or innerHTML, no personal data or banned strings in tracked files.
- Fail-open where required (progress must never break a cycle); fail-closed where required (submit gate, hard stops).
- Prompts and code agree (command shapes, allow-lists, step catalog).
