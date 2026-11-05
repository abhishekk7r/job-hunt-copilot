---
name: instahyre-search
version: 1.0.0
description: >
  Search curated tech, startup, and product engineering vacancies in India on Instahyre.
  Configured for read-only in-Chrome reading via portals phase.
context: fork
enabled: false
---

# Instahyre Search Skill (India)

Searches curated startup, product tech, and software engineering opportunities in India on **[Instahyre](https://www.instahyre.com)**.

## Execution Policy (Tier B, Read-Only in Chrome)
No scripted fetching: Instahyre protects all plain HTTP requests (including the homepage) with Cloudflare anti-bot challenges.
This portal is read in the user's own Chrome by the 6-hourly cycle's portals phase (`docs/cycle_prompts/portals.md`).
- **Status:** `enabled: false` (default OFF, controlled via `ctl:portals` toggle).
- **Caps:** At most 3 search pages and 5 job-detail pages per run, with 4 to 12s pauses between pages.
- **Allowed paths only:** `/jobs/` public listings (`/jobs/?search=<slug>` UNVERIFIED). If the page shows 0 results or a different layout, report `PORTAL instahyre pages=<n> seen=0 note=unverified-url` and move on; never guess selectors or try other URLs.
- **Forbidden paths:** Never visit `/candidate/`.
- **Challenge policy:** Halts immediately on any Cloudflare challenge, CAPTCHA, or rate limit warning, turning `ctl:portals` off.
- **Actions:** Purely read-only; never clicks Apply, Save, Easy Apply, or login controls.
