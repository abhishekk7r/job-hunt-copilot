.PHONY: setup docs test test-python pii-check test-bun test-web lint dashboard nightly

VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip
PYTEST ?= $(VENV)/bin/pytest
BUN ?= $(shell which bun 2>/dev/null || echo $$HOME/.bun/bin/bun)

setup:
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@if [ -x "$(BUN)" ]; then \
		echo "Installing Bun dependencies for search CLIs..."; \
		export PATH="$$HOME/.bun/bin:$$PATH"; \
		(cd .agents/skills/linkedin-search/cli && $(BUN) install); \
		(cd .agents/skills/freehire-search/cli && $(BUN) install); \
		(cd .agents/skills/wellfound-search/cli && $(BUN) install); \
	else \
		echo "Bun not found, skipping search CLI install"; \
	fi
	$(PYTHON) tools/migrate.py

test: pii-check test-python test-bun test-web

pii-check:
	$(PYTHON) tools/check_pii.py

test-python:
	$(PYTEST) tests/

test-bun:
	@if [ -x "$(BUN)" ]; then \
		echo "Running Bun CLI tests (linkedin-search, freehire-search, wellfound-search)..."; \
		export PATH="$$HOME/.bun/bin:$$PATH"; \
		(cd .agents/skills/linkedin-search/cli && $(BUN) test); \
		(cd .agents/skills/freehire-search/cli && $(BUN) test); \
		(cd .agents/skills/wellfound-search/cli && $(BUN) test); \
	else \
		echo "Bun not found, skipping TS CLI tests"; \
	fi

test-web:
	@if [ -x "$(BUN)" ]; then \
		echo "Running Bun harness web tests..."; \
		export PATH="$$HOME/.bun/bin:$$PATH"; \
		$(BUN) test harness/web/tests; \
	else \
		echo "Bun not found, skipping web tests"; \
	fi

lint:
	python3 tools/lint_skills.py
	python3 tools/security_guards.py

dashboard:
	python3 harness/dashboard.py

nightly:
	./bin/nightly.sh

# Documentation site (Starlight) at http://127.0.0.1:4399
docs:
	cd docsite && (test -d node_modules || npm install) && npm run build && npm run preview
