"""Test the cycle pipeline tools integration (candidates -> store -> apply -> bridge)."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_cycle_pipeline_end_to_end(temp_db, tmp_path):
    """Feed 3 fake portal hits through candidates -> store -> apply -> bridge.

    Asserts Medium+ jobs land in SQLite jobs table with TO_APPLY status,
    while Low fit jobs do not (they are marked RANKED_OUT).
    """
    state_file = tmp_path / "seen_jobs.json"
    tracker_file = tmp_path / "tracker.csv"
    tracker_file.write_text("date,company,role\n", encoding="utf-8")

    hits_file = tmp_path / "hits.json"
    fake_hits = [
        {
            "title": "Senior Backend Engineer",
            "company": "Acme Corp",
            "url": "https://wellfound.com/jobs/101-senior-backend-engineer",
            "location": "Bengaluru",
            "date": "2026-11-01",
        },
        {
            "title": "Java Spring Developer",
            "company": "Beta Tech",
            "url": "https://freehire.me/jobs/beta-java-dev",
            "location": "Remote",
            "date": "2026-11-01",
        },
        {
            "title": "React Frontend Intern",
            "company": "Gamma Software",
            "url": "https://linkedin.com/jobs/view/303",
            "location": "Mumbai",
            "date": "2026-11-01",
        },
    ]
    hits_file.write_text(json.dumps(fake_hits), encoding="utf-8")

    # Step 1: scrape_state.py candidates
    res_cand = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "scrape_state.py"),
            "candidates",
            "--results",
            str(hits_file),
            "--portal",
            "wellfound-search",
            "--state",
            str(state_file),
            "--tracker",
            str(tracker_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    cand_out = json.loads(res_cand.stdout)
    assert len(cand_out["selected"]) == 3

    # Step 2: enrich hits and scrape_state.py store
    enriched_hits = []
    for h in cand_out["selected"]:
        enriched_hits.append(
            {
                **h,
                "first_seen": "2026-11-02",
                "posted_date": h.get("date") or "2026-11-01",
                "deadline": None,
                "fit": "high" if "Backend" in h["title"] else ("medium" if "Java" in h["title"] else "low"),
                "status": "new",
                "portal": "wellfound-search",
                "source": "cli",
            }
        )
    enriched_file = tmp_path / "enriched.json"
    enriched_file.write_text(json.dumps(enriched_hits), encoding="utf-8")

    res_store = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "scrape_state.py"),
            "store",
            "--results",
            str(enriched_file),
            "--state",
            str(state_file),
            "--tracker",
            str(tracker_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    store_out = json.loads(res_store.stdout)
    added_keys = store_out["added"]
    assert len(added_keys) == 3

    # Step 3: rank_state.py apply with schema from .claude/commands/rank.md Step 2
    # Key 0: Strong Fit (~84 score)
    # Key 1: Good Fit (~67 score)
    # Key 2: Weak Fit (~31 score)
    scores = [
        {
            "key": added_keys[0],
            "status": "scored",
            "scores": {"technical": 85, "experience": 85, "behavioral": 80, "career": 85},
            "location_verdict": "PASS",
            "language_gate": "PASS",
            "deadline": None,
            "strengths": ["Strong Java Spring Boot AWS background"],
            "gaps": ["None"],
            "language": "en",
            "guard": "clean",
        },
        {
            "key": added_keys[1],
            "status": "scored",
            "scores": {"technical": 70, "experience": 65, "behavioral": 70, "career": 65},
            "location_verdict": "PASS",
            "language_gate": "PASS",
            "deadline": None,
            "strengths": ["Solid Java skills"],
            "gaps": ["Lacks cloud depth"],
            "language": "en",
            "guard": "clean",
        },
        {
            "key": added_keys[2],
            "status": "scored",
            "scores": {"technical": 30, "experience": 30, "behavioral": 40, "career": 30},
            "location_verdict": "PASS",
            "language_gate": "PASS",
            "deadline": None,
            "strengths": ["Basic familiarity"],
            "gaps": ["Lacks all core qualifications"],
            "language": "en",
            "guard": "clean",
        },
    ]
    scores_file = tmp_path / "scores.json"
    scores_file.write_text(json.dumps(scores), encoding="utf-8")

    res_apply = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "rank_state.py"),
            "apply",
            "--results",
            str(scores_file),
            "--state",
            str(state_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res_apply.returncode == 0

    # Step 4: bridge.py --min-verdict Medium
    res_bridge = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "bridge.py"),
            "--state",
            str(state_file),
            "--db",
            temp_db,
            "--min-verdict",
            "Medium",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res_bridge.returncode == 0

    # Step 5: Assert in SQLite jobs table
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT company, role, status, rank_verdict FROM jobs")
    rows = cur.fetchall()
    conn.close()

    status_by_company = {r[0]: (r[2], r[3]) for r in rows}

    # Medium+ jobs must land as TO_APPLY
    assert "Acme Corp" in status_by_company
    assert status_by_company["Acme Corp"][0] == "TO_APPLY"
    assert status_by_company["Acme Corp"][1] == "Strong Fit"

    assert "Beta Tech" in status_by_company
    assert status_by_company["Beta Tech"][0] == "TO_APPLY"
    assert status_by_company["Beta Tech"][1] == "Good Fit"

    # Low fit job must NOT land as TO_APPLY (it is RANKED_OUT)
    assert "Gamma Software" in status_by_company
    assert status_by_company["Gamma Software"][0] == "RANKED_OUT"
    assert status_by_company["Gamma Software"][1] == "Weak Fit"
