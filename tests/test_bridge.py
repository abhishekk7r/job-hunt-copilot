"""Tests for tools/bridge.py and tools/export_tracker.py."""

import json
import sqlite3
from pathlib import Path
import pytest

from tools.bridge import bridge_seen_jobs
from tools.export_tracker import export_tracker
from tools.rank_state import tracker_pairs

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_seen_jobs(tmp_path):
    data = {
        "acme_corp_sde-2": {
            "company": "Acme Corp",
            "title": "SDE-2 Backend",
            "url": "https://acme.com/jobs/101",
            "status": "ranked",
            "rank_score": 82.0,
            "rank_verdict": "Strong Fit",
            "rank_reason": "Excellent Java/Spring Boot fit",
            "salary_lpa": 28,
            "stack": "Java, Spring Boot, AWS",
            "source": "linkedin-search"
        },
        "beta_tech_backend-lead": {
            "company": "Beta Tech",
            "title": "Backend Lead",
            "url": "https://beta.tech/careers/202",
            "status": "ranked",
            "rank_score": 70.0,
            "rank_verdict": "Good Fit",
            "rank_reason": "Microservices experience",
            "salary": None,  # Unknown salary must pass
            "stack": "Java, Kafka, Microservices",
            "source": "freehire"
        },
        "gamma_apps_android-dev": {
            "company": "Gamma Apps",
            "title": "Senior Android Developer",
            "url": "https://gamma.apps/jobs/303",
            "status": "ranked",
            "rank_score": 65.0,
            "rank_verdict": "Good Fit",
            "rank_reason": "Mobile stack",
            "salary_lpa": 30,
            "stack": "Android, Kotlin",
            "source": "linkedin-search"
        },
        "delta_soft_low-salary": {
            "company": "Delta Soft",
            "title": "Java Developer",
            "url": "https://deltasoft.in/jobs/404",
            "status": "ranked",
            "rank_score": 60.0,
            "rank_verdict": "Good Fit",
            "rank_reason": "Low salary offering",
            "salary_lpa": 14,  # Below 22 LPA floor
            "stack": "Java, Spring Boot",
            "source": "naukri"
        },
        "epsilon_weak_fit": {
            "company": "Epsilon",
            "title": "Junior Python Coder",
            "url": "https://epsilon.com/jobs/505",
            "status": "ranked",
            "rank_score": 35.0,
            "rank_verdict": "Weak Fit",
            "rank_reason": "Below score threshold",
            "salary_lpa": 25,
            "stack": "Python, Flask",
            "source": "freehire"
        }
    }
    state_file = tmp_path / "seen_jobs.json"
    state_file.write_text(json.dumps(data), encoding="utf-8")
    return state_file


def test_bridge_filtering_and_insertion(temp_db, sample_seen_jobs):
    """Verify bridge correctly filters and categorizes jobs."""
    counts = bridge_seen_jobs(sample_seen_jobs, Path(temp_db), min_verdict="Medium")
    assert counts["inserted"] == 5
    assert counts["eligible"] == 2  # Acme and Beta Tech
    assert counts["ranked_out"] == 3  # Gamma (Android), Delta (low pay), Epsilon (Weak Fit)

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT company, status, salary_lpa FROM jobs ORDER BY company")
    jobs = {r["company"]: dict(r) for r in cur.fetchall()}

    assert jobs["Acme Corp"]["status"] == "TO_APPLY"
    assert jobs["Acme Corp"]["salary_lpa"] == 28

    assert jobs["Beta Tech"]["status"] == "TO_APPLY"
    assert jobs["Beta Tech"]["salary_lpa"] is None

    assert jobs["Gamma Apps"]["status"] == "RANKED_OUT"
    assert jobs["Delta Soft"]["status"] == "RANKED_OUT"
    assert jobs["Epsilon"]["status"] == "RANKED_OUT"
    conn.close()


def test_bridge_idempotency_and_no_downgrade(temp_db, sample_seen_jobs):
    """Verify bridge re-runs are idempotent and never downgrade in-progress jobs."""
    # First bridge run
    bridge_seen_jobs(sample_seen_jobs, Path(temp_db))

    # Manually transition Acme to APPLIED, Beta Tech to BLOCKED_USER
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE jobs SET status = 'APPLIED' WHERE company = 'Acme Corp'")
    conn.execute("UPDATE jobs SET status = 'BLOCKED_USER', blocker_note = 'OTP required' WHERE company = 'Beta Tech'")
    conn.commit()
    conn.close()

    # Second bridge run
    counts2 = bridge_seen_jobs(sample_seen_jobs, Path(temp_db))
    assert counts2["inserted"] == 0
    assert counts2["updated"] == 5
    assert counts2["skipped_existing_active"] == 2

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT company, status FROM jobs WHERE company IN ('Acme Corp', 'Beta Tech')")
    statuses = {r["company"]: r["status"] for r in cur.fetchall()}
    assert statuses["Acme Corp"] == "APPLIED", "APPLIED job must not be downgraded"
    assert statuses["Beta Tech"] == "BLOCKED_USER", "BLOCKED_USER job must not be downgraded"
    conn.close()


def test_bridge_dry_run(temp_db, sample_seen_jobs):
    """Verify dry-run mode does not modify the database."""
    counts = bridge_seen_jobs(sample_seen_jobs, Path(temp_db), dry_run=True)
    assert counts["inserted"] == 5

    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM jobs")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 0, "Dry run must make no DB changes"


def test_export_tracker_and_roundtrip(temp_db, sample_seen_jobs, tmp_path):
    """Verify export_tracker produces canonical 14-col CSV readable by upstream tools."""
    bridge_seen_jobs(sample_seen_jobs, Path(temp_db))

    csv_out = tmp_path / "job_search_tracker.csv"
    count = export_tracker(Path(temp_db), csv_out)
    assert count == 5
    assert csv_out.exists()

    # Read back using upstream's rank_state.tracker_pairs
    pairs = tracker_pairs(csv_out)
    assert len(pairs) == 5
    expected_pairs = {("acmecorp", "sde2backend"), ("betatech", "backendlead")}
    assert expected_pairs.issubset(pairs)
