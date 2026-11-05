#!/usr/bin/env python3
"""Outreach message renderer and validator CLI wrapper."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.outreach import main

if __name__ == "__main__":
    sys.exit(main())
