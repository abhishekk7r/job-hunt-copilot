"""Verification tests for the four primary commands: /find, /apply, /reach, /send."""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"
EXTRA_DIR = COMMANDS_DIR / "extra"

FOUR_COMMANDS = ["find.md", "apply.md", "reach.md", "send.md"]
DELETED_COMMANDS = ["find-contacts.md", "network.md", "outreach.md"]


class FourCommandsTests(unittest.TestCase):
    def test_four_commands_exist(self):
        """The four user commands must exist directly under .claude/commands/."""
        for cmd in FOUR_COMMANDS:
            cmd_path = COMMANDS_DIR / cmd
            self.assertTrue(cmd_path.is_file(), f"{cmd} must exist in .claude/commands/")

    def test_only_four_commands_at_top_level(self):
        """Only the four commands (and extra/ directory) may exist in .claude/commands/."""
        files = [f.name for f in COMMANDS_DIR.glob("*.md")]
        self.assertEqual(sorted(files), sorted(FOUR_COMMANDS), f"Unexpected command files in {COMMANDS_DIR}: {files}")

    def test_deleted_commands_do_not_exist(self):
        """Deleted commands must not exist in .claude/commands/."""
        for cmd in DELETED_COMMANDS:
            cmd_path = COMMANDS_DIR / cmd
            self.assertFalse(cmd_path.exists(), f"Deleted command {cmd} should not exist in .claude/commands/")

    def test_tools_in_four_commands_parse_help(self):
        """Every 'python3 tools/...' script referenced in the four commands must exit 0 with --help."""
        tool_pattern = re.compile(r"python3\s+(tools/[\w_]+\.py)")
        seen_tools = set()

        for cmd in FOUR_COMMANDS:
            text = (COMMANDS_DIR / cmd).read_text(encoding="utf-8")
            matches = tool_pattern.findall(text)
            for m in matches:
                seen_tools.add(m)

        self.assertTrue(len(seen_tools) > 0, "Should have discovered tools in command specs")

        for tool_rel in seen_tools:
            tool_path = REPO_ROOT / tool_rel
            self.assertTrue(tool_path.is_file(), f"Tool script {tool_rel} must exist")
            res = subprocess.run(
                [sys.executable, str(tool_path), "--help"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"{tool_rel} --help failed with exit {res.returncode}: {res.stderr}",
            )

    def test_no_references_to_deleted_commands_in_active_specs(self):
        """Verify no active command or agent skill references deleted commands."""
        deleted_refs = ["find-contacts.md", "network.md", "outreach.md"]
        scan_paths = list(COMMANDS_DIR.glob("*.md")) + list((REPO_ROOT / ".agents" / "skills").glob("*/SKILL.md"))

        for p in scan_paths:
            content = p.read_text(encoding="utf-8")
            for ref in deleted_refs:
                self.assertNotIn(
                    ref,
                    content,
                    f"Found deleted reference {ref} in {p.relative_to(REPO_ROOT)}",
                )


if __name__ == "__main__":
    unittest.main()
