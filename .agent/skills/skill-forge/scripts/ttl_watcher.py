#!/usr/bin/env python3
"""
skill-forge TTL Watcher — Auto-delete custom skills unused for N days.

Reads .agent/skills/.skill_usage.json for last-use timestamps.
Respects protected skills list (core skills that are never deleted).
Supports --dry-run and --ttl-days flags.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Protected skills — never auto-deleted
PROTECTED_DEFAULT = [
    "task-planner", "debugging-master", "code-synthesizer", "architecture-analyst",
    "system-auditor", "test-generator", "security-auditor", "performance-optimizer",
    "refactoring-specialist", "research-engine", "dependency-analyzer",
    "documentation-writer", "frontend-design", "skill-forge",
]

SKILLS_DIR = Path(".agent/skills")
USAGE_FILE = SKILLS_DIR / ".skill_usage.json"
PROTECTED_FILE = SKILLS_DIR / ".protected"


def load_protected() -> set:
    """Load protected list from file, fallback to hardcoded defaults."""
    if PROTECTED_FILE.exists():
        names = PROTECTED_FILE.read_text().strip().splitlines()
        return {n.strip() for n in names if n.strip()}
    return set(PROTECTED_DEFAULT)


def load_usage() -> dict:
    """Load usage JSON, return empty dict if missing or invalid."""
    if not USAGE_FILE.exists():
        return {}
    try:
        return json.loads(USAGE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def parse_timestamp(ts: str) -> datetime:
    """Parse ISO-8601 timestamp to timezone-aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main():
    parser = argparse.ArgumentParser(description="Delete custom skills unused beyond TTL")
    parser.add_argument("--ttl-days", type=int, default=30, help="Days before expiry (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    usage = load_usage()
    if not usage:
        print("No usage data found.")
        sys.exit(0)

    protected = load_protected()
    now = datetime.now(timezone.utc)
    deleted, retained = 0, 0

    for skill_name, last_used_str in sorted(usage.items()):
        skill_dir = SKILLS_DIR / skill_name

        # Skip skills whose directory no longer exists
        if not skill_dir.is_dir():
            continue

        try:
            last_used = parse_timestamp(last_used_str)
        except (ValueError, TypeError):
            print(f"Skipped: @{skill_name} (invalid timestamp: {last_used_str})")
            retained += 1
            continue

        days_unused = (now - last_used).days

        # Never delete protected skills
        if skill_name in protected:
            if days_unused > args.ttl_days:
                print(f"Skipped: @{skill_name} (protected)")
            retained += 1
            continue

        # Delete if past TTL
        if days_unused > args.ttl_days:
            if args.dry_run:
                print(f"Would delete: @{skill_name} (unused {days_unused} days)")
            else:
                shutil.rmtree(skill_dir)
                print(f"Deleted: @{skill_name} (unused {days_unused} days)")
            deleted += 1
        else:
            retained += 1

    if deleted == 0 and not args.dry_run:
        print("No custom skills to expire.")

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{prefix}skill-forge TTL check: {deleted} deleted, {retained} retained")


if __name__ == "__main__":
    main()
