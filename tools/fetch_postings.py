#!/usr/bin/env python3
"""Fetch job details through a portal CLI and run the integrity guard, no shell pipes.

usage: fetch_postings.py --portal linkedin|freehire|wellfound --out-dir DIR REF [REF ...]

For each REF (id, slug or url) writes DIR/<portal>_<n>.txt (guard-cleaned text,
verbatim otherwise) and prints one JSON line {ref,file,verdict,ok,error}.
Page text is never put on a command line and never interpreted.
"""
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTALS = {"linkedin", "freehire", "wellfound"}
MAX_REFS = 30


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", required=True, choices=sorted(PORTALS))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("refs", nargs="+")
    a = ap.parse_args(argv)
    out = Path(a.out_dir).resolve()
    if not str(out.resolve()).startswith(str((ROOT / "reports" / "cycle_work").resolve())):
        print(json.dumps({"error": "out-dir must be under reports/cycle_work"}))
        return 2
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PATH=f"{Path.home()}/.bun/bin:" + os.environ.get("PATH", ""))
    cli = ROOT / ".agents/skills" / f"{a.portal}-search/cli/src/cli.ts"
    bad = 0
    for i, ref in enumerate(a.refs[:MAX_REFS], 1):
        res = {"ref": ref, "file": None, "verdict": None, "ok": False, "error": None}
        try:
            p = subprocess.run(["bun", "run", str(cli), "detail", ref, "--format", "plain"],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
            if p.returncode != 0 or not p.stdout.strip():
                res["error"] = (p.stderr or p.stdout or "empty").strip()[:200]
            else:
                dst = out / f"{a.portal}_{i}.txt"
                g = subprocess.run([sys.executable, str(ROOT / "tools/posting_guard.py"), "--text",
                                    "--json", "--out", str(dst)], input=p.stdout,
                                   capture_output=True, text=True, timeout=60)
                res.update(file=str(dst.relative_to(ROOT)), verdict=(g.stdout.strip().splitlines() or [""])[0][:200],
                           ok=(g.returncode == 0))
                if g.returncode != 0:
                    res["error"] = "guard flagged; treat as unreachable"
        except Exception as e:  # noqa: BLE001
            res["error"] = f"{type(e).__name__}: {e}"[:200]
        bad += 0 if res["ok"] else 1
        print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
