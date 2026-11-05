"""Contacts scoring, ranking, and deterministic connection note generator."""

import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

TITLE_WEIGHTS = {
    "talent acquisition": 30.0,
    "technical recruiter": 30.0,
    "recruiter": 25.0,
    "ta lead": 32.0,
    "engineering manager": 35.0,
    "hiring manager": 35.0,
    "software development manager": 35.0,
    "staff engineer": 32.0,
    "senior sde": 32.0,
    "senior software engineer": 32.0,
    "software engineer ii": 32.0,
    "sde-2": 32.0,
    "sde ii": 32.0,
    "sde 2": 32.0,
    "lead engineer": 30.0,
}

# Peers, EMs and senior engineers get replies; execs rarely do (user feedback:
# "targeting too high"). Candidates with these titles are rejected outright.
EXECUTIVE_PATTERNS = [
    r"\bsvp\b", r"\bevp\b", r"\bvp\b", r"vice president", r"\bcto\b", r"\bceo\b",
    r"\bcoo\b", r"\bcio\b", r"\bchief\b", r"\bpresident\b", r"\bfounder\b",
    r"\bco-founder\b", r"\bdirector\b", r"head of", r"\bgm\b", r"general manager",
    r"engineering leader", r"tech leader",
]

STACK_KEYWORDS = ["java", "spring", "backend", "back-end", "aws", "kafka", "microservice", "distributed"]


def is_executive(title: str) -> bool:
    t = title.lower()
    return any(re.search(p, t) for p in EXECUTIVE_PATTERNS)


def categorize_kind(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["talent acquisition", "ta lead", "ta manager"]) and not is_executive(t):
        return "ta_lead"
    if "recruiter" in t:
        return "recruiter"
    if is_executive(t):
        return "executive"
    if any(k in t for k in ["engineering manager", "hiring manager", "sdm"]):
        return "hiring_manager"
    if any(k in t for k in ["senior", "staff", "lead", "sde-2", "sde-3", "principal"]):
        return "senior_sde"
    return "recruiter"


def score_contact(
    candidate: Dict[str, Any],
    target_company: str,
    target_city: str = "Bangalore",
    job_applied: bool = False,
) -> float:
    """
    Deterministically scores a LinkedIn contact candidate:
    - Rejects 'Ex-<company>' or former employees (-100.0)
    - Company match: +40
    - Title match: +25 to +35
    - Connection degree: 1st (+20), 2nd (+10), 3rd (0)
    - City/region match: +10
    - Executives (VP/CTO/Director/Head of...): rejected (-100.0), peers preferred
    - Backend-stack keywords in headline: +5 each, max +10
    - Company where the user has already applied: +15
    """
    title = str(candidate.get("title", "")).lower()
    current_company = str(candidate.get("current_company", "")).strip().lower()
    t_company = target_company.strip().lower()

    # Reject Ex- / Former employees
    if re.search(rf"\b(ex|former)\s*-?\s*{re.escape(t_company)}\b", title):
        return -100.0

    if current_company and t_company not in current_company:
        return -100.0

    if is_executive(title):
        return -100.0

    score = 40.0

    # Title score
    best_title_score = 10.0
    for keyword, weight in TITLE_WEIGHTS.items():
        if keyword in title:
            if weight > best_title_score:
                best_title_score = weight
    score += best_title_score

    # Stack relevance (same-stack engineers/managers are likelier to refer)
    score += min(sum(1 for k in STACK_KEYWORDS if k in title) * 5.0, 10.0)

    # Warm company: an application already exists
    if job_applied:
        score += 15.0

    # Degree score
    degree = candidate.get("connection_degree", 2)
    if degree == 1:
        score += 20.0
    elif degree == 2:
        score += 10.0

    # City bonus
    location = str(candidate.get("location", "")).lower()
    if target_city.lower() in location or "bengaluru" in location or "remote" in location:
        score += 10.0

    # Mutual connections
    mutual = int(candidate.get("mutual_connections", 0))
    score += min(mutual, 10) * 0.5

    return round(score, 2)


