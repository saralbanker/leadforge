import sqlite3
import os
import time
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union, Dict, List, Any
import pandas as pd
from leadforge.config import BASE_DIR, OUTPUT_DIR
from leadforge.utils import get_logger, clean_text
from leadforge.normalizer import canonical_phone

logger = get_logger()
DB_PATH = BASE_DIR / "leadforge.db"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def uuidv7() -> str:
    """Generates a UUIDv7 string (36 characters) conforming to time-ordered UUIDv7 standard."""
    ms = int(time.time() * 1000)
    msec_bytes = ms.to_bytes(6, byteorder="big")
    rand = os.urandom(10)

    h = bytearray(16)
    h[0:6] = msec_bytes
    # Set version 7 in upper bits of byte 6
    h[6] = 0x70 | (rand[0] & 0x0F)
    h[7] = rand[1]
    # Set variant 10 in upper bits of byte 8
    h[8] = 0x80 | (rand[2] & 0x3F)
    h[9:16] = rand[3:10]

    return str(uuid.UUID(bytes=bytes(h)))


def get_db_connection() -> sqlite3.Connection:
    """Establishes connection to the SQLite database and configures WAL/FKs."""
    path = os.environ.get("LEADFORGE_DB_PATH") or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # Configure SQLite pragmas
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")

    return conn


def append_event(
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    event_version: int = 1,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """Appends an immutable record to event_store using UUIDv7 primary key.

    Args:
        event_type: Identifier of the event type (e.g., 'LEAD_CREATED').
        entity_type: Target entity model name (e.g., 'Lead', 'Opportunity').
        entity_id: Primary key of target entity.
        payload: Event data context (dictionary, string, or None).
        event_version: Schema version for event payload structure (default 1).
        conn: Optional existing sqlite3.Connection context.

    Returns:
        The generated UUIDv7 event_id string.
    """
    event_id = uuidv7()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    if payload is None:
        payload_str = "{}"
    elif isinstance(payload, str):
        payload_str = payload
    else:
        try:
            payload_str = json.dumps(payload, default=str)
        except Exception:
            payload_str = str(payload)

    query = """
        INSERT INTO event_store (
            event_id, event_type, entity_type, entity_id, timestamp, payload, event_version, processed_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """
    params = (
        event_id,
        str(event_type),
        str(entity_type),
        str(entity_id),
        timestamp,
        payload_str,
        int(event_version),
    )

    if conn is not None:
        cursor = conn.cursor()
        cursor.execute(query, params)
    else:
        db_conn = get_db_connection()
        try:
            cursor = db_conn.cursor()
            cursor.execute(query, params)
            db_conn.commit()
        finally:
            db_conn.close()

    logger.info(f"Event logged [{event_type}] for {entity_type}:{entity_id} (id={event_id})")
    return event_id



def initialize_database():
    """Initializes database, runs pending migrations, and triggers legacy Excel bootstrap."""
    logger.info("Initializing database and checking migrations...")

    conn = get_db_connection()
    try:
        # Create migration tracking table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS migration_history (
                id TEXT PRIMARY KEY CHECK(length(id) = 36),
                migration_name TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)
        conn.commit()

        # Scan and run migrations
        if MIGRATIONS_DIR.exists():
            migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            for filepath in migration_files:
                name = filepath.name

                # Check if migration is already applied
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM migration_history WHERE migration_name = ?", (name,)
                )
                if cursor.fetchone() is None:
                    logger.info(f"Applying migration: {name}")
                    with open(filepath, "r", encoding="utf-8") as f:
                        sql_script = f.read()

                    try:
                        # executescript() handles BEGIN…END trigger blocks correctly.
                        # It issues an implicit COMMIT before running, so the
                        # migration_history INSERT follows in a separate execute().
                        # All migration SQL uses IF NOT EXISTS / OR IGNORE, so a
                        # re-run on next startup is always a safe no-op.
                        conn.executescript(sql_script)
                        conn.execute(
                            "INSERT INTO migration_history (id, migration_name) VALUES (?, ?);",
                            (uuidv7(), name),
                        )
                        conn.commit()
                        logger.info(f"Migration {name} applied successfully.")
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Failed to apply migration {name}: {str(e)}")
                        raise e

        # Check and perform legacy Excel bootstrap migration
        bootstrap_legacy_data(conn)

    finally:
        conn.close()


