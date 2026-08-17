#!/usr/bin/env python3
"""
WAL-Safe Database Backup Script for LeadForge.
Uses SQLite's online backup API to create consistent snapshots without blocking concurrent WAL writes.
"""

import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# Add leadforge to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leadforge.config import DB_PATH
from leadforge.utils import get_logger

logger = get_logger()


def backup_database(dest_dir: Path = None) -> Path:
    """Performs an online WAL-safe backup of the LeadForge SQLite database."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Source database file not found at {DB_PATH}")

    if dest_dir is None:
        dest_dir = DB_PATH.parent / "backups"

    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"leadforge_backup_{timestamp}.db"
    backup_file = dest_dir / backup_filename

    logger.info(f"Starting online SQLite backup from {DB_PATH} to {backup_file}...")

    src_conn = sqlite3.connect(DB_PATH)
    dest_conn = sqlite3.connect(backup_file)

    try:
        with dest_conn:
            src_conn.backup(dest_conn)
        logger.info(f"Backup completed successfully: {backup_file}")
    finally:
        src_conn.close()
        dest_conn.close()

    return backup_file


if __name__ == "__main__":
    try:
        out_file = backup_database()
        print(f"SUCCESS: Backup saved to {out_file}")
    except Exception as err:
        print(f"ERROR: Backup failed: {err}", file=sys.stderr)
        sys.exit(1)
