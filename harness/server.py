#!/usr/bin/env python3
"""Job Harness FastMCP Server.

Coordinates job applications, resource locks, session budgeting, answers bank,
and deterministic outreach drafting.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from mcp.server.fastmcp import FastMCP
from harness.config import identity_capsule
from harness.outreach import render_outreach, determine_channel, create_gmail_draft
from harness.answers import match_screening_answer
from tools.job_key import make_key

# Log strictly to stderr so stdout JSON-RPC is never corrupted
def log_err(msg: str):
    sys.stderr.write(f"[HARNESS] {msg}\n")
    sys.stderr.flush()

mcp = FastMCP("JobHarness")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_CALLS_PER_SESSION = 20

ALLOWED_STATUSES = {
    "TO_APPLY",
    "APPLIED",
    "BLOCKED_USER",
    "COMPANY_SITE_ONLY",
    "REJECTED",
    "RANKED_OUT",
    "HALTED",
    "CONTACTED",
}

def get_db_path() -> str:
    return os.environ.get("HARNESS_DB", os.path.join(BASE_DIR, "harness.db"))

def get_conn():
    conn = sqlite3.connect(get_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def check_kill_switch(conn) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute('INSERT OR IGNORE INTO kill_switch (id, "on", reason, ts) VALUES (1, 0, "", "");')
    cur.execute('SELECT "on", reason FROM kill_switch WHERE id = 1;')
    row = cur.fetchone()
    if row and row["on"]:
        return {
            "HARD_STOP": True,
            "reason": f"Kill switch is active: {row['reason'] or 'Manual halt requested'}"
        }
    return None

def check_and_increment_budget(conn, session_id: str = "") -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    if not session_id:
        cur.execute("SELECT val FROM budgets WHERE key = 'current_session_id'")
        row = cur.fetchone()
        session_id = str(row["val"]) if row else "default_session"

    key = f"session_calls:{session_id}"
    cur.execute("SELECT val FROM budgets WHERE key = ?", (key,))
    row = cur.fetchone()
    calls = (row["val"] if row else 0) + 1
    cur.execute("INSERT OR REPLACE INTO budgets (key, val) VALUES (?, ?)", (key, calls))
    conn.commit()

    if calls > MAX_CALLS_PER_SESSION:
        return {
            "HARD_STOP": True,
            "reason": f"MAX_CALLS_PER_SESSION ({MAX_CALLS_PER_SESSION}) reached to keep context under 35%.",
            "mandatory_action": "Release CHROME_BROWSER lock and output the Mobile App Summary Card immediately."
        }
    return None

def clean_expired_locks(conn):
    now_str = datetime.utcnow().isoformat()
    conn.execute("DELETE FROM agent_locks WHERE expires_at < ?", (now_str,))
    conn.commit()

def init_database():
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    conn = get_conn()
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.commit()
    conn.close()

init_database()

@mcp.tool()
def start_session_with_capsule(agent_name: str, session_id: str = "") -> str:
    """
    MUST BE CALLED FIRST ON TURN 1 OF EVERY SESSION.
    Returns the complete Identity Capsule, peer agent lock state, and queue counts.
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    agent = agent_name.upper()
    now_str = datetime.utcnow().isoformat()

    if not session_id:
        session_id = f"{agent}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    # Record active session in budgets
    conn.execute("INSERT OR REPLACE INTO budgets (key, val) VALUES ('current_session_id', ?)", (session_id,))
    conn.execute(f"INSERT OR IGNORE INTO budgets (key, val) VALUES ('session_calls:{session_id}', 0)")

    budget_check = check_and_increment_budget(conn, session_id)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    clean_expired_locks(conn)
    conn.execute("""
        INSERT OR REPLACE INTO agent_heartbeats (agent_name, status, active_resource, last_seen)
        VALUES (?, 'ACTIVE', 'SESSION_INIT', ?)
    """, (agent, now_str))
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT * FROM agent_locks")
    active_locks = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM agent_heartbeats")
    heartbeats = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT approval_status, COUNT(*) as cnt FROM outreach_queue GROUP BY approval_status")
    outreach_counts = {r["approval_status"]: r["cnt"] for r in cur.fetchall()}

    cur.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status")
    job_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

    cur.execute("SELECT val FROM budgets WHERE key = 'inmail_credits'")
    row = cur.fetchone()
    inmail_left = row["val"] if row else 0

    cur.execute("SELECT id, company, role, recruiter_name, channel, rendered_message, char_count FROM outreach_queue WHERE approval_status = 'PENDING_MOBILE_REVIEW'")
    pending_reviews = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT id, job_id, company, role, recruiter_name, recruiter_linkedin, channel, rendered_message FROM outreach_queue WHERE approval_status = 'APPROVED_TO_SEND'")
    approved_to_send = [dict(r) for r in cur.fetchall()]

    cur.execute(f"SELECT val FROM budgets WHERE key = 'session_calls:{session_id}'")
    calls_used = cur.fetchone()["val"]

    capsule = identity_capsule()
    conn.close()

    return json.dumps({
        "session_id": session_id,
        "identity_capsule": capsule,
        "inmail_credits_remaining": inmail_left,
        "peer_heartbeats": heartbeats,
        "active_locks": active_locks,
        "job_queue_summary": job_counts,
        "outreach_queue_summary": outreach_counts,
        "approved_messages_ready_to_send_now": approved_to_send,
        "drafts_awaiting_mobile_approval": pending_reviews,
        "session_calls_used": calls_used,
        "session_calls_limit": MAX_CALLS_PER_SESSION
    }, indent=2)

