"""Digital Maturity Assessor — Phase 4.

Produces a structured digital maturity profile for a business using only
signals already available from the scraper pipeline.  No inference.

Maturity dimensions
-------------------
WEB_PRESENCE    — does the business have a website at all?
SEARCH_SIGNAL   — Google Maps review count → indexability/visibility
REPUTATION      — star rating → customer satisfaction signal
CONTACT_REACH   — email + phone availability → outreach viability
DATA_RICHNESS   — completeness of business metadata fields

Grade mapping  (configurable via settings)
-------------
A  ≥ 80 pts   — digitally mature; upgrade/augment opportunities
B  ≥ 60 pts   — adequate digital presence; targeted improvement opportunities
C  ≥ 40 pts   — significant gaps; high service opportunity
D  ≥ 20 pts   — severely underdeveloped; strong website + GMB opportunity
F  <  20 pts  — no meaningful digital presence; maximum lead value

Usage::

    assessor = DigitalMaturityAssessor()
    profile = assessor.assess(business_data)
    # profile.grade, profile.score, profile.gaps, profile.explanation

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from leadforge.repositories.settings import SQLiteSettingsRepository


# ── Value Objects ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MaturityDimension:
    """One measurable digital dimension."""
    name: str
    score: float          # 0.0–25.0 per dimension (4 dims × 25 = 100 max)
    max_score: float
    gap: bool             # True → this dimension has a detectable gap
    detail: str           # Human-readable rationale


@dataclass
class MaturityProfile:
    """Full digital maturity assessment for one business."""
    score: float                             # 0.0–100.0
    grade: str                               # A/B/C/D/F
    dimensions: List[MaturityDimension] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    explanation: str = ""
    data_completeness: float = 0.0          # 0.0–1.0 fraction of known fields


# ── Assessor ──────────────────────────────────────────────────────────────────

class DigitalMaturityAssessor:
    """Assesses a business's digital maturity from scraper-provided metadata.

    Deterministic: identical input always produces identical output.
    Configurable: grade thresholds and dimension weights are read from settings.
    """

    _DIM_MAX = 25.0   # max points per dimension; 4 dims × 25 = 100 max total

    def __init__(self, settings_repo: Optional[SQLiteSettingsRepository] = None) -> None:
        self._settings = settings_repo or SQLiteSettingsRepository()

    def assess(self, business_data: Dict[str, Any]) -> MaturityProfile:
        """Compute the full maturity profile for one business."""
        thresholds = self._load_thresholds()

        dims: List[MaturityDimension] = [
            self._dim_web_presence(business_data),
            self._dim_search_signal(business_data, thresholds),
            self._dim_reputation(business_data, thresholds),
            self._dim_contact_reach(business_data),
        ]

        total = sum(d.score for d in dims)
        grade = self._to_grade(total, thresholds)
        completeness = self._data_completeness(business_data)

        gaps = [d.detail for d in dims if d.gap]
        strengths = [d.detail for d in dims if not d.gap]
        explanation = self._build_explanation(business_data, dims, total, grade, completeness)

        return MaturityProfile(
            score=round(total, 2),
            grade=grade,
            dimensions=dims,
            gaps=gaps,
            strengths=strengths,
            explanation=explanation,
            data_completeness=round(completeness, 3),
        )

    # ── Dimensions ────────────────────────────────────────────────────────────

    def _dim_web_presence(self, biz: Dict[str, Any]) -> MaturityDimension:
        website = (biz.get("website") or "").strip()
        if website:
            return MaturityDimension(
                name="WEB_PRESENCE",
                score=self._DIM_MAX,
                max_score=self._DIM_MAX,
                gap=False,
                detail=f"Website detected ({website}) — strong web presence.",
            )
        return MaturityDimension(
            name="WEB_PRESENCE",
            score=0.0,
            max_score=self._DIM_MAX,
            gap=True,
            detail="No website found — major digital gap. Website build is the primary recommendation.",
        )

    def _dim_search_signal(
        self, biz: Dict[str, Any], thresholds: Dict[str, float]
    ) -> MaturityDimension:
        review_count = biz.get("review_count")
        high_t = int(thresholds.get("review_high_threshold", 100))
        mid_t = int(thresholds.get("review_mid_threshold", 10))

        try:
            rc = int(review_count) if review_count is not None else 0
        except (TypeError, ValueError):
            rc = 0

        if rc >= high_t:
            return MaturityDimension(
                name="SEARCH_SIGNAL",
                score=self._DIM_MAX,
                max_score=self._DIM_MAX,
                gap=False,
                detail=f"{rc} reviews — high Maps visibility and customer engagement.",
            )
        elif rc >= mid_t:
            score = self._DIM_MAX * 0.6
            return MaturityDimension(
                name="SEARCH_SIGNAL",
                score=score,
                max_score=self._DIM_MAX,
                gap=False,
                detail=f"{rc} reviews — moderate Maps presence.",
            )
        elif rc > 0:
            score = self._DIM_MAX * 0.25
            return MaturityDimension(
                name="SEARCH_SIGNAL",
                score=score,
                max_score=self._DIM_MAX,
                gap=True,
                detail=f"{rc} reviews — very low Maps visibility. GMB optimisation recommended.",
            )
        return MaturityDimension(
            name="SEARCH_SIGNAL",
            score=0.0,
            max_score=self._DIM_MAX,
            gap=True,
            detail="No reviews — business is not visible or indexed on Google Maps.",
        )

    def _dim_reputation(
        self, biz: Dict[str, Any], thresholds: Dict[str, float]
    ) -> MaturityDimension:
        rating = biz.get("rating")
        high_r = thresholds.get("rating_high_threshold", 4.2)
        mid_r = thresholds.get("rating_mid_threshold", 3.5)
        low_r = thresholds.get("rating_low_threshold", 3.0)

        if rating is None:
            return MaturityDimension(
                name="REPUTATION",
                score=self._DIM_MAX * 0.4,  # partial — unknown is not bad
                max_score=self._DIM_MAX,
                gap=False,
                detail="No rating data available — cannot assess reputation.",
            )

        try:
            r = float(rating)
        except (TypeError, ValueError):
            return MaturityDimension(
                name="REPUTATION",
                score=self._DIM_MAX * 0.4,
                max_score=self._DIM_MAX,
                gap=False,
                detail="Rating data unreadable.",
            )

        if r >= high_r:
            return MaturityDimension(
                name="REPUTATION",
                score=self._DIM_MAX,
                max_score=self._DIM_MAX,
                gap=False,
                detail=f"Rating {r:.1f} ≥ {high_r} — strong online reputation.",
            )
        elif r >= mid_r:
            return MaturityDimension(
                name="REPUTATION",
                score=self._DIM_MAX * 0.7,
                max_score=self._DIM_MAX,
                gap=False,
                detail=f"Rating {r:.1f} — acceptable reputation, room for improvement.",
            )
        elif r >= low_r:
            return MaturityDimension(
                name="REPUTATION",
                score=self._DIM_MAX * 0.35,
                max_score=self._DIM_MAX,
                gap=True,
                detail=f"Rating {r:.1f} — below average. Reputation management opportunity.",
            )
        return MaturityDimension(
            name="REPUTATION",
            score=0.0,
            max_score=self._DIM_MAX,
            gap=True,
            detail=f"Rating {r:.1f} < {low_r} — poor reputation. High-risk lead for digital services.",
        )

    def _dim_contact_reach(self, biz: Dict[str, Any]) -> MaturityDimension:
        email = (biz.get("contact_email") or "").strip()
        phone = (biz.get("phone") or "").strip()

        score = 0.0
        parts = []
        if email:
            score += self._DIM_MAX * 0.6
            parts.append("email")
        if phone:
            score += self._DIM_MAX * 0.4
            parts.append("phone")

        if score >= self._DIM_MAX:
            detail = "Email + phone available — full outreach capability."
            gap = False
        elif score > 0:
            detail = f"{', '.join(parts).capitalize()} available — partial contact reachability."
            gap = not bool(email)  # Missing email = gap (email is primary)
        else:
            detail = "No contact details available — cold outreach only."
            gap = True

        return MaturityDimension(
            name="CONTACT_REACH",
            score=min(score, self._DIM_MAX),
            max_score=self._DIM_MAX,
            gap=gap,
            detail=detail,
        )

    # ── Data Completeness ─────────────────────────────────────────────────────

    def _data_completeness(self, biz: Dict[str, Any]) -> float:
        """Fraction of known key fields.  0.0 = no data, 1.0 = all fields present."""
        fields = ["name", "website", "phone", "contact_email", "rating", "review_count",
                  "business_status", "categories"]
        present = sum(1 for f in fields if biz.get(f))
        return present / len(fields)

    # ── Grade + Explainability ────────────────────────────────────────────────

    def _to_grade(self, score: float, thresholds: Dict[str, float]) -> str:
        if score >= thresholds.get("grade_a", 80.0):
            return "A"
        if score >= thresholds.get("grade_b", 60.0):
            return "B"
        if score >= thresholds.get("grade_c", 40.0):
            return "C"
        if score >= thresholds.get("grade_d", 20.0):
            return "D"
        return "F"

    def _build_explanation(
        self,
        biz: Dict[str, Any],
        dims: List[MaturityDimension],
        total: float,
        grade: str,
        completeness: float,
    ) -> str:
        name = biz.get("name", "this business")
        lines = [
            f"Digital Maturity Assessment: {name}",
            f"Grade: {grade}  |  Score: {total:.1f}/100  |  Data completeness: {completeness:.0%}",
            "",
            "── Dimension Breakdown ──",
        ]
        for d in dims:
            bar = "✓" if not d.gap else "✗"
            pct = int((d.score / d.max_score) * 100) if d.max_score else 0
            lines.append(f"  {bar} [{d.name}] {d.score:.0f}/{d.max_score:.0f} pts ({pct}%) — {d.detail}")

        lines.append("")
        if any(d.gap for d in dims):
            lines.append("── Identified Gaps ──")
            for d in dims:
                if d.gap:
                    lines.append(f"  · {d.detail}")

        return "\n".join(lines)

    # ── Settings Loader ───────────────────────────────────────────────────────

    def _load_thresholds(self) -> Dict[str, float]:
        get = self._settings.get_float
        return {
            "review_high_threshold": get("opp.review.high_threshold", 100.0),
            "review_mid_threshold":  get("opp.review.mid_threshold", 10.0),
            "rating_high_threshold": get("opp.rating.high_threshold", 4.2),
            "rating_mid_threshold":  get("opp.rating.mid_threshold", 3.5),
            "rating_low_threshold":  get("opp.rating.low_threshold", 3.0),
            "grade_a": get("opp.maturity.grade_a", 80.0),
            "grade_b": get("opp.maturity.grade_b", 60.0),
            "grade_c": get("opp.maturity.grade_c", 40.0),
            "grade_d": get("opp.maturity.grade_d", 20.0),
        }
