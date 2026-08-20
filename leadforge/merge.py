"""Merge module for LeadForge V3.0 architecture.

ONLY determines canonical business identity, merges fields, and resolves conflicts.
NEVER: scrapes, validates, scores, or generates opportunities.
"""

from typing import Dict, Any, List, Tuple
from leadforge.normalizer import normalize_phone, normalize_status


class BusinessMerger:
    """Handles field merging and conflict identification for duplicate business records."""

    def merge(
        self, existing: Dict[str, Any], incoming: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Tuple[str, Any, Any]]]:
        """Compares existing database record with incoming scraped data.

        Returns:
            A tuple of (updates, conflicts)
            - updates: dict of fields that should be updated in the database (i.e. fields that were empty in DB but exist in scrape)
            - conflicts: list of tuples (field_name, existing_value, incoming_value) for conflicting non-empty fields
        """
        updates = {}
        conflicts = []

        def merge_field(
            field_name: str,
            existing_val: Any,
            incoming_val: Any,
            normalizer=None,
            overwrite: bool = False,
        ):
            """Fill empty fields; for non-empty conflicts either overwrite or log."""
            if incoming_val is not None and incoming_val != "":
                norm_incoming = normalizer(incoming_val) if normalizer else incoming_val
                norm_existing = normalizer(existing_val) if normalizer else existing_val
                if not existing_val:
                    updates[field_name] = incoming_val
                elif norm_existing != norm_incoming:
                    if overwrite:
                        updates[field_name] = incoming_val
                    else:
                        conflicts.append((field_name, existing_val, incoming_val))

        # 1. Google Place ID — immutable once set; conflicts logged only
        merge_field(
            "google_place_id",
            existing.get("google_place_id"),
            incoming.get("google_place_id"),
        )

        # 2. Display Phone — overwrite: newer scrape reflects current number
        incoming_phone = incoming.get("phone") or incoming.get("display_phone")
        merge_field(
            "display_phone",
            existing.get("display_phone"),
            incoming_phone,
            normalizer=normalize_phone,
            overwrite=True,
        )

        # 3. Website Domain — logged; domain changes are meaningful events
        merge_field(
            "website_domain",
            existing.get("website_domain"),
            incoming.get("website_domain"),
        )

        # 4. Rating — conflict-logged: changes are meaningful audit events
        merge_field("rating", existing.get("rating"), incoming.get("rating"))

        # 5. Review Count — conflict-logged: changes are meaningful audit events
        merge_field(
            "review_count", existing.get("review_count"), incoming.get("review_count")
        )

        # 6. Business Status — overwrite: closure/re-opening must propagate
        incoming_status = incoming.get("business_status") or incoming.get("status")
        merge_field(
            "business_status",
            existing.get("business_status"),
            incoming_status,
            normalizer=normalize_status,
            overwrite=True,
        )

        # 7. Opening Hours — fill-only; hours change frequently, log conflicts
        merge_field(
            "opening_hours",
            existing.get("opening_hours"),
            incoming.get("opening_hours"),
        )

        # 8. Categories — fill-only
        merge_field(
            "categories", existing.get("categories"), incoming.get("categories")
        )

        # 9. Phone candidates & source — merge and update
        incoming_cand = incoming.get("phone_candidates")
        if incoming_cand:
            existing_cand_raw = existing.get("phone_candidates") or "[]"
            try:
                import json
                existing_list = json.loads(existing_cand_raw) if isinstance(existing_cand_raw, str) else list(existing_cand_raw)
                incoming_list = json.loads(incoming_cand) if isinstance(incoming_cand, str) else list(incoming_cand)
                
                # Combine unique by canonical or phone
                seen_canons = {c.get("canonical") or c.get("phone") for c in existing_list if isinstance(c, dict)}
                for inc_item in incoming_list:
                    key = (inc_item.get("canonical") or inc_item.get("phone")) if isinstance(inc_item, dict) else None
                    if key and key not in seen_canons:
                        existing_list.append(inc_item)
                        seen_canons.add(key)
                updates["phone_candidates"] = json.dumps(existing_list)
            except Exception:
                updates["phone_candidates"] = json.dumps(incoming_cand) if not isinstance(incoming_cand, str) else incoming_cand

        if incoming.get("phone_source") and incoming.get("phone_source") != existing.get("phone_source"):
            updates["phone_source"] = incoming.get("phone_source")

        if incoming.get("primary_platform") and incoming.get("primary_platform") != existing.get("primary_platform"):
            updates["primary_platform"] = incoming.get("primary_platform")

        return updates, conflicts
