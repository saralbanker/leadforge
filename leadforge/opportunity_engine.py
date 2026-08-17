"""Opportunity Intelligence Engine — Phase 4 (refined).

Phase 4 improvements over Phase 3
-----------------------------------
* 3-tier review banding (REVIEW_NONE / LOW / MID / HIGH)
* 4-tier rating banding (RATING_POOR / LOW / MID / HIGH)
* Evidence-count–gated confidence (not score-magnitude alone)
* Data completeness guard (zero-data businesses → LOW confidence)
* Digital maturity assessment integrated into draft
* CATEGORIES_KNOWN removed (was noise)
* Service base-price via ServiceRepository (fixes Repository Pattern violation)
* Structured explanation with positive/negative signal separation
* All thresholds fully configurable via settings table
* Score floor at 0, ceiling uncapped (ranking handles the rest)

Design principles (unchanged from Phase 3)
-------------------------------------------
* Deterministic — identical input → identical output.
* Configurable — all weights/thresholds read from settings.
* Explainable — every signal is human-readable.
* Multiple opportunities per business (one per service).
* Duplicate-safe — idempotent on repeat calls.
* Repository-only persistence — no raw SQL here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from leadforge.category_mapper import CategoryServiceMapper
from leadforge.digital_maturity import DigitalMaturityAssessor, MaturityProfile
from leadforge.repositories.maturity import SQLiteDigitalMaturityRepository
from leadforge.repositories.opportunity import SQLiteOpportunityRepository
from leadforge.repositories.service import SQLiteServiceRepository
from leadforge.repositories.settings import SQLiteSettingsRepository
from leadforge.confidence_engine import ConfidenceEngine
from leadforge.database import append_event



# ── Value objects ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoringSignal:
    """A single explainable contribution to an opportunity score."""

    rule_name: str
    score_delta: float
    reason: str


@dataclass
class OpportunityDraft:
    """All data required to persist one opportunity."""

    business_id: str
    title: str
    service_name: str
    pipeline_stage: str
    score: float
    close_probability: float
    estimated_value: float
    signals: List[ScoringSignal] = field(default_factory=list)
    explanation: str = ""
    maturity_grade: str = ""
    maturity_score: float = 0.0


# ── Engine ────────────────────────────────────────────────────────────────────


class OpportunityIntelligenceEngine:
    """Converts a business profile into one or more ranked opportunities.

    Usage::

        engine = OpportunityIntelligenceEngine()
        engine.generate_for_business(business_data)

    *business_data* is the dict produced by the existing scraper pipeline.
    """

    def __init__(
        self,
        settings_repo: Optional[SQLiteSettingsRepository] = None,
        opportunity_repo: Optional[SQLiteOpportunityRepository] = None,
        category_mapper: Optional[CategoryServiceMapper] = None,
        service_repo: Optional[SQLiteServiceRepository] = None,
        maturity_assessor: Optional[DigitalMaturityAssessor] = None,
        maturity_repo: Optional[SQLiteDigitalMaturityRepository] = None,
    ) -> None:
        self._settings = settings_repo or SQLiteSettingsRepository()
        self._opp_repo = opportunity_repo or SQLiteOpportunityRepository()
        self._mapper = category_mapper or CategoryServiceMapper(self._settings)
        self._svc_repo = service_repo or SQLiteServiceRepository()
        self._maturity = maturity_assessor or DigitalMaturityAssessor(self._settings)
        self._maturity_repo = maturity_repo or SQLiteDigitalMaturityRepository()

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_for_business(
        self, business_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate and persist opportunities for one business.

        Returns a list of result dicts (one per opportunity created or skipped).
        Already-existing opportunities are skipped — not re-created.
        """
        business_id: str = business_data.get("business_id", "")
        if not business_id:
            business_id = business_data.get("id", "")
            if not business_id:
                return []

        biz_data = business_data.copy()
        biz_data["business_id"] = business_id

        drafts, maturity = self.evaluate_opportunities(biz_data)

        # Persist maturity so queries can JOIN on it without recomputing.
        try:
            self._maturity_repo.upsert(
                business_id=business_id,
                score=maturity.score,
                grade=maturity.grade,
                details_json=json.dumps(
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
            )
        except Exception:
            pass  # maturity persistence failure must never break opportunity generation

        results: List[Dict[str, Any]] = []
        for draft in drafts:
            if self._opp_repo.title_exists_for_business(business_id, draft.title):
                results.append({"skipped": True, "title": draft.title})
                continue

            opp_id = self._opp_repo.create_with_scoring_logs(
                business_id=draft.business_id,
                title=draft.title,
                pipeline_stage=draft.pipeline_stage,
                score=draft.score,
                close_probability=draft.close_probability,
                estimated_value=draft.estimated_value,
                scoring_logs=[
                    {
                        "rule_name": s.rule_name,
                        "score_delta": s.score_delta,
                        "reason": s.reason,
                    }
                    for s in draft.signals
                ],
            )
            append_event(
                event_type="OPPORTUNITY_CREATED",
                entity_type="Opportunity",
                entity_id=opp_id,
                payload={
                    "business_id": draft.business_id,
                    "title": draft.title,
                    "score": draft.score,
                    "estimated_value": draft.estimated_value,
                },
            )
            results.append(

                {
                    "created": True,
                    "opportunity_id": opp_id,
                    "title": draft.title,
                    "score": draft.score,
                    "close_probability": draft.close_probability,
                    "estimated_value": draft.estimated_value,
                    "maturity_grade": draft.maturity_grade,
                    "maturity_score": draft.maturity_score,
                    "explanation": draft.explanation,
                }
            )

        return results

    def evaluate_opportunities(
        self, business_data: Dict[str, Any]
    ) -> tuple[List[OpportunityDraft], MaturityProfile]:
        """Pure opportunity evaluation without database side effects.

        Returns a tuple of (opportunity_drafts, maturity_profile).
        """
        biz_data = business_data.copy()
        business_id = biz_data.get("business_id", "") or biz_data.get("id", "")
        if not business_id:
            from leadforge.database import uuidv7

            business_id = uuidv7()
        biz_data["business_id"] = business_id

        category: str = biz_data.get("category", "")
        service_names = self._mapper.get_services_for_category(category)
        if not service_names:
            return [], self._maturity.assess(biz_data)

        weights = self._load_weights()
        maturity = self._maturity.assess(biz_data)

        drafts: List[OpportunityDraft] = []
        for service_name in service_names:
            draft = self._draft_opportunity(biz_data, service_name, weights, maturity)
            drafts.append(draft)

        return drafts, maturity

    def score_business(self, business_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute the composite opportunity score for a business.

        Pure — does not write to the database.
        Single source of truth for scoring logic; used both internally and in tests.

        Returns a dict with:
          - score               (float)
          - close_probability   (float 0.0–1.0)
          - priority            ('HIGH' | 'MEDIUM' | 'LOW')
          - confidence          ('HIGH' | 'MEDIUM' | 'LOW')
          - confidence_rationale (str — explains why this confidence level was chosen)
          - signals             (list of signal dicts)
          - positive_signals    (list — signals with score_delta > 0)
          - negative_signals    (list — signals with score_delta < 0)
          - data_completeness   (float 0.0–1.0)
          - maturity_grade      (str)
          - maturity_score      (float)
          - explanation         (str)
        """
        weights = self._load_weights()
        maturity = self._maturity.assess(business_data)
        signals, score = self._compute_signals(business_data, weights)
        close_probability = self._score_to_probability(score, weights)
        priority = self._score_to_priority(score, weights)
        confidence, confidence_rationale = self._score_to_confidence(
            signals, score, maturity, weights
        )
        explanation = self._build_explanation(
            business_data, signals, score, confidence, confidence_rationale, maturity
        )

        all_signals = [
            {"rule_name": s.rule_name, "score_delta": s.score_delta, "reason": s.reason}
            for s in signals
        ]

        return {
            "score": score,
            "close_probability": close_probability,
            "priority": priority,
            "confidence": confidence,
            "confidence_rationale": confidence_rationale,
            "signals": all_signals,
            "positive_signals": [s for s in all_signals if s["score_delta"] > 0],
            "negative_signals": [s for s in all_signals if s["score_delta"] < 0],
            "data_completeness": maturity.data_completeness,
            "maturity_grade": maturity.grade,
            "maturity_score": maturity.score,
            "explanation": explanation,
        }

    def list_opportunities(
        self,
        limit: Optional[int] = None,
        pipeline_stage: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Returns opportunities ranked by score DESC, then close_probability DESC."""
        return self._opp_repo.list_ranked(limit=limit, pipeline_stage=pipeline_stage)

    # ── Internal: Drafting ────────────────────────────────────────────────────

    def _draft_opportunity(
        self,
        business_data: Dict[str, Any],
        service_name: str,
        weights: Dict[str, float],
        maturity: MaturityProfile,
    ) -> OpportunityDraft:
        signals, score = self._compute_signals(business_data, weights)
        close_probability = self._score_to_probability(score, weights)
        estimated_value = self._estimate_value(
            service_name, score, weights, signals=signals, maturity=maturity
        )
        confidence, confidence_rationale = self._score_to_confidence(
            signals, score, maturity, weights
        )
        explanation = self._build_explanation(
            business_data, signals, score, confidence, confidence_rationale, maturity
        )
        business_name = business_data.get("name", "Unknown")
        title = f"{service_name} — {business_name}"

        return OpportunityDraft(
            business_id=business_data["business_id"],
            title=title,
            service_name=service_name,
            pipeline_stage="PROSPECTING",
            score=round(score, 2),
            close_probability=round(close_probability, 4),
            estimated_value=round(estimated_value, 2),
            signals=signals,
            explanation=explanation,
            maturity_grade=maturity.grade,
            maturity_score=maturity.score,
        )

    # ── Internal: Scoring ─────────────────────────────────────────────────────

    def _compute_signals(
        self,
        biz: Dict[str, Any],
        weights: Dict[str, float],
    ) -> tuple[List[ScoringSignal], float]:
        """Evaluate each scoring rule and return (signals, total_score).

        Rules applied in a deterministic order so repeated calls with the
        same data always produce the same signals list and total score.
        """
        signals: List[ScoringSignal] = []
        score: float = 0.0

        def _add(rule: str, delta: float, reason: str) -> None:
            signals.append(
                ScoringSignal(rule_name=rule, score_delta=delta, reason=reason)
            )
            nonlocal score
            score += delta

        website = (biz.get("website") or "").strip()
        email = (biz.get("contact_email") or "").strip()
        phone = (biz.get("phone") or "").strip()
        rating = biz.get("rating")
        review_count = biz.get("review_count")
        business_status = (biz.get("business_status") or "").upper()

        review_high_t = int(weights.get("review_high_threshold", 100))
        review_mid_t = int(weights.get("review_mid_threshold", 10))
        rating_high_t = weights.get("rating_high_threshold", 4.2)
        rating_mid_t = weights.get("rating_mid_threshold", 3.5)
        rating_low_t = weights.get("rating_low_threshold", 3.0)

        # ── Rule 1: Website Presence ──────────────────────────────────────────
        if not website:
            _add(
                "NO_WEBSITE",
                weights["no_website"],
                "Business has no website — primary digital-gap signal. "
                "Website build is the highest-value service opportunity.",
            )
        else:
            _add(
                "HAS_WEBSITE",
                weights["has_website"],
                f"Website detected ({website}). "
                "Opportunity for SEO, redesign, performance audit, or upgrade.",
            )

        # ── Rule 2: Contact Email ─────────────────────────────────────────────
        if email:
            _add(
                "HAS_EMAIL",
                weights["has_email"],
                f"Direct contact email available ({email}) — strong outreach signal.",
            )

        # ── Rule 3: Phone Number ──────────────────────────────────────────────
        if phone:
            _add(
                "HAS_PHONE",
                weights["has_phone"],
                "Phone number present — enables direct outreach.",
            )

        # ── Rule 4: Review Volume (3-tier + zero-review penalty) ──────────────
        try:
            rc = int(review_count) if review_count is not None else None
        except (TypeError, ValueError):
            rc = None

        if rc is None:
            pass  # Unknown — no signal either way
        elif rc >= review_high_t:
            _add(
                "REVIEW_HIGH",
                weights["review_high"],
                f"{rc} reviews — strong Maps visibility and active customer base.",
            )
        elif rc >= review_mid_t:
            _add(
                "REVIEW_MID",
                weights["review_mid"],
                f"{rc} reviews — moderate Maps presence.",
            )
        elif rc > 0:
            _add(
                "REVIEW_LOW",
                weights["review_low"],
                f"{rc} reviews — minimal social proof; GMB optimisation recommended.",
            )
        else:
            _add(
                "REVIEW_NONE",
                weights["review_none"],
                "0 reviews on Google Maps — business is not visible or indexed. "
                "GMB setup is the priority recommendation.",
            )

        # ── Rule 5: Rating (4-tier including poor-rating penalty) ─────────────
        if rating is not None:
            try:
                r = float(rating)
                if r >= rating_high_t:
                    _add(
                        "RATING_HIGH",
                        weights["rating_high"],
                        f"Rating {r:.1f} ≥ {rating_high_t} — strong reputation, "
                        "high conversion potential.",
                    )
                elif r >= rating_mid_t:
                    _add(
                        "RATING_MID",
                        weights["rating_mid"],
                        f"Rating {r:.1f} — acceptable reputation. "
                        "Targeted review strategy can improve ranking.",
                    )
                elif r >= rating_low_t:
                    _add(
                        "RATING_LOW",
                        weights["rating_low"],
                        f"Rating {r:.1f} — below average. "
                        "Reputation management is a service opportunity.",
                    )
                else:
                    _add(
                        "RATING_POOR",
                        weights["rating_poor"],
                        f"Rating {r:.1f} < {rating_low_t} — poor reputation. "
                        "Reputational risk reduces digital service conversion likelihood.",
                    )
            except (TypeError, ValueError):
                pass

        # ── Rule 6: Business Operational Status ───────────────────────────────
        if "PERMANENTLY_CLOSED" in business_status:
            _add(
                "PERMANENTLY_CLOSED",
                weights["permanently_closed"],
                "Business is permanently closed — very low conversion probability. "
                "Exclude from priority outreach.",
            )
        elif "TEMPORARILY_CLOSED" in business_status:
            _add(
                "TEMPORARILY_CLOSED",
                weights["temporarily_closed"],
                "Business is temporarily closed — reduced but non-zero opportunity. "
                "Re-verify before outreach.",
            )
        elif business_status in ("OPERATIONAL", ""):
            _add(
                "OPERATIONAL",
                weights["operational"],
                "Business is operational — strong conversion readiness signal.",
            )

        # Score floor at 0
        score = max(0.0, score)
        return signals, score

    # ── Internal: Derived Metrics ─────────────────────────────────────────────

    def _score_to_probability(self, score: float, weights: Dict[str, float]) -> float:
        """Map raw score to close_probability in [0.0, 1.0].

        Phase 4: uses a softened sigmoid-like cap rather than a raw linear map.
        p = score / (score + 50)  — asymptotically approaches 1.0, never equals it.
        Score 50 → 0.50, Score 80 → 0.62, Score 45 → 0.47.

        This is more realistic than score/100 (which implied 80-score = 80% close rate).
        Formula is still deterministic and fully explicit.
        """
        if score <= 0:
            return 0.0
        return round(score / (score + 50.0), 4)

    def _score_to_priority(self, score: float, weights: Dict[str, float]) -> str:
        high = weights.get("priority_high", 60.0)
        med = weights.get("priority_medium", 28.0)
        if score >= high:
            return "HIGH"
        if score >= med:
            return "MEDIUM"
        return "LOW"

    def _score_to_confidence(
        self,
        signals: List[ScoringSignal],
        score: float,
        maturity: MaturityProfile,
        weights: Dict[str, float],
    ) -> tuple[str, str]:
        """Evidence-count–gated confidence.

        Delegates logic to the decoupled ConfidenceEngine.
        """
        positive_signal_count = sum(1 for s in signals if s.score_delta > 0)
        engine = ConfidenceEngine()
        return engine.calculate(
            score=score,
            positive_signal_count=positive_signal_count,
            data_completeness=maturity.data_completeness,
            weights=weights,
        )

    def _estimate_value(
        self,
        service_name: str,
        score: float,
        weights: Dict[str, float],
        signals: Optional[List[ScoringSignal]] = None,
        maturity: Optional[Any] = None,
    ) -> float:
        """Derive estimated deal value from service base_price × confidence multiplier.

        Callers should pass the already-computed signals and maturity so that
        confidence is calculated with real evidence rather than empty inputs.
        """
        base_price = self._svc_repo.get_base_price(service_name)
        effective_signals = signals if signals is not None else []
        effective_maturity = (
            maturity
            if maturity is not None
            else type("M", (), {"data_completeness": 1.0})()
        )
        confidence, _ = self._score_to_confidence(
            effective_signals, score, effective_maturity, weights
        )
        multiplier_key = {
            "HIGH": "value_multiplier_high",
            "MEDIUM": "value_multiplier_medium",
            "LOW": "value_multiplier_low",
        }[confidence]
        multiplier = weights.get(multiplier_key, 0.35)
        return base_price * multiplier

    # ── Internal: Explainability ──────────────────────────────────────────────

    def _build_explanation(
        self,
        biz: Dict[str, Any],
        signals: List[ScoringSignal],
        total_score: float,
        confidence: str,
        confidence_rationale: str,
        maturity: MaturityProfile,
    ) -> str:
        """Produce a structured, human-readable explanation.

        Structure:
          Header — business name + summary scores
          Positive factors — green signals
          Negative factors — red signals
          Confidence rationale
          Digital maturity summary
          Recommendation
        """
        name = biz.get("name", "this business")
        positive = [s for s in signals if s.score_delta > 0]
        negative = [s for s in signals if s.score_delta < 0]

        lines = [
            f"══ Opportunity Assessment: {name} ══",
            f"  Score: {total_score:.1f}  |  Confidence: {confidence}  "
            f"|  Maturity: {maturity.grade} ({maturity.score:.0f}/100)",
            "",
        ]

        if positive:
            lines.append("✔ Positive signals:")
            for s in positive:
                lines.append(f"    +{s.score_delta:.1f}  [{s.rule_name}]  {s.reason}")
        if negative:
            lines.append("✘ Negative signals:")
            for s in negative:
                lines.append(f"    {s.score_delta:.1f}  [{s.rule_name}]  {s.reason}")
        if not signals:
            lines.append("  (No signals evaluated — check business data completeness)")

        lines += [
            "",
            f"⊙ Confidence rationale: {confidence_rationale}",
            f"⊙ Data completeness: {maturity.data_completeness:.0%}",
            "",
            "── Digital Maturity Gaps ──",
        ]
        if maturity.gaps:
            for gap in maturity.gaps:
                lines.append(f"  · {gap}")
        else:
            lines.append("  · No critical digital gaps detected.")

        return "\n".join(lines)

    # ── Internal: Settings Loader ─────────────────────────────────────────────

    def _load_weights(self) -> Dict[str, float]:
        """Read all scoring weights and thresholds from the settings table.

        Falls back to Phase 4 defaults so the engine works even if migration 004
        has not been applied yet (e.g., in isolated unit tests).
        """
        get = self._settings.get_float

        return {
            # ── Scoring deltas
            "no_website": get("opp.score.no_website", 35.0),
            "has_website": get("opp.score.has_website", 25.0),
            "has_email": get("opp.score.has_email", 10.0),
            "has_phone": get("opp.score.has_phone", 3.0),
            "review_high": get("opp.score.review_high", 15.0),
            "review_mid": get("opp.score.review_mid", 8.0),
            "review_low": get("opp.score.review_low", 3.0),
            "review_none": get("opp.score.review_none", -5.0),
            "rating_high": get("opp.score.rating_high", 12.0),
            "rating_mid": get("opp.score.rating_mid", 6.0),
            "rating_low": get("opp.score.rating_low", 2.0),
            "rating_poor": get("opp.score.rating_poor", -8.0),
            "operational": get("opp.score.operational", 12.0),
            "temporarily_closed": get("opp.score.temporarily_closed", -15.0),
            "permanently_closed": get("opp.score.permanently_closed", -60.0),
            # ── Review / Rating thresholds (used inside _compute_signals)
            "review_high_threshold": get("opp.review.high_threshold", 100.0),
            "review_mid_threshold": get("opp.review.mid_threshold", 10.0),
            "rating_high_threshold": get("opp.rating.high_threshold", 4.2),
            "rating_mid_threshold": get("opp.rating.mid_threshold", 3.5),
            "rating_low_threshold": get("opp.rating.low_threshold", 3.0),
            # ── Confidence thresholds + evidence gates
            "confidence_high": get("opp.confidence.high_threshold", 60.0),
            "confidence_medium": get("opp.confidence.medium_threshold", 30.0),
            "min_signals_high": get("opp.confidence.min_signals_high", 4.0),
            "min_signals_medium": get("opp.confidence.min_signals_medium", 2.0),
            # ── Priority thresholds
            "priority_high": get("opp.priority.high_threshold", 60.0),
            "priority_medium": get("opp.priority.medium_threshold", 28.0),
            # ── Estimated value multipliers
            "value_multiplier_high": get("opp.value.high_confidence_multiplier", 1.0),
            "value_multiplier_medium": get(
                "opp.value.medium_confidence_multiplier", 0.65
            ),
            "value_multiplier_low": get("opp.value.low_confidence_multiplier", 0.35),
        }
