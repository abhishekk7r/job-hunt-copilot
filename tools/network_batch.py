#!/usr/bin/env python3
"""Daily networking batch: pick up to 25 people, render notes, track Send decisions.

The batch is a manifest that the agent uses to open one prefilled LinkedIn
connection-note tab per person in the user's own Chrome (Claude in Chrome).
The agent NEVER clicks Send; the user reviews each tab and sends or skips.

Usage:
  python3 tools/network_batch.py build [--limit 25] [--per-company 3] [--date YYYY-MM-DD]
  python3 tools/network_batch.py mark <contact_id|profile_url> PREFILLED|SENT|SKIPPED [--detail TEXT]
  python3 tools/network_batch.py status
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.contacts import is_executive, render_connection_note  # noqa: E402
from harness.config import identity_capsule  # noqa: E402

DAILY_CAP = 25
NOTE_MAX = 300
VALID_MARKS = {"PREFILLED", "SENT", "SKIPPED"}
try:
    BANNED_LINKS_DEFAULT = identity_capsule().get("forbidden_links", [])
except Exception:
    BANNED_LINKS_DEFAULT = []
ACTION = "network_prefill"

CAPS = {
    "search": 15,
    "profile": 40,
    "prefill": 25,
}


def tick(conn: sqlite3.Connection, kind: str, day: Optional[str] = None) -> bool:
    kind = kind.lower().strip()
    if kind not in CAPS:
        raise ValueError(f"Unknown kind {kind!r}; must be one of {list(CAPS.keys())}")
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cap = CAPS[kind]
    bkey = f"budget:network:{kind}:{day}"
    row = conn.execute("SELECT val FROM budgets WHERE key = ?", (bkey,)).fetchone()
    current = int(row[0]) if row else 0
    if current >= cap:
        print("CAP")
        return False
    new_val = current + 1
    conn.execute(
        "INSERT INTO budgets (key, val) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET val = ?",
        (bkey, new_val, new_val),
    )
    conn.commit()
    print(f"OK {new_val}/{cap}")
    return True


def get_db_path() -> str:
    return os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or get_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def kill_switch_on(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute('SELECT "on" FROM kill_switch WHERE id = 1').fetchone()
    except sqlite3.Error:
        return False
    return bool(row and row["on"])


def used_today(conn: sqlite3.Connection, day: str) -> int:
    """Notes already prefilled today (a SENT/SKIPPED mark does not free a slot)."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT target) FROM action_log WHERE action = ? AND result = 'PREFILLED' AND ts LIKE ?",
        (ACTION, f"{day}%"),
    ).fetchone()
    return int(row[0])


def applied_jobs_by_company(conn: sqlite3.Connection) -> Dict[str, str]:
    """company (lower) -> role for jobs that are really APPLIED."""
    out: Dict[str, str] = {}
    for r in conn.execute("SELECT company, role FROM jobs WHERE status = 'APPLIED'"):
        out.setdefault(r["company"].strip().lower(), r["role"])
    return out


def validate_note(note: str, banned: List[str]) -> Optional[str]:
    if not note.strip():
        return "empty note"
    if len(note) > NOTE_MAX:
        return f"note is {len(note)} chars (> {NOTE_MAX})"
    low = note.lower()
    for b in banned:
        if b.lower() in low:
            return f"banned link {b}"
    return None


def build_batch(
    conn: sqlite3.Connection,
    limit: int = DAILY_CAP,
    per_company: int = 3,
    day: Optional[str] = None,
    banned_links: Optional[List[str]] = None,
) -> Dict[str, Any]:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    banned = banned_links or BANNED_LINKS_DEFAULT

    if kill_switch_on(conn):
        return {"date": day, "halted": "kill switch is ON", "items": [], "skipped": []}

    remaining = max(0, min(limit, DAILY_CAP) - used_today(conn, day))
    applied = applied_jobs_by_company(conn)

    rows = conn.execute(
        "SELECT * FROM contacts WHERE status = 'PROPOSED' ORDER BY score DESC, id"
    ).fetchall()

    # Warm companies (an APPLIED job exists) first, then by score.
    def sort_key(r: sqlite3.Row):
        warm = 1 if r["current_company"].strip().lower() in applied else 0
        return (-warm, -float(r["score"] or 0), r["id"])

    items: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    per_co: Dict[str, int] = {}
    seen_urls = set()

    for r in sorted(rows, key=sort_key):
        if len(items) >= remaining:
            break
        company = r["current_company"].strip()
        ckey = company.lower()
        url = r["profile_url"]

        if url in seen_urls:
            skipped.append({"id": r["id"], "name": r["name"], "reason": "duplicate profile"})
            continue
        if is_executive(r["title"]):
            skipped.append({"id": r["id"], "name": r["name"], "reason": "too senior (executive)"})
            continue
        if per_co.get(ckey, 0) >= per_company:
            skipped.append({"id": r["id"], "name": r["name"], "reason": f"company cap {per_company}"})
            continue

        role = applied.get(ckey, "")
        is_applied = bool(role)
        # Re-render at batch time so "I've applied" always reflects the live job status.
        note = render_connection_note(
            {"name": r["name"], "current_company": company},
            job_applied=is_applied, role=role, company=company,
        )
        problem = validate_note(note, banned)
        if problem:
            skipped.append({"id": r["id"], "name": r["name"], "reason": problem})
            continue

        seen_urls.add(url)
        per_co[ckey] = per_co.get(ckey, 0) + 1
        items.append({
            "contact_id": r["id"],
            "name": r["name"],
            "title": r["title"],
            "company": company,
            "kind": r["kind"],
            "degree": r["connection_degree"],
            "score": r["score"],
            "warm_company": is_applied,
            "outreach_kind": "job_specific" if is_applied else "networking",
            "profile_url": url,
            "note_text": note,
            "note_chars": len(note),
        })

    return {
        "date": day,
        "cap": DAILY_CAP,
        "already_prefilled_today": used_today(conn, day),
        "items": items,
        "skipped": skipped,
        "rules": [
            "Open each profile in the user's own Chrome (Claude in Chrome only; never bot browsers or the linkedin MCP).",
            "Click Connect -> Add a note, type note_text, then STOP. Never click Send.",
            "Stop the whole batch on CAPTCHA, login challenge, rate-limit message or unusual page.",
            "After prefilling a tab run: tools/network_batch.py mark <contact_id> PREFILLED",
        ],
    }


