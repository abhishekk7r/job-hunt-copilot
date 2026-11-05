---
name: naukri-search
version: 1.0.0
description: >
  Search software engineering, backend, and distributed systems jobs across India on Naukri.com.
  Configured for read-only in-Chrome reading via portals phase.
context: fork
enabled: false
---

# Naukri Search Skill (India)

Searches software engineering, backend developer, and distributed systems vacancies across Indian tech hubs (Bangalore, Remote) on **[Naukri.com](https://www.naukri.com)**.

## Execution Policy: Supervised In-Chrome Only (Tier B)
No scripted fetching: plain-HTTP automated scraping of Naukri is dropped because Naukri is a JavaScript shell that returns no job cards over plain HTTP.
This portal is read in the user's own Chrome by the 6-hourly cycle's portals phase (`docs/cycle_prompts/portals.md`).
- **Status:** `enabled: false` (default OFF, controlled via `ctl:portals` toggle).
- **Caps:** At most 3 search pages and 5 job-detail pages per run, with 4 to 12s pauses between pages.
- **Allowed paths only:** `/*-jobs*` slug pages and `/job-listings*`.
- **Forbidden paths:** Never visit `/jobsearch/` or `/candidate/`.
- **Challenge policy:** Halts immediately on any CAPTCHA, Cloudflare challenge, or rate limit warning, turning `ctl:portals` off.
- **Actions:** Purely read-only; never clicks Apply, Save, Easy Apply, or login controls.
