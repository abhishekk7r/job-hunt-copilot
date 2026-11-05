import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from query_plan import (
    ALL_TERMS,
    LOCATIONS,
    SKILL_PHRASES,
    TITLES,
    WELLFOUND_ROLES,
    get_plan,
)


class TestQueryPlan(unittest.TestCase):
    def test_plan_determinism(self):
        plan1 = get_plan(0)
        plan2 = get_plan(0)
        self.assertEqual(plan1, plan2)

        plan_c5_a = get_plan(5)
        plan_c5_b = get_plan(5)
        self.assertEqual(plan_c5_a, plan_c5_b)

    def test_plan_caps(self):
        for c in range(25):
            plan = get_plan(c)
            tier_a_pages = sum(item["page"] for item in plan if item.get("tier") == "A")
            self.assertLessEqual(tier_a_pages, 40, f"Tier A page count {tier_a_pages} exceeds cap 40 in cycle {c}")

            naukri_count = sum(1 for item in plan if item.get("portal") == "naukri")
            self.assertLessEqual(naukri_count, 3, f"Naukri count {naukri_count} exceeds cap 3 in cycle {c}")

            instahyre_count = sum(1 for item in plan if item.get("portal") == "instahyre")
            self.assertLessEqual(instahyre_count, 3, f"Instahyre count {instahyre_count} exceeds cap 3 in cycle {c}")

    def test_forbidden_paths_in_urls(self):
        for c in range(50):
            plan = get_plan(c)
            for item in plan:
                if item.get("tier") == "B":
                    url = item["url"]
                    self.assertNotIn("/candidate/", url, f"Forbidden /candidate/ found in {url}")
                    self.assertNotIn("/jobsearch/", url, f"Forbidden /jobsearch/ found in {url}")

                    if item["portal"] == "naukri":
                        self.assertFalse(
                            url.endswith("-jobs-in-remote"),
                            f"Naukri URL {url} ends with forbidden -jobs-in-remote",
                        )
                        self.assertTrue(
                            re.match(r"^https://www\.naukri\.com/[a-z0-9_-]+-jobs-in-[a-z0-9_-]+", url),
                            f"Naukri URL {url} does not match allowed pattern",
                        )
                    elif item["portal"] == "instahyre":
                        self.assertTrue(
                            url.startswith("https://www.instahyre.com/jobs/"),
                            f"Instahyre URL {url} not under /jobs/",
                        )

    def test_coverage_over_100_cycles(self):
        seen_queries = set()
        for c in range(100):
            plan = get_plan(c)
            for item in plan:
                seen_queries.add(item.get("query"))

        for title in TITLES:
            self.assertIn(title, seen_queries, f"Title '{title}' not covered in 100 cycles")

        for phrase in SKILL_PHRASES:
            self.assertIn(phrase, seen_queries, f"Skill phrase '{phrase}' not covered in 100 cycles")

    def test_linkedin_commands_flags_and_locations(self):
        allowed_flags = {"--location", "--query", "--jobage", "--jobage-minutes", "--remote", "--page", "--limit", "--format"}
        for c in range(50):
            plan = get_plan(c, portal_filter="linkedin")
            for item in plan:
                cmd = item["command"]
                self.assertIn("--jobage 14", cmd, f"Missing '--jobage 14' in {cmd}")
                self.assertNotIn('--location "Remote"', cmd, f"Bare literal 'Remote' in {cmd}")
                if "--remote remote" in cmd:
                    self.assertIn('--location "India"', cmd, f"Remote entry should use --location 'India' in {cmd}")
                else:
                    self.assertIn('--location "Bengaluru, Karnataka, India"', cmd, f"Bengaluru entry missing expected location in {cmd}")

                # Validate all flags against documented list
                tokens = cmd.split()
                flags = [t for t in tokens if t.startswith("--")]
                for f in flags:
                    self.assertIn(f, allowed_flags, f"Undocumented flag '{f}' found in {cmd}")

    def test_tier_a_commands_match_allowed_tools(self):
        cycle_sh_path = REPO_ROOT / "bin" / "cycle.sh"
        self.assertTrue(cycle_sh_path.exists())
        cycle_sh_text = cycle_sh_path.read_text(encoding="utf-8")

        # Extract jobs phase allowedTools
        match = re.search(r'run_claude docs/cycle_prompts/jobs\.md.*?(?=H=|\n\n)', cycle_sh_text, re.DOTALL)
        self.assertIsNotNone(match, "Could not find jobs phase in cycle.sh")
        jobs_block = match.group(0)

        # Portals must match Bash(bun run .agents/skills/<portal>-search/cli/src/cli.ts:*)
        for c in range(5):
            plan = get_plan(c)
            for item in plan:
                if item.get("tier") == "A":
                    cmd = item["command"]
                    self.assertTrue(cmd.startswith("bun run .agents/skills/"))
                    portal = item["portal"]
                    pattern = f"Bash(bun run .agents/skills/{portal}-search/cli/src/cli.ts:*)"
                    self.assertIn(pattern, jobs_block, f"Tool pattern {pattern} not in cycle.sh jobs allow-list")

    def test_command_line_cli(self):
        res = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "query_plan.py"), "--cycle", "0", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

        # Bad cycle
        res_bad = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "query_plan.py"), "--cycle", "-1"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
