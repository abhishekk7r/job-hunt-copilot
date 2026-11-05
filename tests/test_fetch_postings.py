import subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "fetch_postings.py"


class FetchPostingsTest(unittest.TestCase):
    def test_rejects_out_dir_outside_cycle_work(self):
        p = subprocess.run([sys.executable, str(TOOL), "--portal", "linkedin", "--out-dir", "/tmp/x", "1"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("cycle_work", p.stdout)

    def test_rejects_unknown_portal(self):
        p = subprocess.run([sys.executable, str(TOOL), "--portal", "naukri", "--out-dir", "x", "1"],
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)

    def test_cycle_allowlist_has_tool(self):
        self.assertIn("fetch_postings.py", (ROOT / "bin/cycle.sh").read_text())


if __name__ == "__main__":
    unittest.main()
