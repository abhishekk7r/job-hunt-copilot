"""Outreach message generator, template renderer, and Gmail draft creator."""

from __future__ import annotations
import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "config" / "templates"


def load_template(channel_slug: str) -> str:
    """Load template text from config/templates/{channel_slug}.txt or fallback."""
    t_file = TEMPLATES_DIR / f"{channel_slug}.txt"
    if t_file.exists():
        return t_file.read_text(encoding="utf-8").strip()

    # Fallback built-ins
    builtins = {
        "connection_note": "Hi {first_name}, {opener}. {bullets} Would love to connect! Resume: {resume_url}",
        "dm": "Hi {first_name}, {opener} ({job_url}).\n\n{bullets}\n\nResume: {resume_url} | Notice period: {notice_period}.",
        "inmail": "Subject: Application for {role} - {candidate_name}\n\nHi {first_name},\n\n{opener}\n\n{bullets}\n\nResume: {resume_url}\nNotice Period: {notice_period}\n\nBest regards,\n{candidate_name}\n{email_primary}",
        "email": "Subject: Application for {role} - {candidate_name}\n\nHi {first_name},\n\n{opener}\n\n{bullets}\n\nResume: {resume_url}\nNotice Period: {notice_period}\n\nBest regards,\n{candidate_name}\n{email_primary}",
    }
    return builtins.get(channel_slug, "{opener}\n\n{bullets}\n\nResume: {resume_url}")


def determine_channel(
    connection_degree: int,
    tier: int = 1,
    inmail_credits: int = 0,
    has_email: bool = False,
    prefer_email: bool = False
) -> str:
    """Determine best outreach channel based on degree, credits, and available contacts."""
    if prefer_email and has_email:
        return "Email"
    if connection_degree == 1:
        return "LinkedIn DM"
    if connection_degree == 2 and tier in (1, 2) and inmail_credits > 0:
        return "InMail"
    if has_email:
        return "Email"
    return "Connection Note"


