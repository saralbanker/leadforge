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

    @staticmethod
    def evaluate_ab_test(
        control_sent: int,
        control_success: int,
        variant_sent: int,
        variant_success: int,
        min_sample_size: int = 100,
    ) -> Dict[str, float | str | bool]:
        """Performs Chi-Square statistical test (2x2 contingency matrix) for A/B campaign variants.

        Returns:
            Dict containing:
              - p_value_estimate (float)
              - chi2_stat (float)
              - is_significant (bool): True if p <= 0.05
              - winner (str): 'CONTROL', 'VARIANT', or 'NO_WINNER'
        """
        if control_sent <= 0 or variant_sent <= 0:
            return {
                "chi2_stat": 0.0,
                "p_value_estimate": 1.0,
                "is_significant": False,
                "winner": "NO_WINNER",
                "reason": "Insufficient sample size (sent count is zero)",
            }

        total_sample = control_sent + variant_sent
        if total_sample < min_sample_size:
            return {
                "chi2_stat": 0.0,
                "p_value_estimate": 1.0,
                "is_significant": False,
                "winner": "NO_WINNER",
                "reason": f"Sample size ({total_sample}) is below minimum threshold ({min_sample_size})",
            }

        a = control_success
        b = control_sent - control_success
        c = variant_success
        d = variant_sent - variant_success

        if b < 0 or d < 0:
            return {
                "chi2_stat": 0.0,
                "p_value_estimate": 1.0,
                "is_significant": False,
                "winner": "NO_WINNER",
                "reason": "Invalid inputs: success count exceeds total sent count",
            }

        N = total_sample
        denominator = (a + b) * (c + d) * (a + c) * (b + d)

        if denominator == 0:
            return {
                "chi2_stat": 0.0,
                "p_value_estimate": 1.0,
                "is_significant": False,
                "winner": "NO_WINNER",
                "reason": "Zero variance in outcomes",
            }

        # Chi-square statistic with Yates' continuity correction
        numerator = N * (max(0, abs(a * d - b * c) - N / 2.0) ** 2)
        chi2 = numerator / denominator

        # For 1 degree of freedom:
        # chi2 >= 3.841 => p <= 0.05
        # chi2 >= 6.635 => p <= 0.01
        is_significant = chi2 >= 3.841

        # Estimate p-value threshold approximation
        p_est = 0.01 if chi2 >= 6.635 else (0.05 if chi2 >= 3.841 else 0.5)

        control_rate = a / control_sent
        variant_rate = c / variant_sent

        winner = "NO_WINNER"
        if is_significant:
            winner = "VARIANT" if variant_rate > control_rate else "CONTROL"

        return {
            "chi2_stat": round(chi2, 4),
            "p_value_estimate": p_est,
            "is_significant": is_significant,
            "winner": winner,
            "control_rate": round(control_rate, 4),
            "variant_rate": round(variant_rate, 4),
        }

