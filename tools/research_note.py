#!/usr/bin/env python3
"""Job research note generator and manager.

Produces and parses `reports/jobs/<job_id>.md` for Moderate+ ranked jobs.
Includes ATS type detection, login-wall indicators, pitch angles, and
referral-first flags (defaulting to True when rank_score >= 80).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports" / "jobs"


def get_note_path(job_id: int, reports_dir: Optional[Path] = None) -> Path:
    base = reports_dir if reports_dir is not None else DEFAULT_REPORTS_DIR
    return base / f"{job_id}.md"


def write_research_note(
    job_id: int,
    company: str,
    role: str,
    apply_url: str = "",
    rank_score: Optional[int] = None,
    summary: str = "",
    must_have: str = "",
    nice_to_have: str = "",
    fit_reasons: str = "",
    gaps: str = "",
    ats_type: str = "unknown",
    login_required: str = "unknown",
    pitch_angle: str = "",
    referral_first: Optional[bool] = None,
    possible_duplicate: Optional[str] = None,
    reports_dir: Optional[Path] = None,
) -> Path:
    """Write or overwrite reports/jobs/<job_id>.md."""
    target_dir = reports_dir if reports_dir is not None else DEFAULT_REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / f"{job_id}.md"

    if referral_first is None:
        referral_first = bool(rank_score is not None and rank_score >= 80)

    rf_str = "yes" if referral_first else "no"
    score_str = str(rank_score) if rank_score is not None else ""

    lines = [
        f"# Research Note: {company} - {role} (Job #{job_id})",
        "",
        f"- **Company:** {company}",
        f"- **Role:** {role}",
        f"- **Apply URL:** {apply_url}",
        f"- **Rank Score:** {score_str}",
        f"- **ATS Type:** {ats_type}",
        f"- **login_required:** {login_required}",
        f"- **referral_first:** {rf_str}",
        f"- **pitch_angle:** {pitch_angle}",
    ]
    if possible_duplicate:
        lines.append(f"- **possible_duplicate:** {possible_duplicate}")
    lines.extend([
        "",
        "## Summary",
        summary.strip() or "No summary provided.",
        "",
        "## Must-Have vs Nice-To-Have",
        "### Must-Have",
        must_have.strip() or "None specified.",
        "",
        "### Nice-To-Have",
        nice_to_have.strip() or "None specified.",
        "",
        "## Fit Reasons & Gaps",
        "### Fit Reasons",
        fit_reasons.strip() or "None specified.",
        "",
        "### Gaps",
        gaps.strip() or "None specified.",
        "",
    ])

    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def read_research_note(job_id: int, reports_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Read and parse research note if it exists."""
    path = get_note_path(job_id, reports_dir)
    if not path.is_file():
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    data: Dict[str, Any] = {
        "job_id": job_id,
        "file": str(path),
        "company": "",
        "role": "",
        "apply_url": "",
        "rank_score": None,
        "ats_type": "unknown",
        "login_required": "unknown",
        "referral_first": False,
        "pitch_angle": "",
        "possible_duplicate": None,
    }

    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("- **"):
            continue
        m = re.match(r"^-\s+\*\*([^*]+)\*\*:?\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1).rstrip(":").strip().lower(), m.group(2).strip()
        if key == "company":
            data["company"] = val
        elif key == "role":
            data["role"] = val
        elif key == "apply url":
            data["apply_url"] = val
        elif key == "rank score":
            if val.isdigit():
                data["rank_score"] = int(val)
        elif key == "ats type":
            data["ats_type"] = val
        elif key == "login_required":
            data["login_required"] = val
        elif key == "referral_first":
            data["referral_first"] = val.lower() in ("yes", "true", "1")
        elif key == "pitch_angle":
            data["pitch_angle"] = val
        elif key == "possible_duplicate":
            data["possible_duplicate"] = val

    return data


def is_referral_first(job_id: int, reports_dir: Optional[Path] = None) -> bool:
    """Check if the job's research note specifies referral_first: yes."""
    data = read_research_note(job_id, reports_dir)
    if not data:
        return False
    return bool(data.get("referral_first", False))


def set_referral_flag(job_id: int, on: bool = True, reports_dir: Optional[Path] = None) -> bool:
    """Set referral_first flag to yes or no in reports/jobs/<job_id>.md."""
    path = get_note_path(job_id, reports_dir)
    target_val = "yes" if on else "no"

    if not path.is_file():
        # Create minimal note if none exists yet
        write_research_note(
            job_id=job_id,
            company=f"Company #{job_id}",
            role="Unknown Role",
            referral_first=on,
            reports_dir=reports_dir,
        )
        return True

    try:
        content = path.read_text(encoding="utf-8")
        if re.search(r"-\s+\*\*referral_first:?\*\*:?\s*.*", content, re.IGNORECASE):
            content = re.sub(
                r"-\s+\*\*referral_first:?\*\*:?\s*.*",
                f"- **referral_first:** {target_val}",
                content,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            # Insert after the last bullet before ## Summary
            lines = content.splitlines()
            insert_idx = len(lines)
            for idx, line in enumerate(lines):
                if line.startswith("## "):
                    insert_idx = idx
                    break
            lines.insert(insert_idx, f"- **referral_first:** {target_val}")
            content = "\n".join(lines)

        path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Research note manager CLI")
    subparsers = parser.add_subparsers(dest="command")

    get_p = subparsers.add_parser("get", help="Get parsed research note JSON")
    get_p.add_argument("--job", type=int, required=True, help="Job ID")
    get_p.add_argument("--reports-dir", type=str, default=None, help="Reports directory")

    set_p = subparsers.add_parser("set-referral", help="Set referral-first flag")
    set_p.add_argument("--job", type=int, required=True, help="Job ID")
    set_p.add_argument("--on", action="store_true", default=None, help="Set referral_first: yes")
    set_p.add_argument("--off", action="store_true", default=None, help="Set referral_first: no")
    set_p.add_argument("--reports-dir", type=str, default=None, help="Reports directory")

    args = parser.parse_args()
    reports_dir = Path(args.reports_dir) if getattr(args, "reports_dir", None) else None

    if args.command == "get":
        data = read_research_note(args.job, reports_dir)
        print(json.dumps(data or {"error": f"Note not found for job {args.job}"}, indent=2))
        return

    if args.command == "set-referral":
        on_val = False if args.off else True
        ok = set_referral_flag(args.job, on=on_val, reports_dir=reports_dir)
        print(json.dumps({"ok": ok, "job_id": args.job, "referral_first": on_val}))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