def bootstrap_legacy_data(conn: sqlite3.Connection):
    """Checks if the database is empty and performs a one-time import of legacy Excel exports."""
    if os.environ.get("LEADFORGE_SKIP_BOOTSTRAP"):
        return

    # Check if there are any businesses in the database
    cursor = conn.cursor()

    # We first verify if businesses table exists
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='businesses'"
    )
    if cursor.fetchone()[0] == 0:
        return

    cursor.execute("SELECT COUNT(*) FROM businesses")
    business_count = cursor.fetchone()[0]

    if business_count > 0:
        # DB already has data, no legacy bootstrap needed
        return

    # Check if settings table exists
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='settings'"
    )
    if cursor.fetchone()[0] == 0:
        return

    if not OUTPUT_DIR.exists():
        return

    excel_files = sorted(OUTPUT_DIR.glob("*.xlsx"))
    if not excel_files:
        return

    logger.info(
        f"Empty database detected. Found {len(excel_files)} legacy Excel files. Bootstrapping data..."
    )

    for filepath in excel_files:
        filename = filepath.name

        # Check if already imported
        cursor.execute(
            "SELECT value FROM settings WHERE key = ?", (f"imported_excel_{filename}",)
        )
        if cursor.fetchone() is not None:
            continue

        logger.info(f"Importing legacy Excel file: {filename}")
        try:
            df = pd.read_excel(filepath)
            df = df.fillna("")

            # Map nice columns back to field keys
            col_mapping = {
                "Business Name": "name",
                "Business Category": "category",
                "Phone Number": "phone",
                "Website": "website",
                "Address": "address",
                "Area": "area",
                "Priority": "priority",
                "Notes": "notes",
                "Discovery Date": "discovery_date",
            }

            # Re-map columns
            records = []
            for _, row in df.iterrows():
                record = {}
                for excel_col, key in col_mapping.items():
                    if excel_col in df.columns:
                        record[key] = row[excel_col]
                    else:
                        record[key] = ""
                records.append(record)

            # Perform insertions
            conn.execute("BEGIN TRANSACTION;")
            # Collect engine payloads to dispatch after the transaction commits.
            _engine_payloads = []

            # Pre-fetch source and status IDs
            cursor.execute(
                "SELECT id FROM discovery_sources WHERE name = 'MANUAL_IMPORT'"
            )
            source_row = cursor.fetchone()
            source_id = (
                source_row[0] if source_row else "01907de3-bc42-7c89-8d76-5a507db4f112"
            )

            cursor.execute("SELECT id FROM lead_statuses WHERE name = 'OPEN'")
            status_row = cursor.fetchone()
            status_id = (
                status_row[0] if status_row else "01907de3-bc42-7c89-8d76-5a507db4f556"
            )

            # Create a search run history entry
            search_id = uuidv7()

            # Deduced city and category from filename
            parts = filename.replace(".xlsx", "").split("_")
            city = parts[0] if len(parts) > 0 else "Unknown"
            category = parts[1] if len(parts) > 1 else "Unknown"

            cursor.execute(
                """
                INSERT INTO search_history (id, city, category, search_query, results_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?)
            """,
                (
                    search_id,
                    city,
                    category,
                    f"{category} in {city}",
                    len(records),
                    # Format file timestamp or use current
                    datetime.fromtimestamp(
                        filepath.stat().st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                ),
            )

            for row in records:
                name = clean_text(row.get("name", ""))
                if not name:
                    continue

                phone = clean_text(row.get("phone", ""))
                website = clean_text(row.get("website", ""))
                address = clean_text(row.get("address", ""))
                area = clean_text(row.get("area", ""))
                clean_text(row.get("priority", "Medium"))
                category_name = clean_text(row.get("category", category))

                # Canonical deduplication: use normalized_phone column
                normalized_name = name.strip().lower()
                norm_phone = canonical_phone(phone)

                # Try to get existing business by canonical phone, then name+address
                biz_row = None
                if len(norm_phone) >= 7:
                    cursor.execute(
                        "SELECT id FROM businesses WHERE normalized_phone = ?",
                        (norm_phone,),
                    )
                    biz_row = cursor.fetchone()

                if not biz_row:
                    cursor.execute(
                        """
                        SELECT b.id FROM businesses b
                        WHERE b.normalized_name = ?
                          AND EXISTS (
                              SELECT 1 FROM addresses a
                              WHERE a.business_id = b.id AND a.address_line = ?
                          )
                    """,
                        (normalized_name, address),
                    )
                    biz_row = cursor.fetchone()

                if biz_row:
                    business_id = biz_row[0]
                else:
                    business_id = uuidv7()

                    # Ensure business type exists
                    cursor.execute(
                        "SELECT id FROM business_types WHERE name = ?", (category_name,)
                    )
                    bt_row = cursor.fetchone()
                    if bt_row:
                        business_type_id = bt_row[0]
                    else:
                        business_type_id = uuidv7()
                        cursor.execute(
                            "INSERT INTO business_types (id, name) VALUES (?, ?)",
                            (business_type_id, category_name),
                        )

                    # Insert business with canonical phone
                    cursor.execute(
                        """
                        INSERT INTO businesses (id, normalized_name, name, display_phone, normalized_phone, business_type_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            business_id,
                            normalized_name,
                            name,
                            phone,
                            norm_phone or None,
                            business_type_id,
                        ),
                    )

                    append_event(
                        event_type="BUSINESS_DISCOVERED",
                        entity_type="Business",
                        entity_id=business_id,
                        payload={"name": name, "category": category_name, "source": "MANUAL_IMPORT"},
                        conn=conn,
                    )


                    # Insert address
                    cursor.execute(
                        """
                        INSERT INTO addresses (id, business_id, address_line, area, city, state, postal_code)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (uuidv7(), business_id, address, area, city, "", ""),
                    )

                    # Insert digital presence
                    cursor.execute(
                        """
                        INSERT INTO digital_presences (id, business_id, website_url, has_website)
                        VALUES (?, ?, ?, ?)
                    """,
                        (uuidv7(), business_id, website, 1 if website else 0),
                    )

                # INSERT OR IGNORE: one lead row per (business, campaign)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO leads (id, business_id, source_id, status_id, campaign_name)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (uuidv7(), business_id, source_id, status_id, filename),
                )

                # Collect engine payload for post-commit dispatch.
                _engine_payloads.append(
                    {
                        "business_id": business_id,
                        "name": name,
                        "category": category_name,
                        "website": website,
                        "contact_email": "",
                        "phone": phone,
                        "rating": None,
                        "review_count": None,
                        "business_status": "OPERATIONAL",
                        "categories": "",
                    }
                )

            # Mark file as imported in settings
            cursor.execute(
                """
                INSERT OR REPLACE INTO settings (id, key, value, description)
                VALUES (?, ?, 'true', ?)
            """,
                (
                    uuidv7(),
                    f"imported_excel_{filename}",
                    f"Bootstrap imported legacy data from {filename}",
                ),
            )

            conn.commit()
            logger.info(f"Successfully bootstrap imported {filename} into SQLite.")

            # Engine calls run after commit using separate connections (avoids lock).
            from leadforge.opportunity_engine import OpportunityIntelligenceEngine

            for payload in _engine_payloads:
                try:
                    OpportunityIntelligenceEngine().generate_for_business(payload)
                except Exception as eng_err:
                    logger.warning(
                        f"Opportunity generation failed for {payload.get('name')}: {eng_err}"
                    )

        except Exception as e:
            conn.rollback()
            logger.error(f"Error import bootstrap for {filename}: {str(e)}")
            # Do not re-throw so we can continue with other files
            continue
