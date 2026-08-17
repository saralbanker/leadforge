"""Deterministic Lead Prioritization Engine for LeadForge.

Provides a pure, rule-based, explainable scoring engine to rank opportunities
based strictly on structured business evidence without AI/LLM non-determinism.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PriorityResult:
    """Result of deterministic lead prioritization scoring."""

    overall_score: float
    priority_tier: str  # CRITICAL, HIGH, MEDIUM, LOW
    score_breakdown: Dict[str, float]
    explanation: List[str]


class LeadPrioritizationEngine:
    """Pure, rule-based deterministic Lead Prioritization Engine.

    Scores leads from 0.0 to 100.0 based on 5 structured categories:
    1. Digital Presence & Quality (Max 30 pts)
    2. Digital Maturity Assessment (Max 20 pts)
    3. Reputation & Review Signals (Max 20 pts)
    4. Contact Availability & Reachability (Max 15 pts)
    5. Category & Opportunity Value (Max 15 pts)
    """

    HIGH_VALUE_CATEGORIES = {
        "dentist",
        "dentists",
        "lawyer",
        "attorney",
        "hvac",
        "roofing",
        "plumbing",
        "medical",
        "clinic",
        "orthodontist",
    }
    MEDIUM_VALUE_CATEGORIES = {
        "restaurant",
        "auto repair",
        "salon",
        "spa",
        "gym",
        "chiropractor",
    }

    @classmethod
    def calculate_priority(cls, business_data: Dict[str, Any]) -> PriorityResult:
        """Calculates deterministic priority score, breakdown, tier, and explanation.

        *business_data* can contain:
          - website, has_website, ssl_valid, load_time_seconds
          - rating, review_count
          - contact_email, phone
          - category, google_primary_category
          - maturity_score, maturity_grade
          - estimated_value
        """
        breakdown: Dict[str, float] = {}
        explanations: List[str] = []

        # 1. Digital Presence & Quality (Max 30 pts)
        digital_score, digital_reasons = cls._score_digital_presence(business_data)
        breakdown["digital_presence"] = digital_score
        explanations.extend(digital_reasons)

        # 2. Digital Maturity Assessment (Max 20 pts)
        maturity_score, maturity_reasons = cls._score_digital_maturity(business_data)
        breakdown["digital_maturity"] = maturity_score
        explanations.extend(maturity_reasons)

        # 3. Reputation & Review Signals (Max 20 pts)
        reputation_score, reputation_reasons = cls._score_reputation(business_data)
        breakdown["reputation"] = reputation_score
        explanations.extend(reputation_reasons)

        # 4. Contact Reachability (Max 15 pts)
        contact_score, contact_reasons = cls._score_contact_reachability(business_data)
        breakdown["contact_reachability"] = contact_score
        explanations.extend(contact_reasons)

        # 5. Opportunity & Category Value (Max 15 pts)
        category_score, category_reasons = cls._score_category_value(business_data)
        breakdown["category_value"] = category_score
        explanations.extend(category_reasons)

        # Total Calculation clipped to [0.0, 100.0]
        total_raw = sum(breakdown.values())
        overall_score = round(max(0.0, min(100.0, total_raw)), 1)

        # Priority Tier Assignment (Deterministic 4-tier model)
        if overall_score >= 80.0:
            priority_tier = "CRITICAL"
        elif overall_score >= 60.0:
            priority_tier = "HIGH"
        elif overall_score >= 40.0:
            priority_tier = "MEDIUM"
        else:
            priority_tier = "LOW"

        return PriorityResult(
            overall_score=overall_score,
            priority_tier=priority_tier,
            score_breakdown=breakdown,
            explanation=explanations,
        )

    @classmethod
    def _score_digital_presence(cls, data: Dict[str, Any]) -> tuple[float, List[str]]:
        reasons = []
        website = (data.get("website") or data.get("website_domain") or "").strip()
        has_website = data.get("has_website")
        if has_website is None:
            has_website = bool(website)

        if not has_website:
            reasons.append("No website found (+30.0 pts: Prime digital transformation prospect)")
            return 30.0, reasons

        # Website exists - evaluate audit quality metrics
        score = 5.0
        reasons.append("Website exists (+5.0 pts base digital presence)")

        ssl_valid = data.get("ssl_valid")
        if ssl_valid is False:
            score += 15.0
            reasons.append("SSL invalid/missing (+15.0 pts: Security upgrade opportunity)")

        load_time = data.get("load_time_seconds")
        if load_time is not None:
            try:
                lt = float(load_time)
                if lt > 3.0:
                    score += 10.0
                    reasons.append(f"Slow load speed {lt:.1f}s (+10.0 pts: Performance optimization opportunity)")
            except (ValueError, TypeError):
                pass

        return min(30.0, score), reasons

    @classmethod
    def _score_digital_maturity(cls, data: Dict[str, Any]) -> tuple[float, List[str]]:
        reasons = []
        mat_grade = (data.get("maturity_grade") or "").strip().upper()
        mat_score = data.get("maturity_score")

        if mat_grade in ("F", "D") or (mat_score is not None and float(mat_score) < 40.0):
            reasons.append("Low digital maturity (+20.0 pts: High modernization upside)")
            return 20.0, reasons
        elif mat_grade == "C" or (mat_score is not None and 40.0 <= float(mat_score) < 60.0):
            reasons.append("Moderate digital maturity (+12.0 pts: Upgrade opportunity)")
            return 12.0, reasons
        elif mat_grade in ("A", "B") or (mat_score is not None and float(mat_score) >= 60.0):
            reasons.append("High digital maturity (+5.0 pts: Optimization opportunity)")
            return 5.0, reasons

        # Default fallback if maturity not assessed yet
        reasons.append("Unassessed digital maturity (+10.0 pts neutral default)")
        return 10.0, reasons

    @classmethod
    def _score_reputation(cls, data: Dict[str, Any]) -> tuple[float, List[str]]:
        reasons = []
        rating_raw = data.get("rating")
        reviews_raw = data.get("review_count") or data.get("reviews")

        try:
            rating = float(rating_raw) if rating_raw is not None else None
        except (ValueError, TypeError):
            rating = None

        try:
            reviews = int(reviews_raw) if reviews_raw is not None else None
        except (ValueError, TypeError):
            reviews = None

        if reviews is not None and reviews > 50 and rating is not None and rating < 4.0:
            reasons.append(f"High review volume ({reviews}) with sub-4.0 rating ({rating:.1f}) (+20.0 pts: Urgent reputation overhaul)")
            return 20.0, reasons
        elif reviews is not None and reviews >= 20:
            reasons.append(f"Established business ({reviews} reviews) (+15.0 pts: Strong market validation)")
            return 15.0, reasons
        elif reviews is not None and reviews >= 5:
            reasons.append(f"Growing business ({reviews} reviews) (+10.0 pts: Active operations)")
            return 10.0, reasons
        elif reviews is not None:
            reasons.append(f"Low review volume ({reviews} reviews) (+5.0 pts)")
            return 5.0, reasons

        reasons.append("No review data (+5.0 pts baseline)")
        return 5.0, reasons

    @classmethod
    def _score_contact_reachability(cls, data: Dict[str, Any]) -> tuple[float, List[str]]:
        reasons = []
        email_raw = data.get("contact_email") or data.get("discovered_email") or ""
        phone_raw = data.get("phone") or ""

        email = str(email_raw).strip() if email_raw else ""
        phone = str(phone_raw).strip() if phone_raw else ""

        has_email = bool(email)
        has_phone = len("".join([c for c in phone if c.isdigit()])) >= 7


        if has_email and has_phone:
            reasons.append("Direct email and phone available (+15.0 pts: Fully actionable lead)")
            return 15.0, reasons
        elif has_phone:
            reasons.append("Callable phone available (+10.0 pts: Phone outreach actionable)")
            return 10.0, reasons
        elif has_email:
            reasons.append("Email contact available (+8.0 pts: Direct email actionable)")
            return 8.0, reasons

        reasons.append("No direct contact evidence (+0.0 pts: Actionability restricted)")
        return 0.0, reasons

    @classmethod
    def _score_category_value(cls, data: Dict[str, Any]) -> tuple[float, List[str]]:
        reasons = []
        category = (data.get("category") or data.get("google_primary_category") or "").strip().lower()

        is_high = any(c in category for c in cls.HIGH_VALUE_CATEGORIES)
        is_med = any(c in category for c in cls.MEDIUM_VALUE_CATEGORIES)

        if is_high:
            reasons.append(f"High-value category '{category}' (+15.0 pts: High ACV service fit)")
            return 15.0, reasons
        elif is_med:
            reasons.append(f"Medium-value category '{category}' (+10.0 pts: Moderate ACV service fit)")
            return 10.0, reasons

        reasons.append(f"Standard category '{category}' (+5.0 pts: Baseline service fit)")
        return 5.0, reasons