def render_connection_note(
    candidate: Dict[str, Any],
    job_applied: bool = False,
    role: str = "",
    company: str = "",
    intro: str = "I'm a backend engineer working with Java, Spring Boot and AWS.",
) -> str:
    """
    Renders deterministic <=300 character connection note from verified facts only.
    Only states 'I've applied' if job_applied is True.
    """
    first_name = str(candidate.get("name", "there")).strip().split()[0]
    target_comp = company or candidate.get("current_company", "")

    if job_applied and role and target_comp:
        note = (
            f"Hi {first_name}, I've applied for the {role} role at {target_comp}. "
            f"{intro} Would love to connect!"
        )
    else:
        note = (
            f"Hi {first_name}, {intro} I've been following {target_comp}'s engineering work and would love to connect."
        )

    if len(note) > 300:
        # Fallback ultra-concise template
        if job_applied:
            note = (
                f"Hi {first_name}, I've applied for {role[:16]} at {target_comp[:16]}. "
                f"Would love to connect!"
            )
        else:
            note = (
                f"Hi {first_name}, I'm a backend engineer. "
                f"Following {target_comp[:16]}'s work and would love to connect."
            )

    return note[:300]


def save_ranked_contacts(
    job_id: Optional[int],
    company: str,
    candidates: List[Dict[str, Any]],
    db_path: str,
    job_applied: bool = False,
    role: str = "",
    top_n: int = 4,
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    now_str = datetime.utcnow().isoformat()

    # Get already contacted profiles from reachout_data
    already_contacted_urls = set()
    try:
        from tools.reachout_data import collect
        reach_state = collect(db_path)
        for r in reach_state.get("already_contacted", []):
            purl = r.get("profile_url")
            if purl:
                already_contacted_urls.add(purl.strip().rstrip("/"))
    except Exception:
        pass

    existing_urls = {r[0].strip().rstrip("/") for r in cur.execute("SELECT profile_url FROM contacts WHERE profile_url IS NOT NULL")}
    all_banned_urls = existing_urls | already_contacted_urls

    # Check existing contacts for this job_id to enforce max 4 contacts per job (2 eng, 1 manager, 1 recruiter)
    existing_for_job = cur.execute("SELECT kind FROM contacts WHERE job_id = ?", (job_id,)).fetchall() if job_id else []
    eng_count = sum(1 for r in existing_for_job if r["kind"] in ("senior_sde", "engineer"))
    mgr_count = sum(1 for r in existing_for_job if r["kind"] == "hiring_manager")
    rec_count = sum(1 for r in existing_for_job if r["kind"] in ("recruiter", "ta_lead"))
    job_total = len(existing_for_job)

    scored = []
    for c in candidates:
        title = c.get("title", "")
        if is_executive(title):
            continue
        url = c.get("profile_url", "").strip().rstrip("/")
        if not url or url in all_banned_urls:
            continue

        s = c.get("score")
        if s is None:
            s = score_contact(c, company, job_applied=job_applied)
        else:
            s = float(s)

        if s > 0:
            kind = c.get("kind") or categorize_kind(title)
            if kind == "executive":
                continue
            outreach_kind = c.get("outreach_kind") or ("job_specific" if job_applied else "networking")
            note_text = c.get("note_text") or render_connection_note(c, job_applied=job_applied, role=role, company=company)
            scored.append({
                **c,
                "score": s,
                "kind": kind,
                "outreach_kind": outreach_kind,
                "note_text": note_text,
                "note_chars": len(note_text),
                "note": c.get("note", ""),
                "email": c.get("email", ""),
            })

    # Sort descending by score
    scored.sort(key=lambda x: x["score"], reverse=True)

    saved_candidates = []
    for item in scored:
        if job_id:
            if job_total >= top_n:
                break
            k = item["kind"]
            if k in ("senior_sde", "engineer"):
                if eng_count >= 2:
                    continue
                eng_count += 1
            elif k == "hiring_manager":
                if mgr_count >= 1:
                    continue
                mgr_count += 1
            elif k in ("recruiter", "ta_lead"):
                if rec_count >= 1:
                    continue
                rec_count += 1
            job_total += 1
        elif len(saved_candidates) >= top_n:
            break

        cur.execute("""
            INSERT INTO contacts (
                job_id, name, title, profile_url, connection_degree, mutual_connections,
                current_company, location, score, kind, outreach_kind, note_text, note_chars, status, created_at, email, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?, ?)
        """, (
            job_id, item["name"], item["title"], item["profile_url"],
            item.get("connection_degree", 2), item.get("mutual_connections", 0),
            company, item.get("location", ""), item["score"],
            item["kind"], item["outreach_kind"], item["note_text"],
            item["note_chars"], now_str, item.get("email", ""), item.get("note", "")
        ))
        saved_candidates.append(item)
        all_banned_urls.add(item["profile_url"].strip().rstrip("/"))

    conn.commit()
    conn.close()
    return saved_candidates