def write_manifest(batch: Dict[str, Any], out_dir: Optional[Path] = None) -> Dict[str, str]:
    out_dir = out_dir or (REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / f"network-batch-{batch['date']}.json"
    mpath = out_dir / f"network-batch-{batch['date']}.md"
    jpath.write_text(json.dumps(batch, indent=2), encoding="utf-8")

    lines = [f"# Networking batch {batch['date']}", ""]
    if batch.get("halted"):
        lines.append(f"HALTED: {batch['halted']}")
    lines.append(f"{len(batch['items'])} people queued (cap {batch.get('cap', DAILY_CAP)}/day). Tabs are prefilled, not sent.")
    lines.append("")
    for i, it in enumerate(batch["items"], 1):
        warm = " [applied here]" if it["warm_company"] else ""
        lines += [
            f"{i}. {it['name']} - {it['title']} @ {it['company']}{warm} ({it['kind']}, score {it['score']})",
            f"   {it['profile_url']}",
            f"   {it['note_text']}",
            "",
        ]
    if batch["skipped"]:
        lines.append("Skipped:")
        lines += [f"- {s['name']}: {s['reason']}" for s in batch["skipped"]]
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(jpath), "md": str(mpath)}


def mark(conn: sqlite3.Connection, ref: str, status: str, detail: str = "") -> Dict[str, Any]:
    status = status.upper()
    if status not in VALID_MARKS:
        raise ValueError(f"status must be one of {sorted(VALID_MARKS)}")
    if ref.isdigit():
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (int(ref),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM contacts WHERE profile_url = ?", (ref,)).fetchone()
    if not row:
        raise LookupError(f"no contact for {ref}")
    if row["status"] == "SENT" and status != "SENT":
        raise ValueError("contact already SENT; refusing to downgrade")

    conn.execute("UPDATE contacts SET status = ? WHERE id = ?", (status, row["id"]))
    if status == "PREFILLED":
        day = _utc_now()[:10]
        conn.execute(
            "INSERT INTO budgets (key, val) VALUES (?, 1) ON CONFLICT(key) DO UPDATE SET val = val + 1",
            (f"budget:network:prefill:{day}",),
        )
    conn.execute(
        "INSERT INTO action_log (run_id, ts, actor, action, target, result, detail) VALUES (?,?,?,?,?,?,?)",
        (f"network-{_utc_now()[:10]}", _utc_now(), "claude", ACTION, str(row["id"]), status, detail),
    )
    conn.commit()
    return {"contact_id": row["id"], "name": row["name"], "status": status}


def status_summary(conn: sqlite3.Connection, day: Optional[str] = None) -> Dict[str, Any]:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM contacts GROUP BY status")}
    ticks = {}
    for k in CAPS:
        row = conn.execute("SELECT val FROM budgets WHERE key = ?", (f"budget:network:{k}:{day}",)).fetchone()
        ticks[k] = {"used": int(row[0]) if row else 0, "cap": CAPS[k]}
    return {"date": day, "used_today": used_today(conn, day), "cap": DAILY_CAP, "by_status": counts, "budgets": ticks}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--limit", type=int, default=DAILY_CAP)
    b.add_argument("--per-company", type=int, default=3)
    b.add_argument("--date")
    m = sub.add_parser("mark")
    m.add_argument("ref")
    m.add_argument("status")
    m.add_argument("--detail", default="")
    t = sub.add_parser("tick")
    t.add_argument("kind", choices=list(CAPS.keys()))
    t.add_argument("--day", default=None)
    sub.add_parser("status")
    args = ap.parse_args(argv)

    conn = _connect()
    try:
        if args.cmd == "build":
            batch = build_batch(conn, args.limit, args.per_company, args.date)
            paths = write_manifest(batch)
            print(json.dumps({"queued": len(batch["items"]), "skipped": len(batch["skipped"]),
                              "halted": batch.get("halted"), **paths}, indent=2))
        elif args.cmd == "mark":
            print(json.dumps(mark(conn, args.ref, args.status, args.detail)))
        elif args.cmd == "tick":
            ok = tick(conn, args.kind, day=args.day)
            return 0 if ok else 0
        else:
            print(json.dumps(status_summary(conn), indent=2))
    except (ValueError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
