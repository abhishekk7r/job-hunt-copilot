---
name: wellfound-search
version: 1.0.0
description: >
  Search startup engineering, early-stage product, and high-growth tech positions on Wellfound.
context: fork
enabled: true
allowed-tools:
  - Bash(bun run .agents/skills/wellfound-search/cli/src/cli.ts *)
---

# Wellfound Search Skill

Searches high-growth startup, seed to Series D software engineering roles on **[Wellfound](https://wellfound.com)** (formerly AngelList Talent).

## Access & Operation
- **Status:** `enabled: true`. Headless, logged out HTTP access via public role pages.
- **Volume Cap:** At most 1 request per 3 seconds.
- **Endpoints:** Uses public role endpoints (`/role/l/<role>/<location>` and `/role/r/<role>`).
- **Challenge Policy:** Halts immediately on any HTTP 403, 429, or Cloudflare challenge; never attempts bypass.
