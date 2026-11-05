"""Tests for search profile example format, required headings, and git-ignore rules (T6)."""

import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_FILE = REPO_ROOT / "config" / "search_profile.example.md"
LOCAL_FILE = REPO_ROOT / "config" / "search_profile.local.md"

REQUIRED_HEADINGS = [
    "## Who",
    "## What the role must be (judge by the job description, never by the title)",
    "## Seniority by experience asked, not by title",
    "## Location",
    "## Compensation (only when the posting states it)",
    "## Scoring dimensions (same four as rank_state.py; each 0 to 100, from the JD text only)",
    "## Notes rules",
]

BANNED_STRINGS = [
    "shorturl.at",
    "15 days",
]


def test_example_profile_exists_and_has_required_headings():
    assert EXAMPLE_FILE.exists(), "config/search_profile.example.md missing"
    text = EXAMPLE_FILE.read_text(encoding="utf-8")
    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"Missing required heading {heading!r} in search_profile.example.md"


def test_example_profile_contains_no_banned_strings():
    text = EXAMPLE_FILE.read_text(encoding="utf-8")
    for banned in BANNED_STRINGS:
        assert banned not in text, f"Banned string {banned!r} in search_profile.example.md"


def test_local_profile_is_git_ignored():
    res = subprocess.run(
        ["git", "check-ignore", "-v", "config/search_profile.local.md"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    if res.returncode == 128:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "search_profile.local.md" in gitignore or "*.local.*" in gitignore, "config/search_profile.local.md is not git-ignored!"
        return
    assert res.returncode == 0, "config/search_profile.local.md is not git-ignored!"
    assert "config/search_profile.local.md" in res.stdout
