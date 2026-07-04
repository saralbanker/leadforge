from typing import List, Dict, Any, Optional
import re
from urllib.parse import urlparse
from datetime import datetime, timezone
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import LeadRepositoryInterface, RepositoryException
from leadforge.utils import clean_text
from leadforge.normalizer import (
    normalize_phone,
    normalize_domain,
    normalize_category,
    normalize_status
)

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

            # 2. Check Phone Number Match
            normalized_phone = normalize_phone(phone)
            if normalized_phone:
                cursor.execute("""
                    SELECT 1 FROM businesses
                    WHERE display_phone IS NOT NULL AND display_phone != ''
                      AND REPLACE(REPLACE(REPLACE(REPLACE(display_phone, ' ', ''), '-', ''), '(', ''), ')', '') = ?
                """, (re.sub(r'[\s\-\(\)\+]', '', phone),))
                if cursor.fetchone():
                    return True

            # 3. Check Website Domain Match
            # Handled during transaction check since domain is not passed to check_duplicate signature

            # 4. Check Name + Phone Match
            normalized_name = name.strip().lower()
            if phone:
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
            # Phase 3: each business may have multiple opportunities.
            # We surface one row per lead using the highest-scoring opportunity
            # for the business, and the most recent scoring-log reason.
            cursor.execute("""
                SELECT
                    b.name,
                    COALESCE(bt.name, '')          AS category,
                    COALESCE(b.display_phone, '')  AS phone,
                    COALESCE(dp.website_url, '')   AS website,
                    COALESCE(a.address_line, '')   AS address,
                    COALESCE(a.area, '')           AS area,
                    b.rating,
                    b.review_count,
                    COALESCE(best.score, 0)        AS score,
                    best.pipeline_stage,
                    l.created_at                   AS discovery_date,
                    osl.reason                     AS notes,
                    COALESCE(dm.grade, '')         AS maturity_grade,
                    COALESCE(dm.maturity_score, 0) AS maturity_score
                FROM leads l
                JOIN businesses b ON l.business_id = b.id
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN addresses a ON b.id = a.business_id AND a.is_primary = 1
                LEFT JOIN digital_presences dp ON b.id = dp.business_id
                LEFT JOIN (
                    SELECT business_id, MAX(score) AS score, pipeline_stage
                    FROM opportunities
                    WHERE deleted_at IS NULL
                    GROUP BY business_id
                ) best ON b.id = best.business_id
                LEFT JOIN opportunities o ON o.business_id = b.id
                    AND o.score = best.score AND o.deleted_at IS NULL
                LEFT JOIN opportunity_scoring_logs osl ON o.id = osl.opportunity_id
                LEFT JOIN digital_maturities dm ON b.id = dm.business_id
                WHERE l.campaign_name = ?
                GROUP BY l.id
                ORDER BY COALESCE(best.score, 0) DESC
            """, (campaign_name,))
            rows = cursor.fetchall()

            leads = []
            for row in rows:
                score = row["score"] or 0
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
                    "rating": row["rating"],
                    "review_count": row["review_count"],
                    "priority": priority,
                    "score": score,
                    "maturity_grade": row["maturity_grade"],
                    "maturity_score": round(row["maturity_score"] or 0, 1),
                    "notes": row["notes"] or "",
                    "discovery_date": disc_date,
                })
            return leads
        except Exception as e:
            raise RepositoryException(f"Failed to query leads for campaign '{campaign_name}': {str(e)}")
        finally:
            conn.close()


    def save_lead_transaction(self, lead_data: Dict[str, Any], campaign_name: str, search_id: Optional[str] = None) -> Dict[str, Any]:
        # Collect engine payload after commit so we can call it with a clean connection.
        _engine_payload: dict | None = None
        _result_biz_id: str | None = None

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

            # Scraper metadata fields (Phase 2)
            rating = lead_data.get("rating")
            review_count = lead_data.get("review_count")
            business_status = clean_text(lead_data.get("business_status", ""))
            opening_hours = lead_data.get("opening_hours", "")
            categories = lead_data.get("categories", "")

            # Normalize values before storage
            normalized_name = name.strip().lower()
            normalized_phone = normalize_phone(phone)
            website_domain = normalize_domain(website)
            normalized_status = normalize_status(business_status)
            normalized_category = normalize_category(category_name)
            now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%fZ')

            # Extract google place ID if URL matches Maps format
            google_place_id = None
            if source_url and "/maps/place/" in source_url:
                match = re.search(r'1s(0x[a-fA-F0-9]+:0x[a-fA-F0-9]+)', source_url)
                if match:
                    google_place_id = match.group(1)
                else:
                    google_place_id = source_url

            # Ensure business type exists
            cursor.execute("SELECT id FROM business_types WHERE name = ?", (normalized_category,))
            bt_row = cursor.fetchone()
            if bt_row:
                business_type_id = bt_row[0]
            else:
                business_type_id = uuidv7()
                cursor.execute(
                    "INSERT INTO business_types (id, name) VALUES (?, ?)",
                    (business_type_id, normalized_category)
                )

            # --- Centralized Duplicate Detection Priority ---
            business_id = None

            # 1. Google Place ID
            if google_place_id:
                cursor.execute("SELECT id FROM businesses WHERE google_place_id = ?", (google_place_id,))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            # 2. Phone Number
            if not business_id and normalized_phone:
                cursor.execute("""
                    SELECT id FROM businesses
                    WHERE display_phone IS NOT NULL AND display_phone != ''
                      AND REPLACE(REPLACE(REPLACE(REPLACE(display_phone, ' ', ''), '-', ''), '(', ''), ')', '') = ?
                """, (re.sub(r'[\s\-\(\)\+]', '', phone),))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            # 3. Website Domain
            if not business_id and website_domain:
                cursor.execute("SELECT id FROM businesses WHERE website_domain = ?", (website_domain,))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            # 4. Name + Area
            if not business_id and normalized_name and area:
                cursor.execute("""
                    SELECT b.id FROM businesses b
                    JOIN addresses a ON b.id = a.business_id
                    WHERE b.normalized_name = ? AND LOWER(TRIM(a.area)) = ?
                """, (normalized_name, area.strip().lower()))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            # 5. Name + Address
            if not business_id and normalized_name and address:
                cursor.execute("""
                    SELECT b.id FROM businesses b
                    JOIN addresses a ON b.id = a.business_id
                    WHERE b.normalized_name = ? AND LOWER(TRIM(a.address_line)) = ?
                """, (normalized_name, address.strip().lower()))
                row = cursor.fetchone()
                if row:
                    business_id = row[0]

            save_status = "inserted"
            if business_id:
                # Deduplication conflict checking & merge logic (Phase 2)
                cursor.execute("""
                    SELECT google_place_id, display_phone, website_domain, rating, review_count, business_status, opening_hours, categories
                    FROM businesses WHERE id = ?
                """, (business_id,))
                db_row = cursor.fetchone()

                db_place_id = db_row["google_place_id"]
                db_phone = db_row["display_phone"]
                db_domain = db_row["website_domain"]
                db_rating = db_row["rating"]
                db_reviews = db_row["review_count"]
                db_status = db_row["business_status"]
                db_hours = db_row["opening_hours"]
                db_categories = db_row["categories"]

                updates = {}
                conflicts = []

                # Merge Google Place ID
                if google_place_id:
                    if not db_place_id:
                        updates["google_place_id"] = google_place_id
                    elif db_place_id != google_place_id:
                        conflicts.append(("google_place_id", db_place_id, google_place_id))

                # Merge Phone Number
                if phone:
                    if not db_phone:
                        updates["display_phone"] = phone
                    elif normalize_phone(db_phone) != normalized_phone:
                        conflicts.append(("display_phone", db_phone, phone))

                # Merge Website Domain
                if website_domain:
                    if not db_domain:
                        updates["website_domain"] = website_domain
                    elif db_domain != website_domain:
                        conflicts.append(("website_domain", db_domain, website_domain))

                # Merge Scraper Metrics (Rating, Reviews, Status, Hours, Categories)
                if rating is not None:
                    if db_rating is None:
                        updates["rating"] = rating
                    elif db_rating != rating:
                        conflicts.append(("rating", str(db_rating), str(rating)))

                if review_count is not None:
                    if db_reviews is None:
                        updates["review_count"] = review_count
                    elif db_reviews != review_count:
                        conflicts.append(("review_count", str(db_reviews), str(review_count)))

                if normalized_status:
                    if not db_status:
                        updates["business_status"] = normalized_status
                    elif db_status != normalized_status:
                        conflicts.append(("business_status", db_status, normalized_status))

                if opening_hours:
                    if not db_hours:
                        updates["opening_hours"] = opening_hours
                    elif db_hours != opening_hours:
                        conflicts.append(("opening_hours", db_hours, opening_hours))

                if categories:
                    if not db_categories:
                        updates["categories"] = categories
                    elif db_categories != categories:
                        conflicts.append(("categories", db_categories, categories))

                # Apply updates to empty fields
                if updates:
                    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                    cursor.execute(
                        f"UPDATE businesses SET {set_clause}, last_scraped_at = ? WHERE id = ?",
                        list(updates.values()) + [now_str, business_id]
                    )
                    save_status = "updated"
                else:
                    cursor.execute(
                        "UPDATE businesses SET last_scraped_at = ? WHERE id = ?",
                        (now_str, business_id)
                    )
                    save_status = "duplicate"

                # Log conflicts to audit_logs and activity_timeline
                if conflicts:
                    conflict_desc = ", ".join([f"{field}: '{before}' vs '{after}'" for field, before, after in conflicts])

                    # Record audit log
                    for field, before, after in conflicts:
                        cursor.execute("""
                            INSERT INTO audit_logs (id, entity_type, entity_id, action_type, actor, before_state_json, after_state_json, client_metadata_json, occurred_at)
                            VALUES (?, 'businesses', ?, 'UPDATE', 'scraper', ?, ?, ?, ?)
                        """, (
                            uuidv7(),
                            business_id,
                            f'{{"{field}": "{before}"}}',
                            f'{{"{field}": "{after}"}}',
                            '{"conflict": true, "reason": "Conflict detected during scraper pipeline run"}',
                            now_str
                        ))

                    # Record timeline event
                    cursor.execute("""
                        INSERT INTO activity_timeline (id, business_id, activity_type, title, description, occurred_at)
                        VALUES (?, ?, 'NOTE_ADDED', 'Data Conflict Detected', ?, ?)
                    """, (
                        uuidv7(),
                        business_id,
                        f"Scraped new values that conflict with existing values: {conflict_desc}",
                        now_str
                    ))
            else:
                # Business does not exist, insert new business record
                business_id = uuidv7()
                cursor.execute("""
                    INSERT INTO businesses (
                        id, google_place_id, website_domain, normalized_name, name, display_phone, business_type_id,
                        rating, review_count, business_status, opening_hours, categories, last_scraped_at, first_discovered_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    business_id,
                    google_place_id,
                    website_domain,
                    normalized_name,
                    name,
                    phone,
                    business_type_id,
                    rating,
                    review_count,
                    normalized_status,
                    opening_hours,
                    categories,
                    now_str,
                    now_str
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

            # Insert lead entry linked to campaign and search_history_id
            cursor.execute("""
                INSERT INTO leads (id, business_id, source_id, status_id, campaign_name, search_history_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (uuidv7(), business_id, source_id, status_id, campaign_name, search_id))

            # If search_id is provided, increment search run counts inside the transaction
            if search_id:
                if save_status == "inserted":
                    cursor.execute("""
                        UPDATE search_history
                        SET new_businesses = COALESCE(new_businesses, 0) + 1
                        WHERE id = ?
                    """, (search_id,))
                elif save_status == "updated":
                    cursor.execute("""
                        UPDATE search_history
                        SET updated_businesses = COALESCE(updated_businesses, 0) + 1
                        WHERE id = ?
                    """, (search_id,))
                elif save_status == "duplicate":
                    cursor.execute("""
                        UPDATE search_history
                        SET duplicate_detections = COALESCE(duplicate_detections, 0) + 1
                        WHERE id = ?
                    """, (search_id,))

            conn.commit()
            # Capture engine payload before connection closes.
            # The engine MUST run after commit so it can open its own clean connection.
            _result_biz_id = business_id
            _engine_payload = {
                "business_id": business_id,
                "name": name,
                "category": normalized_category,
                "website": website,
                "contact_email": lead_data.get("contact_email", ""),
                "phone": phone,
                "rating": rating,
                "review_count": review_count,
                "business_status": normalized_status,
                "categories": categories,
            }
            # Do NOT return here — let finally close the connection first.
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to save lead transaction: {str(e)}")
        finally:
            conn.close()

        # Engine call happens after connection is fully closed.
        # Failure here must never break lead persistence.
        if _engine_payload:
            self._post_commit_generate_opportunities(_engine_payload)

        return _result_biz_id

    def _post_commit_generate_opportunities(self, engine_payload: dict) -> None:
        """Invokes the Intelligence Engine after the lead transaction has committed.

        Called immediately after save_lead_transaction returns, using a fresh
        connection to avoid SQLite write-lock contention.
        """
        try:
            from leadforge.opportunity_engine import OpportunityIntelligenceEngine
            engine = OpportunityIntelligenceEngine()
            engine.generate_for_business(engine_payload)
        except Exception:
            # Opportunity generation failure must never break lead persistence.
            pass

