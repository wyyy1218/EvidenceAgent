#!/usr/bin/env python3
"""Wrapper: `python scripts/ea.py …` → unified CLI (S48).

Do not name this file evidence_agent.py — that shadows the package.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
