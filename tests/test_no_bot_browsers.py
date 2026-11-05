"""Test that bot-driven browser automation libraries are strictly prohibited in dependencies and scripts."""

import os
import subprocess
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN = ["playwright", "patchright", "selenium", "puppeteer"]

CODE_AND_DEP_EXTENSIONS = {".py", ".sh", ".ts", ".js", ".json", ".toml", ".yml", ".yaml"}


def test_no_bot_browsers_in_dependencies_and_scripts():
    """Verify no forbidden browser libraries are imported or listed as dependencies or in scripts."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True
        )
        tracked_files = [f for f in result.stdout.splitlines() if f]
    except Exception:
        tracked_files = []
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "node_modules"}]
            for file in files:
                rel = os.path.relpath(os.path.join(root, file), REPO_ROOT)
                tracked_files.append(rel)

    violations = []
    for rel_path in tracked_files:
        if rel_path in ("tests/test_no_bot_browsers.py",):
            continue

        p = Path(rel_path)
        if p.suffix not in CODE_AND_DEP_EXTENSIONS and "bin/" not in rel_path and not rel_path.startswith("tools/"):
            continue

        file_path = REPO_ROOT / rel_path
        if not file_path.is_file():
            continue

        try:
            content = file_path.read_text(errors="ignore").lower()
        except Exception:
            continue

        for token in FORBIDDEN:
            if token in content:
                violations.append(f"{rel_path}: contains forbidden token '{token}'")

    assert not violations, f"Forbidden browser automation tokens found in dependencies or scripts:\n" + "\n".join(violations)
