#!/usr/bin/env python3
"""PII guard: scan repository files for literal blocklist patterns."""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATTERNS_PATH = Path.home() / ".config" / "job-hunt-copilot" / "pii_patterns.txt"
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def get_pattern_file(cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).expanduser().resolve()
    env_file = os.environ.get("JHC_PII_FILE")
    if env_file:
        return Path(env_file).expanduser().resolve()
    return DEFAULT_PATTERNS_PATH.expanduser().resolve()


def load_patterns(pattern_path: Path) -> List[Tuple[int, str]]:
    if not pattern_path.is_file():
        return []
    patterns: List[Tuple[int, str]] = []
    with open(pattern_path, "r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f, start=1):
            cleaned = line.rstrip("\r\n")
            if cleaned:
                patterns.append((idx, cleaned))
    return patterns


def get_files_to_scan(root: Path) -> List[Path]:
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        files = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            p = root / line
            if p.is_file():
                # Ensure it is not in skip dirs
                if not any(part in SKIP_DIRS for part in p.parts):
                    files.append(p)
        if files:
            return files
    except Exception:
        pass

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            if p.is_file():
                files.append(p)
    return sorted(files)


def scan_file(file_path: Path, root: Path, patterns: List[Tuple[int, str]]) -> List[str]:
    hits: List[str] = []
    rel_path = file_path.relative_to(root).as_posix()
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, start=1):
                for pat_idx, pat in patterns:
                    if pat in line:
                        hits.append(f"{rel_path}:{line_no} pattern#{pat_idx}")
    except (OSError, UnicodeError):
        pass
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan files for PII patterns.")
    parser.add_argument("--patterns", "-p", help="Path to PII patterns file", default=None)
    parser.add_argument("--root", "-r", help="Repository root directory", default=str(REPO_ROOT))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    pattern_file = get_pattern_file(args.patterns)

    if not pattern_file.is_file():
        print(f"Notice: PII pattern file not found at {pattern_file}; skipping check.")
        return 0

    patterns = load_patterns(pattern_file)
    if not patterns:
        print(f"Notice: No patterns loaded from {pattern_file}; skipping check.")
        return 0

    files = get_files_to_scan(root)
    total_hits = 0

    for file_path in files:
        if file_path.resolve() == pattern_file.resolve():
            continue
        hits = scan_file(file_path, root, patterns)
        for hit in hits:
            print(hit)
            total_hits += 1

    if total_hits > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
