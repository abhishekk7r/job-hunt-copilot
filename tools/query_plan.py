#!/usr/bin/env python3
"""Deterministic query planner for the 6-hourly cycle.

Generates a concrete, bounded plan for one run seeded by --cycle.
Translates search_matrix.md into executable commands (Tier A) or URLs (Tier B).

Caps per cycle:
- Tier A (LinkedIn, Freehire, Wellfound) combined: <= 40 page loads.
- Tier B Naukri: <= 3 search pages.
- Tier B Instahyre: <= 3 search pages.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

TITLES = [
    "Software Engineer",
    "Software Developer",
    "Backend Engineer",
    "Backend Developer",
    "Java Developer",
    "Java Engineer",
    "SDE",
    "SDE-1",
    "SDE-2",
    "SDE II",
    "Software Development Engineer",
    "Application Engineer",
    "Application Developer",
    "Member of Technical Staff",
    "Product Engineer",
    "Platform Engineer",
    "Senior Software Engineer",
    "Technology Analyst",
    "Server-side Engineer",
    "API Engineer",
]

SKILL_PHRASES = [
    "Java Spring Boot microservices",
    "Java Kafka AWS",
    "backend distributed systems",
    "Spring Boot REST AWS",
    "JVM backend scalability",
]

ALL_TERMS = TITLES + SKILL_PHRASES  # 25 total terms

WELLFOUND_ROLES = ["software-engineer", "backend-engineer"]
LOCATIONS = ["Bengaluru", "Remote"]


def slugify(text: str) -> str:
    """Slugify text for URL paths (alphanumeric and hyphens)."""
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def get_plan(cycle: int, portal_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate deterministic plan for the given cycle number."""
    if cycle < 0:
        raise ValueError("cycle must be a non-negative integer")

    plan: List[Dict[str, Any]] = []

    # 1. LinkedIn (Tier A) - 4 queries, 1 page each = 4 page loads
    linkedin_entries: List[Dict[str, Any]] = []
    for i in range(4):
        term = ALL_TERMS[(cycle * 5 + i) % len(ALL_TERMS)]
        is_remote = (i % 2 == 1)
        if is_remote:
            loc = "India"
            cmd = (
                f'bun run .agents/skills/linkedin-search/cli/src/cli.ts search '
                f'--query "{term}" --location "India" --remote remote --jobage 14 --page 1 --limit 25 --format json'
            )
        else:
            loc = "Bengaluru, Karnataka, India"
            cmd = (
                f'bun run .agents/skills/linkedin-search/cli/src/cli.ts search '
                f'--query "{term}" --location "Bengaluru, Karnataka, India" --jobage 14 --page 1 --limit 25 --format json'
            )
        linkedin_entries.append({
            "portal": "linkedin",
            "tier": "A",
            "command": cmd,
            "query": term,
            "location": loc,
            "page": 1,
        })

    # 2. Freehire (Tier A) - 3 queries, 1 page each = 3 page loads
    freehire_entries: List[Dict[str, Any]] = []
    for i in range(3):
        term = ALL_TERMS[(cycle * 5 + 4 + i) % len(ALL_TERMS)]
        is_remote = (i % 2 == 1)
        if is_remote:
            cmd = (
                f'bun run .agents/skills/freehire-search/cli/src/cli.ts search '
                f'--query "{term}" --remote remote --page 1 --limit 25 --format json'
            )
            loc = "Remote"
        else:
            cmd = (
                f'bun run .agents/skills/freehire-search/cli/src/cli.ts search '
                f'--query "{term}" --country IN --city Bengaluru --page 1 --limit 25 --format json'
            )
            loc = "Bengaluru"
        freehire_entries.append({
            "portal": "freehire",
            "tier": "A",
            "command": cmd,
            "query": term,
            "location": loc,
            "page": 1,
        })

    # 3. Wellfound (Tier A) - 2 queries (1 for software-engineer, 1 for backend-engineer) = 2 page loads
    wellfound_entries: List[Dict[str, Any]] = []
    for i, role in enumerate(WELLFOUND_ROLES):
        cmd = (
            f'bun run .agents/skills/wellfound-search/cli/src/cli.ts search '
            f'--role {role} --location india --page 1 --limit 25 --format json'
        )
        wellfound_entries.append({
            "portal": "wellfound",
            "tier": "A",
            "command": cmd,
            "query": role,
            "location": "india",
            "page": 1,
        })

    # 4. Naukri (Tier B) - 3 queries/pages (capped at 3)
    naukri_entries: List[Dict[str, Any]] = []
    for i in range(3):
        term = ALL_TERMS[(cycle * 5 + 7 + i) % len(ALL_TERMS)]
        loc = "bengaluru"
        slug_term = slugify(term)
        url = f"https://www.naukri.com/{slug_term}-jobs-in-{loc}"
        naukri_entries.append({
            "portal": "naukri",
            "tier": "B",
            "url": url,
            "query": term,
            "location": loc,
        })

    # 5. Instahyre (Tier B) - 3 queries/pages (capped at 3)
    instahyre_entries: List[Dict[str, Any]] = []
    for i in range(3):
        term = ALL_TERMS[(cycle * 5 + 10 + i) % len(ALL_TERMS)]
        slug_term = slugify(term)
        # Allowed under /jobs/ only
        url = f"https://www.instahyre.com/jobs/?search={slug_term}"
        instahyre_entries.append({
            "portal": "instahyre",
            "tier": "B",
            "url": url,
            "query": term,
            "location": "India",
        })

    all_entries = {
        "linkedin": linkedin_entries,
        "freehire": freehire_entries,
        "wellfound": wellfound_entries,
        "naukri": naukri_entries,
        "instahyre": instahyre_entries,
    }

    if portal_filter and portal_filter != "all":
        if portal_filter not in all_entries:
            raise ValueError(f"Unknown portal '{portal_filter}', choose from {list(all_entries.keys()) + ['all']}")
        return all_entries[portal_filter]

    for p in ["linkedin", "freehire", "wellfound", "naukri", "instahyre"]:
        plan.extend(all_entries[p])

    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic search query plan for cycle")
    parser.add_argument("--cycle", type=int, required=True, help="Cycle number (non-negative integer)")
    parser.add_argument(
        "--portal",
        choices=["linkedin", "freehire", "wellfound", "naukri", "instahyre", "all"],
        default="all",
        help="Filter plan to specific portal or 'all'",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    args = parser.parse_args()

    try:
        plan = get_plan(args.cycle, args.portal)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"Query Plan for Cycle {args.cycle} (Portal: {args.portal}):")
        for i, item in enumerate(plan, 1):
            if item.get("tier") == "A":
                print(f"[{i}] {item['portal'].upper()} (Tier A): {item['command']}")
            else:
                print(f"[{i}] {item['portal'].upper()} (Tier B): {item['url']} (query: {item['query']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
