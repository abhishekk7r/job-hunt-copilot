#!/usr/bin/env python3
"""Unified answer bank: import, export, add, approve, retire, and track uses."""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS answers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, answer TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('fact','choice','story','policy','legal')),
  scope TEXT NOT NULL DEFAULT 'global', status TEXT NOT NULL DEFAULT 'approved' CHECK (status IN ('approved','drafted','retired')),
  source TEXT NOT NULL DEFAULT '', uses INTEGER NOT NULL DEFAULT 0, last_used_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS answers_q_scope ON answers(lower(question), scope);
"""


def get_db_path() -> str:
    return os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or get_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(CREATE_TABLE_SQL)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_question(key: str) -> str:
    k = key.strip().lower()
    if k.endswith("_years"):
        skill = k[:-6].replace("_", " ").title()
        return f"Years of {skill} experience"
    if k == "notice_period_days":
        return "Notice period in days"
    if k == "work_authorization":
        return "Authorized to work in country"
    if k == "visa_sponsorship":
        return "Requires visa sponsorship"
    return k.replace("_", " ").capitalize()


def upsert_answer(conn: sqlite3.Connection, question: str, answer: str, kind: str, scope: str = "global", status: str = "approved", source: str = "") -> int:
    q, ans, scope = question.strip(), answer.strip(), (scope.strip().lower() or "global")
    cur = conn.cursor()
    cur.execute("SELECT id, status FROM answers WHERE lower(question) = lower(?) AND scope = ?", (q, scope))
    row, ts = cur.fetchone(), now_iso()
    if row:
        ans_id, ex_status = row["id"], row["status"]
        if ex_status == "approved" and status == "drafted":
            return ans_id
        cur.execute("UPDATE answers SET answer=?, kind=?, status=?, source=CASE WHEN ?!='' THEN ? ELSE source END, updated_at=? WHERE id=?",
                    (ans, kind, status, source, source, ts, ans_id))
        return ans_id
    cur.execute("INSERT INTO answers (question, answer, kind, scope, status, source, uses, created_at, updated_at) VALUES (?,?,?,?,?,?,0,?,?)",
                (q, ans, kind, scope, status, source, ts, ts))
    return cur.lastrowid


def import_all(conn: sqlite3.Connection) -> Dict[str, int]:
    counts = {"screening_qa": 0, "decisions": 0, "stories": 0, "config": 0, "facts": 0}
    cur = conn.cursor()
    # 1. screening_qa
    if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screening_qa'").fetchone():
        for r in cur.execute("SELECT question_key, answer FROM screening_qa").fetchall():
            k, ans = str(r["question_key"]).strip(), str(r["answer"]).strip()
            if k and ans:
                kind = "legal" if any(w in k.lower() for w in ("agree", "terms", "nda", "nondisclosure", "relat")) else "fact"
                upsert_answer(conn, canonical_question(k), ans, kind, scope="global", status="approved", source="screening_qa")
                counts["screening_qa"] += 1
    # 2. decisions (APPROVED / EDITED)
    if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decisions'").fetchone():
        cur.execute("SELECT * FROM decisions WHERE status IN ('APPROVED', 'EDITED')")
        for r in cur.fetchall():
            prop_key = next((k for k in r.keys() if k.startswith("prop")), "")
            ans = (r["final_answer"] or (r[prop_key] if prop_key else "") or "").strip()
            q, comp = (r["question"] or "").strip(), (r["company"] or "").strip().lower()
            if q and ans:
                scope = f"company:{comp}" if comp and comp in q.lower() else "global"
                kind = "legal" if any(w in q.lower() for w in ("disability", "government", "terms", "nondisclosure")) else "choice" if ans.lower() in ("yes", "no", "hybrid", "remote") else "fact"
                upsert_answer(conn, q, ans, kind, scope=scope, status="approved", source=f"decision:{r['id']}")
                counts["decisions"] += 1
    # 3. app_story_answers
    if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_story_answers'").fetchone():
        for r in cur.execute("SELECT question, answer FROM app_story_answers").fetchall():
            q, ans = (r["question"] or "").strip(), (r["answer"] or "").strip()
            if q and ans:
                upsert_answer(conn, q, ans, "story", scope="global", status="approved", source="app_story_answers")
                counts["stories"] += 1
    # 4. config/local.toml [screening]
    for p in (REPO_ROOT / "config" / "local.toml", REPO_ROOT / "config" / "example.toml"):
        if p.exists():
            m = re.search(r"\[screening\](.*?)(\n\[|\Z)", p.read_text(encoding="utf-8"), re.DOTALL)
            if m:
                for k, v in re.findall(r'(\w+)\s*=\s*"([^"]+)"', m.group(1)):
                    upsert_answer(conn, canonical_question(k), v.strip(), "fact", scope="global", status="approved", source="config")
                    counts["config"] += 1
            break
    # 5. applicant_facts (local or example)
    for p in (REPO_ROOT / "config" / "applicant_facts.local.md", REPO_ROOT / "config" / "applicant_facts.example.md"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith("- ") and ":" in line:
                    q, a = line[2:].split(":", 1)
                    if q.strip() and a.strip():
                        upsert_answer(conn, q.strip(), a.strip(), "policy", scope="global", status="approved", source="applicant_facts")
                        counts["facts"] += 1
            break
    conn.commit()
    return counts


def export_markdown(conn: sqlite3.Connection, statuses: Optional[List[str]] = None, company: Optional[str] = None) -> str:
    status_filter = [s.strip().lower() for s in (statuses or ["approved", "drafted"]) if s.strip()]
    cur = conn.cursor()
    comp = company.strip().lower() if company else None
    rows = cur.execute("SELECT id, question, answer, kind, scope, status FROM answers ORDER BY id ASC").fetchall()
    by_kind: Dict[str, List[Any]] = {"fact": [], "choice": [], "story": [], "policy": [], "legal": []}
    for r in rows:
        if r["status"] not in status_filter:
            continue
        scope = r["scope"]
        if scope != "global":
            if not comp or scope != f"company:{comp}":
                continue
        by_kind.setdefault(r["kind"], []).append(r)

    lines = []
    for kind in ("fact", "choice", "story", "policy", "legal"):
        group = by_kind.get(kind, [])
        if not group:
            continue
        lines.append(f"## {kind.capitalize()}")
        for r in group:
            lines.append(f"#{r['id']} [{r['kind']}] {r['question']} -> {r['answer']}")
        lines.append("")
    return "\n".join(lines).strip()


def cmd_approve(conn: sqlite3.Connection, ans_id: int, answer: Optional[str] = None) -> bool:
    cur, ts = conn.cursor(), now_iso()
    sql = "UPDATE answers SET status='approved', answer=?, updated_at=? WHERE id=?" if answer else "UPDATE answers SET status='approved', updated_at=? WHERE id=?"
    params = (answer.strip(), ts, ans_id) if answer else (ts, ans_id)
    cur.execute(sql, params)
    conn.commit()
    return cur.rowcount > 0

def cmd_edit(conn: sqlite3.Connection, ans_id: int, answer: str) -> bool:
    cur, ts = conn.cursor(), now_iso()
    cur.execute("UPDATE answers SET answer=?, updated_at=? WHERE id=?", (answer.strip(), ts, ans_id))
    conn.commit()
    return cur.rowcount > 0

def cmd_retire(conn: sqlite3.Connection, ans_id: int) -> bool:
    cur = conn.cursor()
    cur.execute("UPDATE answers SET status='retired', updated_at=? WHERE id=?", (now_iso(), ans_id))
    conn.commit()
    return cur.rowcount > 0

def cmd_used(conn: sqlite3.Connection, ans_id: int) -> bool:
    cur, ts = conn.cursor(), now_iso()
    cur.execute("UPDATE answers SET uses=uses+1, last_used_at=?, updated_at=? WHERE id=?", (ts, ts, ans_id))
    conn.commit()
    return cur.rowcount > 0

def get_answers(conn: sqlite3.Connection, status: Optional[str] = None) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    if status:
        rows = cur.execute(
            "SELECT id, question, answer, kind, scope, status, source, uses, created_at, updated_at "
            "FROM answers WHERE status=? ORDER BY id DESC",
            (status.strip().lower(),),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, question, answer, kind, scope, status, source, uses, created_at, updated_at "
            "FROM answers ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]

def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Answer Bank manager")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import")
    exp = sub.add_parser("export")
    exp.add_argument("--status", default="approved,drafted")
    exp.add_argument("--company", default=None)
    add_p = sub.add_parser("add")
    add_p.add_argument("--question", required=True)
    add_p.add_argument("--answer", required=True)
    add_p.add_argument("--kind", required=True, choices=["fact", "choice", "story", "policy", "legal"])
    add_p.add_argument("--scope", default="global")
    add_p.add_argument("--status", default="drafted", choices=["approved", "drafted", "retired"])
    add_p.add_argument("--source", default="")
    app = sub.add_parser("approve")
    app.add_argument("id", type=int)
    app.add_argument("--answer", default=None)
    edit_p = sub.add_parser("edit")
    edit_p.add_argument("id", type=int)
    edit_p.add_argument("--answer", required=True)
    sub.add_parser("retire").add_argument("id", type=int)
    sub.add_parser("used").add_argument("id", type=int)

    args = parser.parse_args()
    conn = get_conn()
    try:
        if args.cmd == "import":
            print(f"Imported answers: {import_all(conn)}")
        elif args.cmd == "export":
            st = args.status.split(",") if args.status else None
            print(export_markdown(conn, statuses=st, company=args.company))
        elif args.cmd == "add":
            aid = upsert_answer(conn, args.question, args.answer, args.kind, args.scope, args.status, args.source)
            conn.commit()
            print(f"Saved answer #{aid}")
        elif args.cmd == "approve":
            print("OK" if cmd_approve(conn, args.id, args.answer) else "Not found")
        elif args.cmd == "edit":
            print("OK" if cmd_edit(conn, args.id, args.answer) else "Not found")
        elif args.cmd == "retire":
            print("OK" if cmd_retire(conn, args.id) else "Not found")
        elif args.cmd == "used":
            print("OK" if cmd_used(conn, args.id) else "Not found")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
