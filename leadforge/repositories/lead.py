from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from datetime import datetime, timezone
import json
from leadforge.database import get_db_connection, uuidv7, append_event
from leadforge.repositories.base import LeadRepositoryInterface, RepositoryException
from leadforge.utils import clean_text, extract_place_id
from leadforge.normalizer import (
    canonical_phone,
    normalize_category,
    normalize_status,
)

# Whitelist of column names allowed in dynamic UPDATE clauses in save_merged_lead.
_ALLOWED_MERGE_COLUMNS = frozenset(
    {
        "google_place_id",
        "display_phone",
        "normalized_phone",
        "phone_candidates",
        "phone_source",
        "primary_platform",
        "website_domain",
        "rating",
        "review_count",
        "business_status",
        "opening_hours",
        "categories",
    }
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
    def check_duplicate(
        self, google_place_id: Optional[str], name: str, phone: Optional[str]
    ) -> bool:
        """Single authoritative duplicate check.

        Priority:
          1. Google Place ID exact match — strongest signal.
          2. canonical_phone exact match against indexed normalized_phone column.
          3. normalized_name + canonical_phone — name-based fallback.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # 1. Google Place ID (deterministic identifier)
            if google_place_id:
                cursor.execute(
                    "SELECT 1 FROM businesses WHERE google_place_id = ?",
                    (google_place_id,),
                )
                if cursor.fetchone():
                    return True

            # 2. Canonical phone — indexed, digits-only, format-independent
            norm_phone = canonical_phone(phone)
            if len(norm_phone) >= 7:
                cursor.execute(
                    "SELECT 1 FROM businesses WHERE normalized_phone = ?", (norm_phone,)
                )
                if cursor.fetchone():
                    return True

            # 3. Name + phone fallback
            normalized_name = (name or "").strip().lower()
            if normalized_name and norm_phone:
                cursor.execute(
                    "SELECT 1 FROM businesses WHERE normalized_name = ? AND normalized_phone = ?",
                    (normalized_name, norm_phone),
                )
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
            cursor.execute(
                """
                SELECT
                    b.id                           AS business_id,
                    b.name,
                    COALESCE(bt.name, '')          AS category,
                    COALESCE(b.display_phone, '')  AS phone,
                    COALESCE(b.phone_source, '')   AS phone_source,
                    b.phone_candidates,
                    COALESCE(b.primary_platform, '') AS primary_platform,
                    COALESCE(dp.website_url, '')   AS website,
                    COALESCE(a.address_line, '')   AS address,
                    COALESCE(a.area, '')           AS area,
                    b.rating,
                    b.review_count,
                    COALESCE(best.score, 0)        AS score,
                    COALESCE(o.title, '')          AS top_opportunity,
                    l.created_at                   AS discovery_date,
                    MAX(osl.reason)                AS notes,
                    COALESCE(dm.grade, '')         AS maturity_grade,
                    COALESCE(dm.maturity_score, 0) AS maturity_score
                FROM leads l
                JOIN businesses b ON l.business_id = b.id
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN addresses a ON b.id = a.business_id AND a.is_primary = 1
                LEFT JOIN digital_presences dp ON b.id = dp.business_id
                LEFT JOIN (
                    SELECT business_id, MAX(score) AS score
                    FROM opportunities
                    WHERE deleted_at IS NULL
                    GROUP BY business_id
                ) best ON b.id = best.business_id
                LEFT JOIN opportunities o ON o.business_id = b.id
                    AND o.score = best.score AND o.deleted_at IS NULL
                LEFT JOIN opportunity_scoring_logs osl ON o.id = osl.opportunity_id
                LEFT JOIN digital_maturities dm ON b.id = dm.business_id
                WHERE l.campaign_name = ?
                GROUP BY b.id
                ORDER BY COALESCE(best.score, 0) DESC
            """,
                (campaign_name,),
            )
            rows = cursor.fetchall()

            leads = []
            for row in rows:
                score = row["score"] or 0
                priority = "High" if score >= 60 else "Medium"

                disc_date = ""
                if row["discovery_date"]:
                    try:
                        disc_date = row["discovery_date"].split("T")[0]
                    except Exception:
                        disc_date = row["discovery_date"]

                # Parse phone candidates if JSON string
                cand_list = []
                if row["phone_candidates"]:
                    try:
                        cand_list = json.loads(row["phone_candidates"]) if isinstance(row["phone_candidates"], str) else row["phone_candidates"]
                    except Exception:
                        pass

                leads.append(
                    {
                        "business_id": row["business_id"],
                        "name": row["name"],
                        "category": row["category"],
                        "phone": row["phone"],
                        "phone_source": row["phone_source"],
                        "phone_candidates": cand_list,
                        "primary_platform": row["primary_platform"],
                        "website": row["website"],
                        "address": row["address"],
                        "area": row["area"],
                        "rating": row["rating"],
                        "review_count": row["review_count"],
                        "priority": priority,
                        "score": score,
                        "top_opportunity": row["top_opportunity"],
                        "maturity_grade": row["maturity_grade"],
                        "maturity_score": round(row["maturity_score"] or 0, 1),
                        "notes": row["notes"] or "",
                        "discovery_date": disc_date,
                    }
                )
            return leads
        except Exception as e:
            raise RepositoryException(
                f"Failed to query leads for campaign '{campaign_name}': {str(e)}"
            )
        finally:
            conn.close()

    def save_new_qualified_lead(
        self,
        lead_data: Dict[str, Any],
        opp_drafts: List[Any],
        maturity: Any,
        campaign_name: str,
        search_id: Optional[str] = None,
    ) -> str:
        """Atomically persists a new qualified business, address, presence, leads, maturity, and opportunities."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            conn.execute("BEGIN TRANSACTION;")

            # 1. Ensure business type exists
            category_name = normalize_category(lead_data.get("category", "General"))
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

            # 2. Insert business
            business_id = uuidv7()
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            google_place_id = lead_data.get("google_place_id")
            website_domain = lead_data.get("website_domain") or extract_domain(
                lead_data.get("website", "")
            )

            norm_phone = canonical_phone(lead_data.get("phone", ""))
            phone_cand = lead_data.get("phone_candidates")
            phone_cand_json = (
                json.dumps(phone_cand)
                if isinstance(phone_cand, (list, dict))
                else (phone_cand or None)
            )
            phone_source = lead_data.get("phone_source") or "google_maps"
            primary_platform = lead_data.get("primary_platform") or "google_maps"

            cursor.execute(
                """
                INSERT INTO businesses (
                    id, google_place_id, website_domain, normalized_name, name,
                    display_phone, normalized_phone, phone_candidates, phone_source, primary_platform, business_type_id,
                    rating, review_count, business_status, opening_hours, categories,
                    last_scraped_at, first_discovered_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    business_id,
                    google_place_id,
                    website_domain,
                    lead_data.get("name", "").strip().lower(),
                    lead_data.get("name"),
                    lead_data.get("phone"),
                    norm_phone or None,
                    phone_cand_json,
                    phone_source,
                    primary_platform,
                    business_type_id,
                    lead_data.get("rating"),
                    lead_data.get("review_count"),
                    normalize_status(lead_data.get("business_status")),
                    lead_data.get("opening_hours"),
                    lead_data.get("categories"),
                    now_str,
                    now_str,
                ),
            )

            append_event(
                event_type="BUSINESS_DISCOVERED",
                entity_type="Business",
                entity_id=business_id,
                payload={
                    "name": lead_data.get("name"),
                    "category": category_name,
                    "campaign": campaign_name,
                },
                conn=conn,
            )

            # 3. Insert Address
            cursor.execute(
                """
                INSERT INTO addresses (id, business_id, address_line, area, city, state, postal_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    uuidv7(),
                    business_id,
                    lead_data.get("address"),
                    lead_data.get("area"),
                    lead_data.get("city", ""),
                    lead_data.get("state", ""),
                    lead_data.get("postal_code", "") or "",
                ),
            )

            # 4. Insert Digital Presence
            website = lead_data.get("website", "")
            cursor.execute(
                """
                INSERT INTO digital_presences (id, business_id, website_url, has_website)
                VALUES (?, ?, ?, ?)
            """,
                (uuidv7(), business_id, website, 1 if website else 0),
            )

            # 5. Insert Lead entry
            cursor.execute("SELECT id FROM discovery_sources WHERE name = 'SCRAPER'")
            source_row = cursor.fetchone()
            source_id = (
                source_row[0] if source_row else "01907de3-bc42-7c89-8d76-5a507db4ef8f"
            )

            cursor.execute("SELECT id FROM lead_statuses WHERE name = 'OPEN'")
            status_row = cursor.fetchone()
            status_id = (
                status_row[0] if status_row else "01907de3-bc42-7c89-8d76-5a507db4f556"
            )

            # INSERT OR IGNORE: the unique index idx_leads_unique_business_campaign
            # enforces at most one row per (business_id, campaign_name).
            cursor.execute(
                """
                INSERT OR IGNORE INTO leads (id, business_id, source_id, status_id, campaign_name, search_history_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (uuidv7(), business_id, source_id, status_id, campaign_name, search_id),
            )

            # 6. Insert Digital Maturity
            if maturity:
                cursor.execute(
                    """
                    INSERT INTO digital_maturities (id, business_id, maturity_score, grade, details_json, audited_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        uuidv7(),
                        business_id,
                        maturity.score,
                        maturity.grade,
                        json.dumps(
                            {
                                "gaps": maturity.gaps,
                                "strengths": maturity.strengths,
                                "data_completeness": maturity.data_completeness,
                                "dimensions": [
                                    {
                                        "name": d.name,
                                        "score": d.score,
                                        "max_score": d.max_score,
                                        "gap": d.gap,
                                        "detail": d.detail,
                                    }
                                    for d in maturity.dimensions
                                ],
                            }
                        ),
                        now_str,
                    ),
                )

            # 7. Insert Opportunities and scoring logs
            if opp_drafts:
                for opp in opp_drafts:
                    opp_id = uuidv7()
                    cursor.execute(
                        """
                        INSERT INTO opportunities
                            (id, business_id, title, pipeline_stage, score, close_probability, estimated_value)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            opp_id,
                            business_id,
                            opp.title,
                            opp.pipeline_stage,
                            opp.score,
                            opp.close_probability,
                            opp.estimated_value,
                        ),
                    )

                    for entry in opp.signals:
                        cursor.execute(
                            """
                            INSERT INTO opportunity_scoring_logs
                                (id, opportunity_id, rule_name, score_delta, reason)
                            VALUES (?, ?, ?, ?, ?)
                        """,
                            (
                                uuidv7(),
                                opp_id,
                                entry.rule_name,
                                entry.score_delta,
                                entry.reason,
                            ),
                        )

            # 8. Update search history count
            if search_id:
                cursor.execute(
                    """
                    UPDATE search_history
                    SET new_businesses = COALESCE(new_businesses, 0) + 1
                    WHERE id = ?
                """,
                    (search_id,),
                )

            conn.commit()
            return business_id
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to save qualified lead: {str(e)}")
        finally:
            conn.close()

    def save_merged_lead(
        self,
        business_id: str,
        updates: Dict[str, Any],
        conflicts: List[tuple],
        lead_data: Dict[str, Any],
        campaign_name: str,
        search_id: Optional[str] = None,
        link_to_campaign: bool = True,
    ) -> None:
        """Atomically merges business fields, audits conflicts, and links a new lead entry.

        link_to_campaign=False: merge business data only; do not insert a leads
        row for this campaign.  Used by the control plane for historical duplicates
        that have not passed current-campaign validation.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            conn.execute("BEGIN TRANSACTION;")

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            # 1. Apply updates to fields — restrict to whitelisted columns
            if updates:
                # If display_phone is being updated, keep normalized_phone in sync
                if "display_phone" in updates:
                    updates["normalized_phone"] = (
                        canonical_phone(updates["display_phone"]) or None
                    )
                safe_updates = {
                    k: v for k, v in updates.items() if k in _ALLOWED_MERGE_COLUMNS
                }
                if safe_updates:
                    set_clause = ", ".join([f"{k} = ?" for k in safe_updates.keys()])
                    cursor.execute(
                        f"UPDATE businesses SET {set_clause}, last_scraped_at = ? WHERE id = ?",
                        list(safe_updates.values()) + [now_str, business_id],
                    )
                    save_status = "updated"
                else:
                    cursor.execute(
                        "UPDATE businesses SET last_scraped_at = ? WHERE id = ?",
                        (now_str, business_id),
                    )
                    save_status = "duplicate"
            else:
                cursor.execute(
                    "UPDATE businesses SET last_scraped_at = ? WHERE id = ?",
                    (now_str, business_id),
                )
                save_status = "duplicate"
            # 2. Record conflicts to audit logs and timeline
            if conflicts:
                conflict_desc = ", ".join(
                    [
                        f"{field}: '{before}' vs '{after}'"
                        for field, before, after in conflicts
                    ]
                )

                # Record audit log
                for field, before, after in conflicts:
                    cursor.execute(
                        """
                        INSERT INTO audit_logs (id, entity_type, entity_id, action_type, actor, before_state_json, after_state_json, client_metadata_json, occurred_at)
                        VALUES (?, 'businesses', ?, 'UPDATE', 'scraper', ?, ?, ?, ?)
                    """,
                        (
                            uuidv7(),
                            business_id,
                            f'{{"{field}": "{before}"}}',
                            f'{{"{field}": "{after}"}}',
                            '{"conflict": true, "reason": "Conflict detected during scraper pipeline run"}',
                            now_str,
                        ),
                    )

                # Record timeline event
                cursor.execute(
                    """
                    INSERT INTO activity_timeline (id, business_id, activity_type, title, description, occurred_at)
                    VALUES (?, ?, 'NOTE_ADDED', 'Data Conflict Detected', ?, ?)
                """,
                    (
                        uuidv7(),
                        business_id,
                        f"Scraped new values that conflict with existing values: {conflict_desc}",
                        now_str,
                    ),
                )

            # 3. Link campaign — only when the business has passed campaign validation.
            if link_to_campaign:
                cursor.execute(
                    "SELECT id FROM discovery_sources WHERE name = 'SCRAPER'"
                )
                source_row = cursor.fetchone()
                source_id = (
                    source_row[0]
                    if source_row
                    else "01907de3-bc42-7c89-8d76-5a507db4ef8f"
                )

                cursor.execute("SELECT id FROM lead_statuses WHERE name = 'OPEN'")
                status_row = cursor.fetchone()
                status_id = (
                    status_row[0]
                    if status_row
                    else "01907de3-bc42-7c89-8d76-5a507db4f556"
                )

                cursor.execute(
                    """
                    INSERT OR IGNORE INTO leads (id, business_id, source_id, status_id, campaign_name, search_history_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        uuidv7(),
                        business_id,
                        source_id,
                        status_id,
                        campaign_name,
                        search_id,
                    ),
                )

            # 4. Update search history counters
            if search_id:
                if save_status == "updated":
                    cursor.execute(
                        """
                        UPDATE search_history
                        SET updated_businesses = COALESCE(updated_businesses, 0) + 1
                        WHERE id = ?
                    """,
                        (search_id,),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE search_history
                        SET duplicate_detections = COALESCE(duplicate_detections, 0) + 1
                        WHERE id = ?
                    """,
                        (search_id,),
                    )

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to merge lead transaction: {str(e)}")
        finally:
            conn.close()

    def save_lead_transaction(
        self,
        lead_data: Dict[str, Any],
        campaign_name: str,
        search_id: Optional[str] = None,
    ) -> str:
        """Backward-compatible transaction orchestrator for testing and legacy workflows."""
        name = clean_text(lead_data.get("name", ""))
        phone = clean_text(lead_data.get("phone", ""))
        website = clean_text(lead_data.get("website", ""))
        address = clean_text(lead_data.get("address", ""))
        area = clean_text(lead_data.get("area", ""))
        category_name = clean_text(lead_data.get("category", "General"))
        source_url = lead_data.get("source_url", "")
        rating = lead_data.get("rating")
        review_count = lead_data.get("review_count")
        business_status = clean_text(lead_data.get("business_status", ""))
        opening_hours = lead_data.get("opening_hours", "")
        categories = lead_data.get("categories", "")

        google_place_id = extract_place_id(source_url)

        standard_lead = {
            "name": name,
            "phone": phone,
            "website": website,
            "address": address,
            "area": area,
            "category": category_name,
            "source_url": source_url,
            "google_place_id": google_place_id,
            "rating": rating,
            "review_count": review_count,
            "business_status": business_status,
            "opening_hours": opening_hours,
            "categories": categories,
        }

        # Check duplicate
        is_dup = self.check_duplicate(google_place_id, name, phone)
        if is_dup:
            business_id = self._find_existing_business_id(
                google_place_id, name, phone, address, area
            )
            existing_biz = self._get_existing_business_by_id(business_id)
            if existing_biz:
                from leadforge.merge import BusinessMerger

                merger = BusinessMerger()
                updates, conflicts = merger.merge(existing_biz, standard_lead)
                self.save_merged_lead(
                    business_id,
                    updates,
                    conflicts,
                    standard_lead,
                    campaign_name,
                    search_id,
                )

                # Perform post-commit opportunities check for backwards compatibility
                self._post_commit_generate_opportunities(
                    {
                        "business_id": business_id,
                        "name": name,
                        "category": category_name,
                        "website": website,
                        "contact_email": lead_data.get("contact_email", ""),
                        "phone": phone,
                        "rating": rating,
                        "review_count": review_count,
                        "business_status": business_status,
                        "categories": categories,
                    }
                )
                return business_id

        # New business! Evaluate opportunities & maturity using the engine
        from leadforge.opportunity_engine import OpportunityIntelligenceEngine

        engine = OpportunityIntelligenceEngine()
        opp_drafts, maturity = engine.evaluate_opportunities(standard_lead)

        business_id = self.save_new_qualified_lead(
            standard_lead, opp_drafts, maturity, campaign_name, search_id
        )
        return business_id

    def _find_existing_business_id(
        self, google_place_id, name, phone, address, area
    ) -> Optional[str]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            normalized_name = (name or "").strip().lower()
            norm_phone = canonical_phone(phone)

            # 1. Google Place ID
            if google_place_id:
                cursor.execute(
                    "SELECT id FROM businesses WHERE google_place_id = ?",
                    (google_place_id,),
                )
                row = cursor.fetchone()
                if row:
                    return row[0]

            # 2. Canonical phone (indexed)
            if len(norm_phone) >= 7:
                cursor.execute(
                    "SELECT id FROM businesses WHERE normalized_phone = ?",
                    (norm_phone,),
                )
                row = cursor.fetchone()
                if row:
                    return row[0]

            # 3. Name + Area
            if normalized_name and area:
                cursor.execute(
                    """
                    SELECT b.id FROM businesses b
                    JOIN addresses a ON b.id = a.business_id
                    WHERE b.normalized_name = ? AND LOWER(TRIM(a.area)) = ?
                """,
                    (normalized_name, area.strip().lower()),
                )
                row = cursor.fetchone()
                if row:
                    return row[0]

            # 4. Name + Address
            if normalized_name and address:
                cursor.execute(
                    """
                    SELECT b.id FROM businesses b
                    JOIN addresses a ON b.id = a.business_id
                    WHERE b.normalized_name = ? AND LOWER(TRIM(a.address_line)) = ?
                """,
                    (normalized_name, address.strip().lower()),
                )
                row = cursor.fetchone()
                if row:
                    return row[0]

            return None
        finally:
            conn.close()

    def _get_existing_business_by_id(
        self, business_id: str
    ) -> Optional[Dict[str, Any]]:
        if not business_id:
            return None
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, google_place_id, name, display_phone, phone_source, phone_candidates, primary_platform, website_domain, rating, review_count, business_status, opening_hours, categories
                FROM businesses WHERE id = ?
            """,
                (business_id,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()

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