@mcp.tool()
def acquire_lock(resource_id: str, agent_name: str, task_description: str, ttl_minutes: int = 12) -> str:
    """
    Acquires or renews an exclusive lock on a resource.
    If locked by another agent, returns LOCKED_BY_PEER.
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    clean_expired_locks(conn)
    cur = conn.cursor()
    agent = agent_name.upper()

    cur.execute("SELECT * FROM agent_locks WHERE resource_id = ?", (resource_id,))
    existing = cur.fetchone()
    if existing and existing["locked_by"] != agent:
        conn.close()
        return json.dumps({
            "lock_acquired": False,
            "status": "LOCKED_BY_PEER",
            "resource_id": resource_id,
            "locked_by": existing["locked_by"],
            "peer_task": existing["task_description"],
            "expires_at": existing["expires_at"]
        })

    now = datetime.utcnow()
    expires = now + timedelta(minutes=ttl_minutes)
    conn.execute("""
        INSERT OR REPLACE INTO agent_locks (resource_id, locked_by, task_description, locked_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, (resource_id, agent, task_description, now.isoformat(), expires.isoformat()))
    conn.execute("""
        INSERT OR REPLACE INTO agent_heartbeats (agent_name, status, active_resource, last_seen)
        VALUES (?, 'WORKING', ?, ?)
    """, (agent, resource_id, now.isoformat()))
    conn.commit()
    conn.close()
    return json.dumps({
        "lock_acquired": True,
        "resource_id": resource_id,
        "owner": agent,
        "expires_at": expires.isoformat()
    })

