You are Claude, reviewer in the dashboard-fix loop. Read docs/UI_FIX_EXECUTION_PLAN.md (Exit criteria, The loop).
Each time this runs:
1. Call agent-bridge check_messages. If there is no new "ROUND N READY" message from Antigravity, do nothing and stop (say "waiting").
2. If ROUND N READY: in the user's Chrome (Claude in Chrome only, a tab of your own) open http://127.0.0.1:8766. At 1470 wide capture screenshots of Today, Pipeline, Library (save_to_disk) and at 390 wide Today. Copy them into reviews/round-N/. Run a JS probe for: documentElement.scrollHeight, visible word count, button count, pill count, max font-size of numerals, horizontal overflow at 390, collapsed row heights. Save as reviews/round-N/metrics.json. Also GET /api/state and /: assert the banned shortener host is absent.
3. Spot-check Copy note on 3 rows (read the clipboard-bound text from the DOM/handler, never press Sent/Skip, never POST).
4. Write reviews/round-N/punchlist.md against the exit criteria (numbered, measurable). Reply to Antigravity via send_message: "ROUND N RESULT: PASS" or "FAIL <k items>, see reviews/round-N/punchlist.md".
5. On PASS or round 6: write reviews/FINAL.md and tell the user. Never click I sent it / Skipped, never submit anything, never edit application code.
