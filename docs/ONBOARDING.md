# Onboarding Guide: AI Job Search

## 1. What It Is
AI Job Search is a privacy-first, autonomous and supervised job search copilot for software engineers.
It continuously discovers and ranks tech roles across multiple portals, fills applications using a verified facts and answers bank, and identifies key team contacts for high-touch outreach.
The entire workflow is driven by four unified user commands: `/find`, `/apply`, `/reach`, and `/send`.

### The Four Commands
| Command | What it does | Supervised? |
|---|---|---|
| `/find` | Discovers jobs across portals, generates research notes, ranks candidates, and deduplicates against Gmail confirmations and the database. | Automated / Interactive |
| `/apply` | Supervised application session in Chrome: navigates posting, fills fields from verified answers bank, leaves CAPTCHAs/logins open, submits, and records status. | Supervised in Chrome |
| `/reach` | Discovers target peers, managers, and recruiters (up to 4 per applied job) on LinkedIn with rate caps and drafts tailored connection notes, InMails, and emails passing strict validation. | Automated |
| `/send` | Interactive dispatch walkthrough: opens profiles/drafts in Chrome, pastes validated text, and stops for the user to review and click Send. | Supervised in Chrome |

---

## 2. Prerequisites
- **Operating System:** macOS or Linux
- **Python:** Python 3.11+
- **Bun:** Bun runtime (`curl -fsSL https://bun.sh/install | bash`)
- **Browser:** Google Chrome with the official Claude in Chrome extension installed
- **Claude Code:** Claude Code CLI signed in (`npm install -g @anthropic-ai/claude-code`)
- **GitHub CLI (optional):** `gh` for repository management

**Total Setup Time:** ~15 minutes.

---

## 3. Getting Started

### Step 1: Clone the Repository
```bash
git clone <your-repo-url> jobsearch
cd jobsearch
```

> [!IMPORTANT]
> Keep your repository private. Candidate personal details, employment history, and salary facts live in git-ignored local files (`config/*.local.*`, `config/local.toml`, `harness.db`) and are guarded against accidental commits.

### Step 2: One-Command Environment Setup
Run the automated environment bootstrap:
```bash
make setup
```
This target:
1. Creates a Python virtual environment (`.venv`) if not present.
2. Installs Python dependencies (`pip install -r requirements.txt`).
3. Installs Bun dependencies for the TypeScript search CLIs (LinkedIn, Freehire, Wellfound).
4. Initializes and runs SQLite migrations on `harness.db`.

### Step 3: Launch Claude Code
Open your interactive Claude Code session in the repository root:
```bash
claude
```

### Step 4: Run `/find` (First-Run Profile Setup)
Run the search command:
```text
/find
```
On your very first run, `/find` detects missing configuration files and prompts you through a quick onboarding questionnaire:
- Full Name, Email, Phone, and Current City
- Resume path or URL
- Notice period, current CTC, and target CTC
- Target roles and key technical skills (with years of experience)
- Past employers and education

It populates `config/local.toml` and `config/applicant_facts.local.md`, imports the answers bank, and immediately begins searching job portals.

---

## 4. Daily Routine (~30–45 Minutes)

1. **Morning Discovery (`/find`):** Run `/find` to aggregate overnight postings across LinkedIn, Freehire, and Wellfound, score them against your rubric, and generate research notes for matching jobs.
2. **Supervised Application Session (`/apply`):** Run `/apply` while sitting nearby. Claude navigates each open posting in your Chrome browser, fills answers from your answer bank, leaves any CAPTCHA or login wall for you to clear, and submits applications with full logging.
3. **Contact Discovery & Drafting (`/reach`):** Run `/reach` to find relevant engineers, managers, and recruiters for the jobs you just submitted. Claude generates custom, deterministic outreach drafts that pass strict length and format validators.
4. **Dispatch Review (`/send`):** Run `/send` to deliver your outreach. Claude walks through pending drafts, opens the recipient's profile or Gmail draft in Chrome, pastes the message text, and halts so you can review and click Send yourself.

---

## 5. Guide for Contributors

### Repository Map
- `.agents/skills/`: Portable Agent Skills and TypeScript portal CLIs (`linkedin-search`, `freehire-search`, `wellfound-search`, `reach`, `send`).
- `.claude/commands/`: Primary workflow command definitions (`find.md`, `apply.md`, `reach.md`, `send.md`).
- `.claude/commands/extra/`: Namespaced secondary commands and utilities (sync, reporting, expansion, reset).
- `.claude/skills/`: Domain skill packs for evaluation, templates, and interview prep.
- `bin/`: Shell scripts for cycle automation, kill switch, and background runners.
- `config/`: Configuration schemas, templates, and example files.
- `docs/`: Architectural specifications, design documents, and cycle prompt templates.
- `harness/`: Job Harness core backend (FastMCP server, SQLite data model, dashboard, outreach validator).
- `migrations/`: Schema migration scripts for `harness.db`.
- `reports/`: Generated run outputs, research notes, and daily digests (git-ignored).
- `tests/`: Comprehensive pytest suite validating privacy, security guards, CLI flags, and command contracts.
- `tools/`: Python CLI utilities for scraping state, query planning, deduplication, answers bank, and decision logging.

### Testing & Verification
Run the complete automated test suite before committing:
```bash
make test       # Runs privacy guards, Python unit/integration tests, and Bun CLI tests
make test-web   # Runs web harness frontend tests
```

### PII & Privacy Guard
The test suite enforces a strict zero-PII commitment via `tools/check_pii.py` and `tests/test_privacy.py`. Never commit real names, email addresses, phone numbers, or private employer details into tracked files. All personal profile data must reside in git-ignored `.local.*` files.

### Adding a New Job Board
To integrate a new job portal:
1. Create a portal skill directory in `.agents/skills/<portal>-search/` with `SKILL.md` and CLI implementation.
2. Implement search and detail scraping subcommands adhering to the standard schema (`id`, `title`, `company`, `location`, `url`, `date_posted`).
3. Add portal configuration mapping in `tools/query_plan.py` and `tools/fetch_postings.py`.
4. Register tests under `tests/test_install_portal_clis.py`.