@mcp.tool()
def release_lock(resource_id: str, agent_name: str) -> str:
    """Releases a lock held by agent_name."""
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    agent = agent_name.upper()
    conn.execute("DELETE FROM agent_locks WHERE resource_id = ? AND locked_by = ?", (resource_id, agent))
    conn.execute("""
        INSERT OR REPLACE INTO agent_heartbeats (agent_name, status, active_resource, last_seen)
        VALUES (?, 'IDLE', '', ?)
    """, (agent, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return json.dumps({"released": True, "resource_id": resource_id, "agent": agent})

@mcp.tool()
def add_sourced_job(
    company: str,
    role: str,
    job_url: str,
    platform: str,
    tier: int = 2,
    salary_lpa: int = 25,
    stack_keywords: str = "Java, Spring Boot",
    job_id_ext: str = "N/A"
) -> str:
    """
    Validates a newly sourced job against deterministic filters and stores it as TO_APPLY.
    Stores salary_lpa and stack_keywords (Bug 1 fix).
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    capsule = identity_capsule()
    min_lpa = capsule.get("min_ctc_lpa", 22)
    if salary_lpa < min_lpa:
        conn.close()
        return json.dumps({"added": False, "reason": f"Rejected: Salary {salary_lpa} LPA is below floor ({min_lpa} LPA)."})

    lower_stack = (stack_keywords + " " + role).lower()
    excluded = capsule.get("excluded_stack", ["android", "flask", "ios", "react-only"])
    for bad in excluded:
        if bad.lower() in lower_stack:
            conn.close()
            return json.dumps({"added": False, "reason": f"Rejected: Contains excluded stack '{bad}'."})

    now_str = datetime.utcnow().isoformat()
    s_key = make_key(company.strip(), role.strip(), job_url.strip())

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO jobs (
                company, role, job_url, job_id_ext, platform, tier, status,
                salary_lpa, stack_keywords, source, source_key, first_seen, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'TO_APPLY', ?, ?, ?, ?, ?, ?)
        """, (
            company.strip(), role.strip(), job_url.strip(), job_id_ext.strip(),
            platform.strip(), tier, salary_lpa, stack_keywords.strip(),
            platform.strip(), s_key, now_str, now_str
        ))
        job_id = cur.lastrowid
        conn.commit()
        conn.close()
        return json.dumps({"added": True, "job_id": job_id, "source_key": s_key, "status": "TO_APPLY"})
    except sqlite3.IntegrityError:
        conn.close()
        return json.dumps({"added": False, "reason": "Duplicate job_url or source_key already exists in database."})

@mcp.tool()
def claim_next_job_for_claude() -> str:
    """
    Fetches and locks the single next unlocked job (APPLIED needing recruiter first, then TO_APPLY).
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    clean_expired_locks(conn)
    cur = conn.cursor()

    cur.execute("SELECT resource_id FROM agent_locks WHERE resource_id LIKE 'JOB_%'")
    locked_job_ids = [int(r["resource_id"].split("_")[1]) for r in cur.fetchall() if r["resource_id"].split("_")[1].isdigit()]

    placeholders = ",".join(["?"] * len(locked_job_ids)) if locked_job_ids else "0"
    query = f"""
        SELECT * FROM jobs
        WHERE status IN ('APPLIED', 'TO_APPLY')
        AND id NOT IN ({placeholders})
        ORDER BY CASE status WHEN 'APPLIED' THEN 1 WHEN 'TO_APPLY' THEN 2 END, tier ASC, id ASC
        LIMIT 1
    """
    cur.execute(query, locked_job_ids if locked_job_ids else [])
    job = cur.fetchone()

    if not job:
        conn.close()
        return json.dumps({"status": "NO_UNLOCKED_JOBS", "directive": "Sweep portals for new jobs or finish session."})

    job_dict = dict(job)
    res_id = f"JOB_{job_dict['id']}"
    now = datetime.utcnow()
    expires = now + timedelta(minutes=12)
    conn.execute("""
        INSERT OR REPLACE INTO agent_locks (resource_id, locked_by, task_description, locked_at, expires_at)
        VALUES (?, 'CLAUDE', ?, ?, ?)
    """, (res_id, f"Processing {job_dict['company']} ({job_dict['status']})", now.isoformat(), expires.isoformat()))
    conn.commit()

    capsule = identity_capsule()
    conn.close()

    next_step = "FIND_RECRUITER_AND_DRAFT" if job_dict["status"] == "APPLIED" else "FILL_APPLICATION_IN_CHROME"
    return json.dumps({
        "locked_resource": res_id,
        "required_action": next_step,
        "job": job_dict,
        "identity_capsule": capsule
    }, indent=2)

@mcp.tool()
def update_application_state(job_id: int, new_status: str, blocker_note: str = "") -> str:
    """
    Updates job status after portal attempt.
    Allowed new_status values: 'APPLIED', 'BLOCKED_USER', 'COMPANY_SITE_ONLY', 'REJECTED', 'RANKED_OUT', 'HALTED'
    Validates status strictly (Bug 7 fix).
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    if new_status not in ALLOWED_STATUSES:
        conn.close()
        return json.dumps({
            "updated": False,
            "error": f"Invalid status '{new_status}'. Allowed statuses: {sorted(list(ALLOWED_STATUSES))}"
        })

    cur = conn.cursor()
    cur.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return json.dumps({"updated": False, "error": f"Job ID {job_id} not found."})

    current_status = row["status"]
    if current_status == "APPLIED" and new_status != "APPLIED":
        conn.close()
        return json.dumps({
            "updated": False,
            "error": f"Cannot downgrade job {job_id} from APPLIED to '{new_status}'."
        })

    today = datetime.utcnow().strftime("%Y-%m-%d") if new_status == "APPLIED" else ""
    now_str = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE jobs
        SET status = ?, blocker_note = ?, date_applied = CASE WHEN ? != '' THEN ? ELSE date_applied END,
            notion_synced = 0, updated_at = ?
        WHERE id = ?
    """, (new_status, blocker_note, today, today, now_str, job_id))

    if new_status != "APPLIED":
        conn.execute("DELETE FROM agent_locks WHERE resource_id = ?", (f"JOB_{job_id}",))
    conn.commit()
    conn.close()
    return json.dumps({"updated": True, "job_id": job_id, "new_status": new_status})

@mcp.tool()
def draft_outreach_for_mobile_review(
    job_id: int,
    recruiter_name: str,
    recruiter_title: str,
    recruiter_linkedin: str,
    connection_degree: int,
    custom_opener: str = "",
    channel_override: str = "",
    recruiter_email: str = ""
) -> str:
    """
    Deterministically formats outreach message using templates in config/templates/,
    enforces <=300 chars for Connection Notes, honors custom_opener (Bug 2 fix),
    and does NOT overwrite jobs.status (Bug 3 fix: sets outreach_state='DRAFTED').
    Supports LinkedIn DM, InMail, Connection Note, and Email (creates Gmail draft).
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job = cur.fetchone()
    if not job:
        conn.close()
        return json.dumps({"error": f"Job ID {job_id} not found."})

    cur.execute("SELECT val FROM budgets WHERE key = 'inmail_credits'")
    row = cur.fetchone()
    inmail_credits = row["val"] if row else 0

    capsule = identity_capsule()
    job_dict = dict(job)
    contact_dict = {
        "name": recruiter_name,
        "title": recruiter_title,
        "linkedin_url": recruiter_linkedin,
        "email": recruiter_email
    }

    if channel_override:
        channel = channel_override
    else:
        channel = determine_channel(
            connection_degree=connection_degree,
            tier=job_dict.get("tier", 1),
            inmail_credits=inmail_credits,
            has_email=bool(recruiter_email)
        )

    outreach_result = render_outreach(
        channel=channel,
        job=job_dict,
        contact=contact_dict,
        capsule=capsule,
        custom_opener=custom_opener,
        inmail_credits=inmail_credits
    )
    msg = outreach_result["body"]
    channel = outreach_result["channel"]

    # If Email, generate a Gmail draft file (never sends!)
    draft_info = None
    if channel == "Email" and recruiter_email:
        draft_info = create_gmail_draft(
            to_email=recruiter_email,
            subject=outreach_result.get("subject", f"Application for {job_dict.get('role')}"),
            body=msg
        )

    now_str = datetime.utcnow().isoformat()

    # BUG 3 FIX: Do NOT overwrite jobs.status; set outreach_state = 'DRAFTED'
    cur.execute("""
        UPDATE jobs
        SET outreach_state = 'DRAFTED', last_status_before_outreach = status,
            recruiter_name = ?, recruiter_title = ?, recruiter_linkedin = ?,
            connection_degree = ?, notion_synced = 0, updated_at = ?
        WHERE id = ?
    """, (recruiter_name, recruiter_title, recruiter_linkedin, connection_degree, now_str, job_id))

    cur.execute("""
        INSERT INTO outreach_queue (job_id, company, role, recruiter_name, recruiter_linkedin, channel, rendered_message, char_count, approval_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_MOBILE_REVIEW')
    """, (job_id, job["company"], job["role"], recruiter_name, recruiter_linkedin, channel, msg, len(msg)))
    queue_id = cur.lastrowid

    conn.execute("DELETE FROM agent_locks WHERE resource_id = ?", (f"JOB_{job_id}",))
    conn.commit()
    conn.close()

    resp = {
        "queued_for_mobile_review": True,
        "queue_id": queue_id,
        "job_id": job_id,
        "channel": channel,
        "char_count": len(msg),
        "rendered_message": msg
    }
    if draft_info:
        resp["gmail_draft"] = draft_info

    return json.dumps(resp, indent=2)

@mcp.tool()
def process_mobile_approvals(approve_all: bool = False, approve_queue_ids: list[int] = [], skip_queue_ids: list[int] = []) -> str:
    """
    Called when the user replies 'Approve all' or 'Approve 1, 2' from the Claude Mobile App.
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    cur = conn.cursor()
    if approve_all:
        cur.execute("UPDATE outreach_queue SET approval_status = 'APPROVED_TO_SEND' WHERE approval_status = 'PENDING_MOBILE_REVIEW'")
    elif approve_queue_ids:
        placeholders = ",".join(["?"] * len(approve_queue_ids))
        cur.execute(f"UPDATE outreach_queue SET approval_status = 'APPROVED_TO_SEND' WHERE id IN ({placeholders})", approve_queue_ids)

    if skip_queue_ids:
        placeholders = ",".join(["?"] * len(skip_queue_ids))
        cur.execute(f"UPDATE outreach_queue SET approval_status = 'SKIPPED_BY_USER' WHERE id IN ({placeholders})", skip_queue_ids)

    conn.commit()
    cur.execute("SELECT id, job_id, company, role, recruiter_name, recruiter_linkedin, channel, rendered_message FROM outreach_queue WHERE approval_status = 'APPROVED_TO_SEND'")
    ready = [dict(r) for r in cur.fetchall()]
    conn.close()
    return json.dumps({"approved_items_to_send_now": ready}, indent=2)

@mcp.tool()
def mark_outreach_sent(queue_id: int, sent_from_account: str = "LinkedIn") -> str:
    """
    Marks an approved outreach item as SENT.
    Updates jobs.outreach_state = 'SENT'.
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    cur = conn.cursor()
    cur.execute("SELECT * FROM outreach_queue WHERE id = ?", (queue_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return json.dumps({"error": f"Queue ID {queue_id} not found."})

    now = datetime.utcnow()
    followup = (now + timedelta(days=6)).strftime("%Y-%m-%d")

    if row["channel"] == "InMail":
        cur.execute("UPDATE budgets SET val = MAX(0, val - 1) WHERE key = 'inmail_credits'")

    cur.execute("""
        UPDATE outreach_queue
        SET approval_status = 'SENT', sent_from = ?, sent_at = ?, next_followup = ?, notion_synced = 0
        WHERE id = ?
    """, (sent_from_account, now.isoformat(), followup, queue_id))

    cur.execute("""
        UPDATE jobs
        SET outreach_state = 'SENT', next_followup = ?, notion_synced = 0, updated_at = ?
        WHERE id = ?
    """, (followup, now.isoformat(), row["job_id"]))

    conn.execute("DELETE FROM agent_locks WHERE resource_id = ?", (f"JOB_{row['job_id']}",))
    conn.commit()
    conn.close()
    return json.dumps({"sent_logged": True, "queue_id": queue_id, "next_followup": followup})

@mcp.tool()
def get_or_save_screening_answer(question_key: str, new_answer_to_save: str = "") -> str:
    """Fetches a saved screening answer, or saves a new one."""
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    cur = conn.cursor()
    key = question_key.strip().lower()
    if new_answer_to_save.strip():
        ans_text = new_answer_to_save.strip()
        from tools.answers_bank import upsert_answer
        upsert_answer(conn, question=question_key.strip(), answer=ans_text, kind="fact", scope="global", status="drafted", source="server")
        cur.execute("INSERT OR REPLACE INTO screening_qa VALUES (?, ?)", (key, ans_text))
        conn.commit()
        conn.close()
        return json.dumps({"saved": True, "question_key": key, "answer": ans_text})

    # Read approved answer from answers bank
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='answers'")
    if cur.fetchone():
        from tools.answers_bank import canonical_question
        cq = canonical_question(key)
        cur.execute("SELECT answer FROM answers WHERE (lower(question) = lower(?) OR lower(question) = lower(?)) AND status = 'approved'", (key, cq))
        row = cur.fetchone()
        if row:
            conn.close()
            return json.dumps({"found": True, "question_key": key, "answer": row["answer"]})

    cur.execute("SELECT answer FROM screening_qa WHERE question_key = ?", (key,))
    row = cur.fetchone()
    if row:
        conn.close()
        return json.dumps({"found": True, "question_key": key, "answer": row["answer"]})

    # Fallback to normalized / alias matching
    fuzzy_ans = match_screening_answer(question_key, conn)
    conn.close()
    if fuzzy_ans:
        return json.dumps({"found": True, "question_key": key, "answer": fuzzy_ans})

    return json.dumps({
        "found": False,
        "directive": f"Question '{key}' is unseen. Ask the user on the Mobile App Summary Card and mark job BLOCKED_USER for now."
    })

@mcp.tool()
def get_application_answers(application: str) -> str:
    """
    Fetches application story answers from app_story_answers table for a specific company or application.
    Matches exact or substring/prefix.
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    cur = conn.cursor()
    cur.execute(
        "SELECT id, application, question, answer, status FROM app_story_answers WHERE application = ? ORDER BY id",
        (application.strip(),)
    )
    rows = cur.fetchall()
    if not rows:
        pattern = f"%{application.strip()}%"
        cur.execute(
            "SELECT id, application, question, answer, status FROM app_story_answers WHERE application LIKE ? ORDER BY id",
            (pattern,)
        )
        rows = cur.fetchall()

    conn.close()
    if not rows:
        return json.dumps({
            "found": False,
            "application": application,
            "answers": [],
            "error": f"No story answers found for application '{application}'."
        })

    answers_list = [
        {
            "id": r["id"],
            "application": r["application"],
            "question": r["question"],
            "answer": r["answer"],
            "status": r["status"]
        }
        for r in rows
    ]
    return json.dumps({
        "found": True,
        "application": application,
        "count": len(answers_list),
        "answers": answers_list
    }, indent=2)

@mcp.tool()
def mark_application_answers_submitted(application: str) -> str:
    """
    Marks application story answers in app_story_answers as 'SUBMITTED' for the given application.
    """
    conn = get_conn()
    ks = check_kill_switch(conn)
    if ks:
        conn.close()
        return json.dumps(ks)

    budget_check = check_and_increment_budget(conn)
    if budget_check:
        conn.close()
        return json.dumps(budget_check)

    cur = conn.cursor()
    cur.execute(
        "UPDATE app_story_answers SET status = 'SUBMITTED' WHERE application = ? OR application LIKE ?",
        (application.strip(), f"%{application.strip()}%")
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return json.dumps({
        "updated": True,
        "application": application,
        "rows_updated": count,
        "status": "SUBMITTED"
    })

if __name__ == "__main__":
    mcp.run()