def render_outreach(
    channel: str,
    job: Dict[str, Any],
    contact: Dict[str, Any],
    capsule: Dict[str, Any],
    custom_opener: str = "",
    inmail_credits: int = 0
) -> Dict[str, Any]:
    """
    Deterministically renders outreach message from templates and identity capsule.
    Enforces <=300 chars for Connection Notes, bans link shorteners,
    honours custom_opener, and guarantees 'I've applied for' phrasing in DMs.
    """
    forbidden_links = capsule.get("forbidden_links", ["shorturl.at"])
    resume_url = capsule.get("resume_url", "")
    candidate_name = capsule.get("candidate_name", "")
    email_primary = capsule.get("email_primary", "")
    notice_period = capsule.get("notice_period", "30 days")
    bullets_list: List[str] = capsule.get("bullets", [])

    # Banned link checks
    for fl in forbidden_links:
        if fl in resume_url:
            raise ValueError(f"Banned link '{fl}' detected in resume_url")
        if fl in custom_opener:
            raise ValueError(f"Banned link '{fl}' detected in custom_opener")

    contact_name = contact.get("name", "")
    first_name = contact_name.strip().split()[0] if contact_name.strip() else "there"
    role = job.get("role", "Software Engineer")
    company = job.get("company", "Company")
    job_url = job.get("job_url", "")
    job_id_ext = job.get("job_id_ext", "")

    # Opener logic honoring custom_opener & guarantees
    if channel == "LinkedIn DM":
        if custom_opener:
            opener = custom_opener.strip()
            # If custom_opener doesn't say "I've applied for", ensure phrase is present
            if "i've applied for" not in opener.lower():
                opener = f"I've applied for the {role} position at {company}. {opener}"
        else:
            opener = f"I've applied for the {role} position at {company}"

        template = load_template("dm")
        bullets_text = "\n".join(f"- {b}" for b in bullets_list)
        rendered = template.format(
            first_name=first_name,
            opener=opener,
            job_url=job_url,
            bullets=bullets_text,
            resume_url=resume_url,
            notice_period=notice_period,
            candidate_name=candidate_name,
            role=role,
            company=company
        )
        subject = ""

    elif channel == "InMail":
        if custom_opener:
            opener = custom_opener.strip()
        else:
            opener = f"I've applied for the {role} position at {company} and wanted to reach out directly."

        template = load_template("inmail")
        bullets_text = "\n".join(f"• {b}" for b in bullets_list)
        rendered = template.format(
            first_name=first_name,
            opener=opener,
            bullets=bullets_text,
            resume_url=resume_url,
            notice_period=notice_period,
            candidate_name=candidate_name,
            email_primary=email_primary,
            role=role,
            company=company,
            job_id_ext=job_id_ext
        )
        subject = f"Application for {role} ({job_id_ext}) - {candidate_name}" if job_id_ext else f"Application for {role} - {candidate_name}"

    elif channel == "Email":
        if custom_opener:
            opener = custom_opener.strip()
        else:
            opener = f"I've applied for the {role} position at {company}."

        template = load_template("email")
        bullets_text = "\n".join(f"• {b}" for b in bullets_list)
        rendered = template.format(
            first_name=first_name,
            opener=opener,
            bullets=bullets_text,
            resume_url=resume_url,
            notice_period=notice_period,
            candidate_name=candidate_name,
            email_primary=email_primary,
            role=role,
            company=company,
            job_id_ext=job_id_ext
        )
        subject = f"Application for {role} - {candidate_name}"

    else:  # Connection Note
        channel = "Connection Note"
        if custom_opener:
            opener = custom_opener.strip()
        else:
            opener = f"I've applied for {role} at {company}"

        template = load_template("connection_note")
        bullets_text = bullets_list[0] if bullets_list else "3 yrs Java/Spring Boot experience"
        rendered = template.format(
            first_name=first_name,
            opener=opener,
            bullets=bullets_text,
            resume_url=resume_url,
            candidate_name=candidate_name,
            role=role,
            company=company
        )
        # Enforce <= 300 chars
        if len(rendered) > 300:
            short_opener = f"I've applied for {role[:20]} at {company[:16]}"
            short_bullet = "3 yrs Java/Spring Boot backend"
            rendered = f"Hi {first_name}, {short_opener}. {short_bullet}. Would love to connect! Resume: {resume_url}"
            if len(rendered) > 300:
                rendered = rendered[:297] + "..."
        subject = ""

    # Extra safety assertions: never contains shorturl.at
    for fl in forbidden_links:
        if fl in rendered:
            raise ValueError(f"Rendered message contains forbidden link: {fl}")

    return {
        "channel": channel,
        "subject": subject,
        "body": rendered,
        "char_count": len(rendered),
        "to": contact.get("email", ""),
        "contact_name": contact_name,
        "contact_linkedin": contact.get("linkedin_url", "")
    }


