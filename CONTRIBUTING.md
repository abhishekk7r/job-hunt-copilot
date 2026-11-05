# Contributing to job-hunt-copilot

Thanks for considering a contribution! This repository is designed to help job seekers automate the repetitive, tedious parts of job hunting while keeping full human control.

## Guiding Principles

1. **User In Control**: We never send messages, connect with people, or submit forms automatically. The user is always in the loop to review and click Submit and Send.
2. **Privacy First**: Personal data lives strictly in git-ignored files (`config/local.toml`, `config/*.local.*`). PII guards enforce this locally and in tests.
3. **Robustness & Tests**: Contributions should include automated unit tests and pass all existing test suites.

## Development Workflow

1. Setup the environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Run the tests:
   ```bash
   make test
   make test-web
   ```

3. Ensure PII check passes:
   ```bash
   python3 tools/check_pii.py
   ```

## Pull Requests

- Keep pull requests focused on a single feature or bugfix.
- Follow Conventional Commits for commit messages (`feat: ...`, `fix: ...`, `docs: ...`).
- Verify no personal data or secrets are included in your changes.
