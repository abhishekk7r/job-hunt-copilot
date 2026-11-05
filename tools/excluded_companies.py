"""Companies the owner never wants jobs from (git-ignored list, one name per line)."""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path() -> Path:
    return Path(os.environ.get("EXCLUDED_COMPANIES_FILE") or ROOT / "config" / "excluded_companies.local.txt")


def load() -> list[str]:
    try:
        lines = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [l.strip().lower() for l in lines if l.strip() and not l.lstrip().startswith("#")]


def is_excluded(company: str, names: list[str] | None = None) -> bool:
    names = load() if names is None else names
    c = re.sub(r"\s+", " ", (company or "").lower())
    for n in names:
        if re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", c):
            return True
    return False
