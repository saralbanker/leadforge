"""Phone Candidate Aggregator and Multi-Platform Prioritization Engine."""

import json
from typing import List, Dict, Any, Optional, Tuple

from leadforge.enrichment.phone_providers.base import PhoneResult
from leadforge.normalizer import canonical_phone, normalize_phone


def classify_indian_phone(phone_str: str, canon: str) -> Tuple[str, bool]:
    """Deterministically identifies phone type (MOBILE, LANDLINE, VIRTUAL_PBX, TOLL_FREE)."""
    if not canon or len(canon) < 7:
        return "UNKNOWN", False

    digits = canon
    if digits.startswith("1800") or digits.startswith("1860") or digits.startswith("911800"):
        return "TOLL_FREE", False

    # IndiaMART Virtual PBX (Bangalore STD 080 + 4xxx series)
    if (
        digits.startswith("91804")
        or digits.startswith("0804")
        or digits.startswith("804")
        or phone_str.strip().startswith("0804")
    ):
        return "VIRTUAL_PBX", False

    # Prominent Indian industrial city STD codes (2-digit after 91)
    std_codes = {"11", "22", "33", "44", "80", "40", "20", "79", "71", "72"}
    if len(digits) == 12 and digits.startswith("91"):
        if digits[2:4] in std_codes:
            return "LANDLINE", False
        if digits[2] in "6789":
            return "MOBILE", True
        return "LANDLINE", False

    if len(digits) == 10:
        if digits[:2] in std_codes:
            return "LANDLINE", False
        if digits[0] in "6789":
            return "MOBILE", True
        return "LANDLINE", False

    return "LANDLINE", False


class PhoneCandidateAggregator:
    """Ranks, deduplicates, and aggregates phone numbers from multi-platform scrapers."""

    def aggregate(
        self,
        candidate_results: List[PhoneResult],
        initial_phone: Optional[str] = None,
        initial_source: str = "google_maps",
    ) -> Tuple[Optional[str], Optional[str], Optional[str], List[Dict[str, Any]]]:
        """Aggregates all discovered candidate phone numbers.

        Returns:
            Tuple of:
            (primary_display_phone, primary_source, canonical_primary_phone, phone_candidates_list)
        """
        all_candidates: List[PhoneResult] = list(candidate_results)

        # Include initial phone from primary discovery if present
        if initial_phone:
            canon = canonical_phone(initial_phone)
            if len(canon) >= 7:
                p_type, is_mob = classify_indian_phone(initial_phone, canon)
                all_candidates.append(
                    PhoneResult(
                        phone=normalize_phone(initial_phone),
                        phone_type=p_type,
                        source_provider=initial_source,
                        source_url="",
                        confidence_score=0.92 if is_mob else (0.75 if p_type == "VIRTUAL_PBX" else 0.85),
                        is_mobile=is_mob,
                        raw_text=initial_phone,
                    )
                )

        if not all_candidates:
            return None, None, None, []

        # Deduplicate candidates by canonical representation, keeping highest confidence
        unique_by_canon: Dict[str, PhoneResult] = {}
        for cand in all_candidates:
            c = canonical_phone(cand.phone)
            if not c or len(c) < 7:
                continue

            if c not in unique_by_canon:
                unique_by_canon[c] = cand
            else:
                # Replace if higher confidence
                if cand.confidence_score > unique_by_canon[c].confidence_score:
                    unique_by_canon[c] = cand

        if not unique_by_canon:
            return None, None, None, []

        # Sort candidates:
        # 1. is_mobile (True first)
        # 2. confidence_score (Highest first)
        # 3. Not TOLL_FREE
        def sort_key(item: Tuple[str, PhoneResult]):
            cand = item[1]
            mobile_rank = 2 if cand.is_mobile else (0 if cand.phone_type == "TOLL_FREE" else 1)
            return (mobile_rank, cand.confidence_score)

        sorted_items = sorted(unique_by_canon.items(), key=sort_key, reverse=True)
        top_canon, top_result = sorted_items[0]

        candidates_data: List[Dict[str, Any]] = []
        for c_key, c_res in sorted_items:
            candidates_data.append(
                {
                    "phone": c_res.phone,
                    "canonical": c_key,
                    "phone_type": c_res.phone_type,
                    "source": c_res.source_provider,
                    "source_url": c_res.source_url,
                    "confidence": round(c_res.confidence_score, 2),
                    "is_mobile": c_res.is_mobile,
                }
            )

        return (
            top_result.phone,
            top_result.source_provider,
            top_canon,
            candidates_data,
        )
