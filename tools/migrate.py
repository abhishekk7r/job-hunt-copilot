#!/usr/bin/env python3
"""Run database initialization and migrations."""
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def migrate(db_path: str = None) -> None:
    db = db_path or os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))
    schema_path = REPO_ROOT / "schema.sql"
    conn = sqlite3.connect(db)
    if schema_path.exists():
        conn.executescript(schema_path.read_text(encoding="utf-8"))

    migrations_dir = REPO_ROOT / "migrations"
    if migrations_dir.exists():
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            conn.executescript(sql_file.read_text(encoding="utf-8"))

    conn.commit()
    conn.close()
    print(f"Database migrated successfully at {db}")


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("Usage: python3 tools/migrate.py [DB_PATH]")
        print("Initializes harness.db schema and applies SQL migrations.")
        sys.exit(0)
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    migrate(db_arg)
