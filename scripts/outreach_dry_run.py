#!/usr/bin/env python3
"""Run a read-only safety report before using the manual deliver trigger."""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/outreach_dry_run.py` from a checkout without requiring
# callers to set PYTHONPATH first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leadforge.outreach.dry_run import build_dry_run_report, format_dry_run_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only outreach pre-send dry run")
    parser.add_argument("--draft-id", action="append", dest="draft_ids", help="Approved draft ID to include (repeatable)")
    args = parser.parse_args()
    print(format_dry_run_report(asyncio.run(build_dry_run_report(args.draft_ids))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
