"""Confidence Engine module for LeadForge V3.0 architecture.

ONLY calculates confidence for business leads and opportunity evaluations.
NEVER: rejects businesses, generates opportunities, or modifies business records.
"""

from typing import Dict, Tuple


class ConfidenceEngine:
    """Calculates evaluation confidence based on data completeness and score metrics.

    Adheres strictly to the V3.0 confidence logic.
    """

    def calculate(
        self,
        score: float,
        positive_signal_count: int,
        data_completeness: float,
        weights: Dict[str, float],
    ) -> Tuple[str, str]:
        """Calculates confidence and its rationale based on evidence gating rules.

        Returns:
            A tuple of (confidence_level, confidence_rationale)
            where confidence_level is 'HIGH', 'MEDIUM', or 'LOW'.
        """
        high_threshold = weights.get("confidence_high", 60.0)
        med_threshold = weights.get("confidence_medium", 30.0)
        min_signals_high = int(weights.get("min_signals_high", 4))
        min_signals_medium = int(weights.get("min_signals_medium", 2))

        # Guard: if data is very sparse, confidence can never be HIGH
        if data_completeness < 0.25:
            return (
                "LOW",
                f"Data completeness is only {data_completeness:.0%} — "
                "insufficient evidence to justify higher confidence.",
            )

        if (
            score >= high_threshold
            and positive_signal_count >= min_signals_high
            and data_completeness >= 0.5
        ):
            return (
                "HIGH",
                f"Score {score:.1f} ≥ {high_threshold} with {positive_signal_count} positive signals "
                f"and {data_completeness:.0%} data completeness.",
            )

        if score >= med_threshold and positive_signal_count >= min_signals_medium:
            return (
                "MEDIUM",
                f"Score {score:.1f} ≥ {med_threshold} with {positive_signal_count} positive signals.",
            )

        return (
            "LOW",
            f"Score {score:.1f} or evidence count ({positive_signal_count} positive signals) "
            "is below threshold for MEDIUM confidence.",
        )
