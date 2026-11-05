"""Answers bank matcher and form field auditor for Job Harness.

Handles exact and fuzzy lookup for screening questions, behavioral story answers,
and field auditing against the Identity Capsule (including Simplify autofill verification).
"""

import re
import sqlite3
from typing import Any, Dict, Optional, Tuple

STOP_WORDS = {"what", "is", "your", "how", "many", "do", "you", "have", "in", "of", "the", "a", "an", "please", "state"}

KEYWORD_ALIASES = {
    "notice": "notice_period_days",
    "notice period": "notice_period_days",
    "java": "java_years",
    "spring": "spring_boot_years",
    "spring boot": "spring_boot_years",
    "microservices": "microservices_years",
    "aws": "aws_years",
    "kafka": "kafka_years",
    "rag": "rag_genai_years",
    "genai": "rag_genai_years",
    "current ctc": "current_ctc",
    "expected ctc": "expected_ctc",
    "expected salary": "expected_ctc",
    "experience": "total_experience",
    "total experience": "total_experience",
}


def normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    words = [w for w in cleaned.split() if w and w not in STOP_WORDS]
    return " ".join(words)


def match_screening_answer(question: str, conn: sqlite3.Connection) -> Optional[str]:
    """Matches a screening question to an answer using exact, alias, and fuzzy containment."""
    cur = conn.cursor()
    norm_q = normalize_text(question)

    # 1. Exact match on normalized or raw
    cur.execute("SELECT answer FROM screening_qa WHERE question_key = ?", (question.strip().lower(),))
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute("SELECT question_key, answer FROM screening_qa")
    all_qa = {r[0]: r[1] for r in cur.fetchall()}

    for k, ans in all_qa.items():
        if k == norm_q or normalize_text(k) == norm_q:
            return ans

    # 2. Alias mapping lookup
    for alias_pattern, target_key in KEYWORD_ALIASES.items():
        if re.search(rf"\b{re.escape(alias_pattern)}\b", question.lower()):
            if target_key in all_qa:
                return all_qa[target_key]

    # 3. Fuzzy containment
    for k, ans in all_qa.items():
        k_words = set(normalize_text(k).split())
        q_words = set(norm_q.split())
        if k_words and k_words.issubset(q_words):
            return ans

    return None


def match_story_answer(prompt: str, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """Matches a behavioral/long-form prompt against app_story_answers and story_answers bank."""
    cur = conn.cursor()
    norm_prompt = prompt.lower()
    norm_p = normalize_text(prompt)
    p_words = set(norm_p.split())

    # 1. Search app_story_answers first (the real active table)
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_story_answers'")
        if cur.fetchone():
            cur.execute("SELECT id, application, question, answer FROM app_story_answers")
            for row in cur.fetchall():
                app_id, app_name, q_text, ans_text = row[0], row[1], row[2], row[3]
                if not q_text or not ans_text:
                    continue
                norm_q = normalize_text(q_text)
                q_words = set(norm_q.split())
                if (norm_q in norm_p or norm_p in norm_q) or (q_words and len(q_words & p_words) / len(q_words) >= 0.5):
                    return {
                        "id": app_id,
                        "topic": app_name,
                        "answer_text": ans_text,
                        "key_metrics": "",
                        "question": q_text,
                        "application": app_name,
                    }
    except sqlite3.Error:
        pass

    # 2. Search story_answers (legacy table for backwards compatibility)
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='story_answers'")
        if cur.fetchone():
            cur.execute("SELECT topic, question_pattern, answer_text, key_metrics FROM story_answers")
            rows = cur.fetchall()
            for row in rows:
                topic, pattern, ans_text, metrics = row[0], row[1], row[2], row[3]
                if pattern:
                    try:
                        if re.search(pattern, norm_prompt, re.IGNORECASE):
                            return {
                                "topic": topic,
                                "answer_text": ans_text,
                                "key_metrics": metrics
                            }
                    except re.error:
                        pass

                if topic.lower() in norm_prompt or topic.lower().replace("_", " ") in norm_prompt:
                    return {
                        "topic": topic,
                        "answer_text": ans_text,
                        "key_metrics": metrics
                    }
    except sqlite3.Error:
        pass

    return None


def audit_field_value(field_name: str, current_value: str, capsule: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Audits an autofilled field (e.g. from Simplify) against the identity capsule.
    Returns (is_correct, corrected_value). Never trusts third-party autofill blindly.
    """
    field_lower = field_name.lower().replace("_", " ")
    val_clean = str(current_value).strip()

    # Expected CTC / compensation check
    if any(k in field_lower for k in ["expected ctc", "expected salary", "expected pay", "compensation", "salary"]):
        exp = str(capsule.get("expected_ctc", 30))
        # Check if current_value matches expected
        if val_clean != exp and not val_clean.startswith(exp):
            return False, exp

    # Notice period check
    if "notice" in field_lower:
        np = str(capsule.get("notice_period", "30 days"))
        if val_clean.lower() != np.lower() and "30" not in val_clean:
            return False, np

    # Total experience check
    if "experience" in field_lower and "total" in field_lower:
        exp_yrs = str(capsule.get("total_experience", "3 years"))
        if val_clean.lower() != exp_yrs.lower() and "3" not in val_clean:
            return False, exp_yrs

    # Phone / Email / Name checks
    if "email" in field_lower and capsule.get("email_primary"):
        if val_clean.lower() != capsule["email_primary"].lower():
            return False, capsule["email_primary"]

    if "name" in field_lower and "company" not in field_lower and capsule.get("candidate_name"):
        if val_clean.lower() != capsule["candidate_name"].lower():
            return False, capsule["candidate_name"]

    # Banned link check
    for banned in capsule.get("forbidden_links", ["shorturl.at"]):
        if banned in val_clean:
            return False, capsule.get("resume_url", "")

    return True, val_clean
