from typing import List, Dict, Any, Optional
import re
from urllib.parse import urlparse
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import LeadRepositoryInterface, RepositoryException
from leadforge.utils import clean_text

def extract_domain(url: str) -> str:
    """Helper to extract clean, normalized domain string from URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.strip().lower()
    except Exception:
        return ""

class SQLiteLeadRepository(LeadRepositoryInterface):
    def check_duplicate(self, google_place_id: Optional[str], name: str, phone: Optional[str]) -> bool:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # 1. Check Google Place ID Match
            if google_place_id:
                cursor.execute("SELECT 1 FROM businesses WHERE google_place_id = ?", (google_place_id,))
                if cursor.fetchone():
                    return True

            # 2. Check Name + Phone Match
            normalized_name = name.strip().lower()
            if phone:
                normalized_phone = phone.strip().replace(" ", "").replace("-", "")
                cursor.execute("""
                    SELECT 1 FROM businesses
                    WHERE normalized_name = ?
                      AND REPLACE(REPLACE(display_phone, ' ', ''), '-', '') = ?
                """, (normalized_name, normalized_phone))
                if cursor.fetchone():
                    return True

            return False
        except Exception as e:
            raise RepositoryException(f"Failed to check duplicate business: {str(e)}")
        finally:
            conn.close()

    def get_leads_by_campaign(self, campaign_name: str) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    b.name,
                    bt.name AS category,
                    b.display_phone AS phone,
                    dp.website_url AS website,
                    a.address_line AS address,
                    a.area,
                    o.score,
                    o.pipeline_stage,
                    l.created_at AS discovery_date,
                    osl.reason AS notes
                FROM leads l
                JOIN businesses b ON l.business_id = b.id
                JOIN business_types bt ON b.business_type_id = bt.id
                JOIN addresses a ON b.id = a.business_id
                JOIN digital_presences dp ON b.id = dp.business_id
                JOIN opportunities o ON b.id = o.business_id
                LEFT JOIN opportunity_scoring_logs osl ON o.id = osl.opportunity_id
                WHERE l.campaign_name = ?
                ORDER BY o.score DESC
            """, (campaign_name,))
            rows = cursor.fetchall()

            leads = []
            for row in rows:
                score = row["score"]
                priority = "High" if score >= 60 else "Medium"

                # Format discovery_date to YYYY-MM-DD
                disc_date = ""
                if row["discovery_date"]:
                    try:
                        disc_date = row["discovery_date"].split("T")[0]
                    except Exception:
                        disc_date = row["discovery_date"]

                leads.append({
                    "name": row["name"],
                    "category": row["category"],
                    "phone": row["phone"],
                    "website": row["website"],
                    "address": row["address"],
                    "area": row["area"],
                    "priority": priority,
                    "score": score,
                    "notes": row["notes"],
                    "discovery_date": disc_date
                })
            return leads
        except Exception as e:
            raise RepositoryException(f"Failed to query leads for campaign '{campaign_name}': {str(e)}")
        finally:
            conn.close()

    def save_lead_transaction(self, lead_data: Dict[str, Any], campaign_name: str) -> str:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # Start transaction
            conn.execute("BEGIN TRANSACTION;")

            # Get default discovery source ID
            cursor.execute("SELECT id FROM discovery_sources WHERE name = 'SCRAPER'")
            source_row = cursor.fetchone()
            source_id = source_row[0] if source_row else "01907de3-bc42-7c89-8d76-5a507db4ef8f"

            # Get default status ID
            cursor.execute("SELECT id FROM lead_statuses WHERE name = 'OPEN'")
            status_row = cursor.fetchone()
            status_id = status_row[0] if status_row else "01907de3-bc42-7c89-8d76-5a507db4f556"

            name = clean_text(lead_data.get("name", ""))
            phone = clean_text(lead_data.get("phone", ""))
            website = clean_text(lead_data.get("website", ""))
            address = clean_text(lead_data.get("address", ""))
            area = clean_text(lead_data.get("area", ""))
            category_name = clean_text(lead_data.get("category", "General"))
            source_url = lead_data.get("source_url", "")

            # Extract google place ID if URL matches Maps format
            google_place_id = None
            if source_url and "/maps/place/" in source_url:
                match = re.search(r'1s(0x[a-fA-F0-9]+:0x[a-fA-F0-9]+)', source_url)
                if match:
                    google_place_id = match.group(1)
                else:
                    google_place_id = source_url

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

            # Check duplicate to find existing business ID
            business_id = None
            normalized_name = name.strip().lower()
            normalized_phone = phone.strip().replace(" ", "").replace("-", "")

            if google_place_id:
                cursor.execute("SELECT id FROM businesses WHERE google_place_id = ?", (google_place_id,))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            if not business_id and phone:
                cursor.execute("""
                    SELECT id FROM businesses
                    WHERE normalized_name = ?
                      AND REPLACE(REPLACE(display_phone, ' ', ''), '-', '') = ?
                """, (normalized_name, normalized_phone))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            if not business_id and address:
                cursor.execute("""
                    SELECT b.id FROM businesses b
                    JOIN addresses a ON b.id = a.business_id
                    WHERE b.normalized_name = ? AND a.address_line = ?
                """, (normalized_name, address))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            if business_id:
                # Business exists, update mutable fields if they are blank in DB
                cursor.execute("""
                    UPDATE businesses
                    SET google_place_id = COALESCE(google_place_id, ?),
                        display_phone = COALESCE(NULLIF(display_phone, ''), ?),
                        website_domain = COALESCE(NULLIF(website_domain, ''), ?)
                    WHERE id = ?
                """, (google_place_id, phone, extract_domain(website), business_id))
            else:
                # Business does not exist, insert new
                business_id = uuidv7()
                cursor.execute("""
                    INSERT INTO businesses (id, google_place_id, website_domain, normalized_name, name, display_phone, business_type_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    business_id,
                    google_place_id,
                    extract_domain(website),
                    normalized_name,
                    name,
                    phone,
                    business_type_id
                ))

                # Insert address
                cursor.execute("""
                    INSERT INTO addresses (id, business_id, address_line, area, city, state, postal_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (uuidv7(), business_id, address, area, "Ahmedabad", "Gujarat", ""))

                # Insert digital presence
                cursor.execute("""
                    INSERT INTO digital_presences (id, business_id, website_url, has_website)
                    VALUES (?, ?, ?, ?)
                """, (uuidv7(), business_id, website, 1 if website else 0))

            # Insert lead entry linked to campaign
            cursor.execute("""
                INSERT INTO leads (id, business_id, source_id, status_id, campaign_name)
                VALUES (?, ?, ?, ?, ?)
            """, (uuidv7(), business_id, source_id, status_id, campaign_name))

            # Insert opportunity
            opp_id = uuidv7()
            score = lead_data.get("score", 0)
            cursor.execute("""
                INSERT INTO opportunities (id, business_id, title, pipeline_stage, score)
                VALUES (?, ?, ?, 'PROSPECTING', ?)
            """, (opp_id, business_id, f"Digital Transformation - {name}", score))

            # Insert opportunity scoring logs
            cursor.execute("""
                INSERT INTO opportunity_scoring_logs (id, opportunity_id, rule_name, score_delta, reason)
                VALUES (?, ?, 'WEBSITE_CHECK', ?, ?)
            """, (uuidv7(), opp_id, score, lead_data.get("notes", "")))

            conn.commit()
            return business_id
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to save lead transaction: {str(e)}")
        finally:
            conn.close()
