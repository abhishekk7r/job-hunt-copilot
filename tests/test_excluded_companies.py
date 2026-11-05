import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import excluded_companies as ex  # noqa: E402


class ExcludedTest(unittest.TestCase):
    def test_whole_word_match(self):
        n = ["acme", "foo bar"]
        self.assertTrue(ex.is_excluded("ACME Web Services", n))
        self.assertTrue(ex.is_excluded("Foo  Bar Ltd", n))
        self.assertFalse(ex.is_excluded("Acmetech", n))
        self.assertFalse(ex.is_excluded("", n))

    def test_candidates_drops_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "x.txt").write_text("# c\nacme\n")
            (d / "r.json").write_text(json.dumps([
                {"title": "SDE", "company": "Acme", "url": "https://e.com/1"},
                {"title": "SDE", "company": "Other", "url": "https://e.com/2"}]))
            (d / "s.json").write_text('{"seen": {}}')
            p = subprocess.run([sys.executable, str(ROOT / "tools/scrape_state.py"), "candidates",
                                "--results", str(d / "r.json"), "--state", str(d / "s.json"),
                                "--portal", "t", "--tracker", str(d / "none.csv")],
                               capture_output=True, text=True, cwd=ROOT,
                               env=dict(os.environ, EXCLUDED_COMPANIES_FILE=str(d / "x.txt")))
            out = json.loads(p.stdout)
            self.assertEqual([j["company"] for j in out["selected"]], ["Other"])
            self.assertEqual(out["excluded_company"], 1)


if __name__ == "__main__":
    unittest.main()
