"""Validator module for LeadForge V3.0/3.1/3.2 architecture.

ONLY checks if a business is qualified based on the target criteria.
Returns "PASS" or a specific rejection reason string.
NEVER: scores, merges, persists, or modifies business state.

Rejection reasons (returned instead of generic "FAIL"):
    NO_NAME              — business name missing
    NO_PHONE             — phone number absent or too short to be callable
    PERMANENTLY_CLOSED   — business is permanently closed
    WRONG_STATUS         — status not in the accepted set (default: OPERATIONAL only)
    GHOST_LISTING        — every enrichment field missing (rating, reviews,
                           address, opening hours, categories)
    CATEGORY_UNVERIFIED  — Google category could not be extracted; category
                           match cannot be verified (precision-first reject)
    WRONG_CATEGORY       — Google's category doesn't match the requested one
    NO_ADDRESS           — city validation requested but no address scraped
    WRONG_CITY           — PIN prefix or address doesn't match target city
    HAS_WEBSITE          — business has a website (no_website_only filter)
    BELOW_MIN_RATING     — rating below minimum threshold or missing while
                           the filter is enabled
    BELOW_MIN_REVIEWS    — review count below minimum threshold or missing
                           while the filter is enabled
    WRONG_AREA           — area doesn't match required_area filter

Validation compares the REQUESTED category/city against SCRAPED evidence only
(google_primary_category, scraped categories list, address, postal code).
It never compares a requested value against itself.
"""

import json
from typing import Dict, Any, List, Optional

from leadforge.config import DEFAULT_CITY_PIN_PREFIXES
from leadforge.parser import extract_postal_code


def _category_matches(target: str, candidate: str) -> bool:
    """Deterministic substring category match (existing precision policy)."""
    if not candidate:
        return False
    return (
        target in candidate
        or candidate in target
        or (len(target) > 4 and target[:4] in candidate)
    )


class BusinessValidator:
    """Validator for business records.

    Checks if a business meets campaign criteria.
    """

    def validate(
        self,
        business_data: Dict[str, Any],
        no_website_only: bool = False,
        target_city: str = None,
        target_category: str = None,
        min_rating: float = None,
        min_reviews: int = None,
        required_status: str = None,
        required_area: str = None,
        allow_temporarily_closed: bool = False,
        pin_prefix_map: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """Validates a business against criteria.

        Returns:
            "PASS" if qualified.
            A specific rejection reason string if unqualified (e.g. "NO_PHONE").
        """
        # 1. Business Name must exist
        name = (business_data.get("name") or "").strip()
        if not name:
            return "NO_NAME"

        # 2. Valid Phone Number must exist & must be callable
        phone = (business_data.get("phone") or "").strip()
        if not phone:
            return "NO_PHONE"

        # Strip all formatting to check if phone has enough digits to be callable.
        # 7 is the ITU minimum for any assigned number (short-codes excluded).
        phone_digits = "".join([c for c in phone if c.isdigit()])
        if len(phone_digits) < 7:
            return "NO_PHONE"

        # 3. Check operational status.
        # Default accepted status is OPERATIONAL only; TEMPORARILY_CLOSED fails
        # unless explicitly allowed. Empty status is treated as OPERATIONAL
        # (normalize_status maps "" the same way upstream).
        status = (business_data.get("business_status") or "").upper()
        if status == "PERMANENTLY_CLOSED":
            return "PERMANENTLY_CLOSED"

        if required_status:
            req_status = required_status.strip().upper()
            if status != req_status:
                return "WRONG_STATUS"
        else:
            accepted = {"OPERATIONAL", ""}
            if allow_temporarily_closed:
                accepted.add("TEMPORARILY_CLOSED")
            if status not in accepted:
                return "WRONG_STATUS"

        # 4. Ghost listing detection — every enrichment field missing means the
        # listing carries no verifiable evidence; precision-first reject.
        scraped_cats = self._parse_categories(business_data)
        google_primary = (
            (business_data.get("google_primary_category") or "").strip().lower()
        )
        address_raw = (business_data.get("address") or "").strip()
        has_any_category = bool(scraped_cats) or bool(google_primary)
        if (
            business_data.get("rating") is None
            and business_data.get("review_count") is None
            and not address_raw
            and not (business_data.get("opening_hours") or "").strip()
            and not has_any_category
        ):
            return "GHOST_LISTING"

        # 5. Correct Category — requested category vs Google's extracted
        # categories ONLY. The requested category is never compared against
        # a field that was seeded from the request itself.
        if target_category:
            norm_target = target_category.strip().lower()
            if not has_any_category:
                return "CATEGORY_UNVERIFIED"

            candidates = list(scraped_cats)
            if google_primary:
                candidates.insert(0, google_primary)
            matched = any(
                _category_matches(norm_target, (c or "").strip().lower())
                for c in candidates
            )
            if not matched:
                return "WRONG_CATEGORY"

        # 6. Correct City — PIN-prefix mapping first, address comparison as
        # fallback. The scraped address is the only location evidence used.
        if target_city:
            city_norm = target_city.strip().lower()
            if not address_raw:
                return "NO_ADDRESS"

            postal_code = (business_data.get("postal_code") or "").strip()
            if not postal_code:
                postal_code = extract_postal_code(address_raw)

            prefix_map = (
                pin_prefix_map
                if pin_prefix_map is not None
                else DEFAULT_CITY_PIN_PREFIXES
            )
            prefixes = prefix_map.get(city_norm)

            if postal_code and prefixes:
                if not any(postal_code.startswith(p) for p in prefixes):
                    return "WRONG_CITY"
            elif city_norm not in address_raw.lower():
                return "WRONG_CITY"

        # 7. Apply User Filters
        # No Website Only filter
        if no_website_only:
            website = (business_data.get("website") or "").strip()
            if website:
                return "HAS_WEBSITE"

        # Minimum Rating filter — an enabled filter is never bypassed:
        # a missing rating fails validation.
        if min_rating is not None:
            rating = business_data.get("rating")
            try:
                if rating is None or float(rating) < float(min_rating):
                    return "BELOW_MIN_RATING"
            except (ValueError, TypeError):
                return "BELOW_MIN_RATING"

        # Minimum Reviews filter — missing review count fails when enabled.
        if min_reviews is not None:
            reviews = business_data.get("review_count")
            try:
                if reviews is None or int(reviews) < int(min_reviews):
                    return "BELOW_MIN_REVIEWS"
            except (ValueError, TypeError):
                return "BELOW_MIN_REVIEWS"

        # Required Area filter
        if required_area:
            area_norm = required_area.strip().lower()
            area_field = (business_data.get("area") or "").strip().lower()
            addr = address_raw.lower()
            if area_norm not in area_field and area_norm not in addr:
                return "WRONG_AREA"

        return "PASS"

    @staticmethod
    def _parse_categories(business_data: Dict[str, Any]) -> List[str]:
        """Parse the scraped categories field (JSON string or list) safely."""
        raw = business_data.get("categories") or "[]"
        try:
            cats = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            cats = []
        return [c for c in cats if (c or "").strip()] if isinstance(cats, list) else []
