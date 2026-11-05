"""Test privacy guards, check_pii.py, and personal data exclusion."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PII_SCRIPT = REPO_ROOT / "tools" / "check_pii.py"


def test_check_pii_missing_pattern_file(tmp_path):
    """When pattern file does not exist, check_pii prints a notice and exits 0."""
    missing_file = tmp_path / "non_existent_patterns.txt"
    res = subprocess.run(
        [sys.executable, str(PII_SCRIPT), "--patterns", str(missing_file), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "Notice: PII pattern file not found" in res.stdout


def test_check_pii_no_hits(tmp_path):
    """When scanned files contain no blocklist patterns, check_pii exits 0."""
    pat_file = tmp_path / "patterns.txt"
    pat_file.write_text("FORBIDDEN_STRING_12345\nANOTHER_SECRET\n", encoding="utf-8")
    
    code_dir = tmp_path / "repo"
    code_dir.mkdir()
    (code_dir / "clean.py").write_text("print('hello world')\n", encoding="utf-8")
    
    res = subprocess.run(
        [sys.executable, str(PII_SCRIPT), "--patterns", str(pat_file), "--root", str(code_dir)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_check_pii_detects_hit_and_masks_pattern(tmp_path):
    """When a hit is found, check_pii exits 1, prints file:line pattern#n, and never prints the pattern text."""
    secret = "SUPER_SECRET_TOKEN_XYZ"
    pat_file = tmp_path / "patterns.txt"
    pat_file.write_text(f"DUMMY_PAT\n{secret}\n", encoding="utf-8")
    
    code_dir = tmp_path / "repo"
    code_dir.mkdir()
    (code_dir / "bad.py").write_text(f"# comment\ntoken = '{secret}'\n", encoding="utf-8")
    
    res = subprocess.run(
        [sys.executable, str(PII_SCRIPT), "--patterns", str(pat_file), "--root", str(code_dir)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "bad.py:2 pattern#2" in res.stdout
    # Pattern text must NEVER be printed
    assert secret not in res.stdout
    assert secret not in res.stderr


def test_banned_shortener_only_in_configs_and_tests():
    """Verify shorturl.at appears only in banned-links lists or tests."""
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
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "node_modules", "__pycache__"}]
            for file in files:
                if file.endswith((".pyc", ".pyo")):
                    continue
                rel = os.path.relpath(os.path.join(root, file), REPO_ROOT)
                tracked_files.append(rel)

    allowed_files = {
        "tests/test_privacy.py",
        "config/example.toml",
        "harness/config.py",
        "harness/answers.py",
        "harness/outreach.py",
        ".claude/commands/fill.md",
        ".claude/commands/outreach.md",
        ".agents/skills/fill/SKILL.md",
        ".agents/skills/outreach/SKILL.md",
    }

    violations = []
    for rel_path in tracked_files:
        if rel_path in allowed_files or rel_path.startswith("tests/"):
            continue
        p = REPO_ROOT / rel_path
        if not p.is_file():
            continue
        try:
            content = p.read_text(errors="ignore")
        except Exception:
            continue
        if "shorturl.at" in content:
            violations.append(rel_path)

    assert not violations, f"Banned link 'shorturl.at' found in unexpected files: {violations}"
