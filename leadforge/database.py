import sqlite3
import os
import time
import uuid
from pathlib import Path
import pandas as pd
from leadforge.config import BASE_DIR, OUTPUT_DIR
from leadforge.utils import get_logger, clean_text

logger = get_logger()
DB_PATH = BASE_DIR / "leadforge.db"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

def uuidv7() -> str:
    """Generates a UUIDv7 string (36 characters) conforming to time-ordered UUIDv7 standard."""
    ms = int(time.time() * 1000)
    msec_bytes = ms.to_bytes(6, byteorder='big')
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Configure SQLite pragmas
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")

    return conn

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
                cursor.execute("SELECT 1 FROM migration_history WHERE migration_name = ?", (name,))
                if cursor.fetchone() is None:
                    logger.info(f"Applying migration: {name}")
                    with open(filepath, "r", encoding="utf-8") as f:
                        sql_script = f.read()

                    try:
                        conn.execute("BEGIN TRANSACTION;")
                        conn.executescript(sql_script)
                        conn.execute(
                            "INSERT INTO migration_history (id, migration_name) VALUES (?, ?);",
                            (uuidv7(), name)
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
    # Check if there are any businesses in the database
    cursor = conn.cursor()

    # We first verify if businesses table exists
    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='businesses'")
    if cursor.fetchone()[0] == 0:
        return

    cursor.execute("SELECT COUNT(*) FROM businesses")
    business_count = cursor.fetchone()[0]

    if business_count > 0:
        # DB already has data, no legacy bootstrap needed
        return

    # Check if settings table exists
    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='settings'")
    if cursor.fetchone()[0] == 0:
        return

    if not OUTPUT_DIR.exists():
        return

    excel_files = sorted(OUTPUT_DIR.glob("*.xlsx"))
    if not excel_files:
        return

    logger.info(f"Empty database detected. Found {len(excel_files)} legacy Excel files. Bootstrapping data...")

    for filepath in excel_files:
        filename = filepath.name

        # Check if already imported
        cursor.execute("SELECT value FROM settings WHERE key = ?", (f"imported_excel_{filename}",))
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
                "Discovery Date": "discovery_date"
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

            # Pre-fetch source and status IDs
            cursor.execute("SELECT id FROM discovery_sources WHERE name = 'MANUAL_IMPORT'")
            source_row = cursor.fetchone()
            source_id = source_row[0] if source_row else "01907de3-bc42-7c89-8d76-5a507db4f112"

            cursor.execute("SELECT id FROM lead_statuses WHERE name = 'OPEN'")
            status_row = cursor.fetchone()
            status_id = status_row[0] if status_row else "01907de3-bc42-7c89-8d76-5a507db4f556"

            # Create a search run history entry
            search_id = uuidv7()

            # Deduced city and category from filename
            parts = filename.replace(".xlsx", "").split("_")
            city = parts[0] if len(parts) > 0 else "Unknown"
            category = parts[1] if len(parts) > 1 else "Unknown"

            cursor.execute("""
                INSERT INTO search_history (id, city, category, search_query, results_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?)
            """, (
                search_id,
                city,
                category,
                f"{category} in {city}",
                len(records),
                # Format file timestamp or use current
                time.strftime('%Y-%m-%dT%H:%M:%fZ', time.gmtime(filepath.stat().st_mtime))
            ))

            for row in records:
                name = clean_text(row.get("name", ""))
                if not name:
                    continue

                phone = clean_text(row.get("phone", ""))
                website = clean_text(row.get("website", ""))
                address = clean_text(row.get("address", ""))
                area = clean_text(row.get("area", ""))
                clean_text(row.get("priority", "Medium"))
                notes = clean_text(row.get("notes", ""))
                category_name = clean_text(row.get("category", category))

                # Check duplicate by name + phone or address
                normalized_name = name.strip().lower()
                normalized_phone = phone.strip().replace(" ", "").replace("-", "")

                # Try to get existing business
                cursor.execute("""
                    SELECT id FROM businesses
                    WHERE normalized_name = ? AND (
                        (display_phone = ? AND display_phone != '') OR
                        id IN (SELECT business_id FROM addresses WHERE address_line = ?)
                    )
                """, (normalized_name, normalized_phone, address))

                biz_row = cursor.fetchone()
                if biz_row:
                    business_id = biz_row[0]
                else:
                    business_id = uuidv7()

                    # Ensure business type exists
                    cursor.execute("SELECT id FROM business_types WHERE name = ?", (category_name,))
                    bt_row = cursor.fetchone()
                    if bt_row:
                        business_type_id = bt_row[0]
                    else:
                        business_type_id = uuidv7()
                        cursor.execute(
                            "INSERT INTO business_types (id, name) VALUES (?, ?)",
                            (business_type_id, category_name)
                        )

                    # Insert business
                    cursor.execute("""
                        INSERT INTO businesses (id, normalized_name, name, display_phone, business_type_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (business_id, normalized_name, name, phone, business_type_id))

                    # Insert address
                    cursor.execute("""
                        INSERT INTO addresses (id, business_id, address_line, area, city, state, postal_code)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (uuidv7(), business_id, address, area, city, "Gujarat", ""))

                    # Insert digital presence
                    cursor.execute("""
                        INSERT INTO digital_presences (id, business_id, website_url, has_website)
                        VALUES (?, ?, ?, ?)
                    """, (uuidv7(), business_id, website, 1 if website else 0))

                # Insert lead linked to this campaign/filename
                cursor.execute("""
                    INSERT INTO leads (id, business_id, source_id, status_id, campaign_name)
                    VALUES (?, ?, ?, ?, ?)
                """, (uuidv7(), business_id, source_id, status_id, filename))

                # Insert opportunity
                opp_id = uuidv7()
                score = 60 if not website else 0
                cursor.execute("""
                    INSERT INTO opportunities (id, business_id, title, pipeline_stage, score)
                    VALUES (?, ?, ?, 'PROSPECTING', ?)
                """, (opp_id, business_id, f"Digital Transformation - {name}", score))

                # Insert scoring log
                cursor.execute("""
                    INSERT INTO opportunity_scoring_logs (id, opportunity_id, rule_name, score_delta, reason)
                    VALUES (?, ?, 'WEBSITE_CHECK', ?, ?)
                """, (uuidv7(), opp_id, score, notes))

            # Mark file as imported in settings
            cursor.execute("""
                INSERT OR REPLACE INTO settings (id, key, value, description)
                VALUES (?, ?, 'true', ?)
            """, (uuidv7(), f"imported_excel_{filename}", f"Bootstrap imported legacy data from {filename}"))

            conn.commit()
            logger.info(f"Successfully bootstrap imported {filename} into SQLite.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error import bootstrap for {filename}: {str(e)}")
            # Do not re-throw so we can continue with other files
            continue