def create_gmail_draft(
    to_email: str,
    subject: str,
    body: str,
    draft_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Creates a Gmail draft file in outreach_emails/ directory.
    Guaranteed NEVER to send an email - only prepares drafts for user review.
    """
    out_dir = draft_dir or (REPO_ROOT / "outreach_emails")
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_to = (to_email or "unknown").replace("@", "_at_").replace(".", "_")
    filename = f"draft_{timestamp}_{safe_to}.txt"
    filepath = out_dir / filename

    draft_content = (
        f"To: {to_email}\n"
        f"Subject: {subject}\n"
        f"Date: {datetime.utcnow().isoformat()}\n"
        f"Status: DRAFT_ONLY (NEVER SENT AUTOMATICALLY)\n"
        f"---------------------------------------------------\n\n"
        f"{body}\n"
    )

    filepath.write_text(draft_content, encoding="utf-8")
    return {
        "draft_created": True,
        "channel": "Email",
        "to": to_email,
        "subject": subject,
        "draft_path": str(filepath),
        "sent": False
    }


BANNED_SHORTENERS = [
    "bit.ly", "tinyurl.com", "shorturl.at", "t.co", "goo.gl",
    "ow.ly", "buff.ly", "is.gd", "cutt.ly", "rb.gy", "rebrand.ly",
]

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA70-\U0001FAFF"
    "]+",
    flags=re.UNICODE
)


def validate_outreach(
    channel: str,
    job_id: int,
    file_path: Union[str, Path],
    db_path: Optional[str] = None
) -> List[str]:
    """
    Validates a prospective outreach draft against hard constraints:
    - Length limits per channel
    - Required 'I have applied' phrasing if job is APPLIED
    - Canonical resume link present for email/InMail and no other resume links
    - No link shorteners or banned links
    - Zero markdown syntax (plain text only)
    - Zero emojis
    - Every number/metric present in applicant facts or job note (blocks hallucinations)
    """
    channel = channel.lower().strip()
    if channel not in ("note", "inmail", "email"):
        return [f"Unknown channel: {channel!r}. Must be 'note', 'inmail', or 'email'."]

    p = Path(file_path)
    if not p.is_file():
        return [f"Draft file not found: {file_path}"]

    text = p.read_text(encoding="utf-8")
    errors: List[str] = []

    # Parse subject and body if formatted as Subject: ...
    subject = ""
    body = text
    if text.startswith("Subject:"):
        parts = text.split("\n\n", 1)
        if len(parts) == 2:
            subject = parts[0][len("Subject:"):].strip()
            body = parts[1].strip()
        else:
            lines = text.splitlines()
            subject = lines[0][len("Subject:"):].strip()
            body = "\n".join(lines[1:]).strip()

    # 1. Length checks
    if channel == "note":
        if len(text.strip()) > 300:
            errors.append(f"Connection note length ({len(text.strip())}) exceeds 300 characters limit")
    elif channel == "inmail":
        if subject and len(subject) > 200:
            errors.append(f"InMail subject length ({len(subject)}) exceeds 200 characters limit")
        if len(body) > 1900:
            errors.append(f"InMail body length ({len(body)}) exceeds 1900 characters limit")
    elif channel == "email":
        if subject and len(subject) > 200:
            errors.append(f"Email subject length ({len(subject)}) exceeds 200 characters limit")
        if len(body) > 10000:
            errors.append(f"Email body length ({len(body)}) exceeds limit")

    # 2. Markdown checks
    if re.search(r'\[([^\]]+)\]\(([^)]+)\)', text):
        errors.append("Markdown link format [text](url) detected; plain text required")
    if re.search(r'^\s*#{1,6}\s+\S', text, re.M):
        errors.append("Markdown header detected; plain text required")
    if re.search(r'(\*\*|__)[^\s*].*?\1', text):
        errors.append("Markdown bold formatting detected; plain text required")
    if "`" in text:
        errors.append("Markdown backticks detected; plain text required")

    # 3. Emoji check
    if EMOJI_PATTERN.search(text):
        errors.append("Emojis detected in message; plain text without emojis required")

    # 4. Banned links & shorteners
    from harness.config import identity_capsule
    try:
        capsule = identity_capsule()
    except Exception:
        capsule = {}
    banned = list(capsule.get("forbidden_links", [])) + BANNED_SHORTENERS
    for b in banned:
        if b.lower() in text.lower():
            errors.append(f"Forbidden link or shortener detected: '{b}'")

    # 5. Database checks: job status and 'I have applied'
    db_file = db_path or os.environ.get("HARNESS_DB", str(REPO_ROOT / "harness.db"))
    job_row = None
    if os.path.exists(db_file):
        try:
            conn = sqlite3.connect(db_file, timeout=5.0)
            conn.row_factory = sqlite3.Row
            job_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            conn.close()
        except Exception:
            pass

    if job_row and job_row["status"] == "APPLIED":
        low_text = text.lower()
        if "i have applied" not in low_text and "i've applied" not in low_text:
            errors.append("Job status is APPLIED: outreach message must explicitly state 'I have applied'")

    # 6. Canonical resume URL for email and InMail
    canonical_resume = capsule.get("resume_url", "").strip()
    if channel in ("inmail", "email"):
        if canonical_resume and canonical_resume not in text:
            errors.append(f"Canonical resume link ({canonical_resume}) missing from {channel} draft")

        # Disallow any other resume links
        all_urls = re.findall(r'https?://[^\s<>"\')]+', text)
        for u in all_urls:
            if canonical_resume and u == canonical_resume:
                continue
            if any(k in u.lower() for k in ("resume", "cv", "drive.google.com", "dropbox.com")):
                errors.append(f"Unauthorized resume link found: '{u}' (only canonical resume URL allowed)")

    # 7. Number verification (prevent hallucinated numbers/metrics)
    # Extract numbers like 50, 50K, 30%, 3.5, 3
    msg_numbers = set(re.findall(r'\b\d+(?:[.,]\d+)?%?', text))

    sources_text = []
    # Candidate facts
    for facts_p in (REPO_ROOT / "config" / "applicant_facts.local.md", REPO_ROOT / "config" / "applicant_facts.example.md"):
        if facts_p.is_file():
            sources_text.append(facts_p.read_text(encoding="utf-8"))
            break
    # Config toml
    for toml_p in (REPO_ROOT / "config" / "local.toml", REPO_ROOT / "config" / "example.toml"):
        if toml_p.is_file():
            sources_text.append(toml_p.read_text(encoding="utf-8"))
            break
    # Job research note
    job_note_p = REPO_ROOT / "reports" / "jobs" / f"{job_id}.md"
    if job_note_p.is_file():
        sources_text.append(job_note_p.read_text(encoding="utf-8"))
    # Job row
    if job_row:
        job_dict = dict(job_row)
        sources_text.append(f"{job_dict.get('company', '')} {job_dict.get('role', '')} {job_dict.get('job_id_ext', '')}")
    # Canonical resume URL
    if canonical_resume:
        sources_text.append(canonical_resume)

    all_source_content = " ".join(sources_text)
    source_numbers = set(re.findall(r'\b\d+(?:[.,]\d+)?%?', all_source_content))
    for num in msg_numbers:
        if num in source_numbers or num in all_source_content:
            continue
        clean_num = num.rstrip("%Kk")
        if clean_num in source_numbers or clean_num in all_source_content:
            continue
        errors.append(f"Invented number or metric '{num}' not found in applicant facts or job note")

    return errors


def record_outreach_draft(
    conn: sqlite3.Connection,
    job_id: int,
    company: str,
    role: str,
    recruiter_name: str,
    recruiter_linkedin: str,
    channel: str,
    message: str,
    to_email: str = "",
    subject: str = "",
) -> int:
    """Records an outreach draft in outreach_queue and outreach_email_drafts if email."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO outreach_queue (
            job_id, company, role, recruiter_name, recruiter_linkedin, channel,
            rendered_message, char_count, approval_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_MOBILE_REVIEW')
    """, (
        job_id, company, role, recruiter_name, recruiter_linkedin, channel,
        message, len(message)
    ))
    queue_id = cur.lastrowid

    if channel.lower() == "email" and to_email:
        now_ts = datetime.utcnow().isoformat()
        cur.execute("""
            INSERT OR REPLACE INTO outreach_email_drafts (
                job_id, company, contact_name, contact_linkedin, to_email, subject, body, status, saved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT_NOT_SENT', ?)
        """, (
            job_id, company, recruiter_name, recruiter_linkedin, to_email,
            subject or f"Application for {role} - {recruiter_name}", message, now_ts
        ))

    conn.commit()
    return queue_id


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Outreach message renderer and validator CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--channel", required=True, choices=["note", "inmail", "email"])
    v.add_argument("--job", required=True, type=int)
    v.add_argument("--file", required=True)
    v.add_argument("--db", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "validate":
        errors = validate_outreach(args.channel, args.job, args.file, db_path=args.db)
        if errors:
            print(f"Validation failed for {args.channel} (job #{args.job}):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        print(f"VALID: {args.channel} message passed all checks.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
