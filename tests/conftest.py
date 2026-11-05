"""Global pytest fixtures."""

import os
import sqlite3
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Provides a fresh migrated temp SQLite database isolated from production."""
    db_path = str(tmp_path / "temp_harness.db")
    monkeypatch.setenv("HARNESS_DB", db_path)

    schema_file = REPO_ROOT / "schema.sql"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_file.read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version = 1;")
    conn.commit()
    conn.close()

    yield db_path
