# Wellfound Search CLI

Self-contained CLI for searching Wellfound (formerly AngelList Talent) public role and location pages.
Zero runtime dependencies; runs under Bun.

## Usage

```bash
bun run src/cli.ts search --role software-engineer --location india --format json
bun run src/cli.ts detail https://wellfound.com/jobs/2448180-software-engineer --format plain
```

## Security & Ethics
- Headless, logged out requests only.
- Strict rate limiting: at most 1 request per 3 seconds.
- Stops immediately on any challenge or rate-limit indicator without bypass.
