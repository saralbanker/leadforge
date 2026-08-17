from datetime import datetime
from typing import List, Dict, Any
from leadforge.prioritization import LeadPrioritizationEngine
from leadforge.utils import deduplicate_leads, get_logger

logger = get_logger()


def score_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Score a single business using the deterministic LeadPrioritizationEngine."""
    result = LeadPrioritizationEngine.calculate_priority(lead)

    scored_lead = lead.copy()
    scored_lead["priority"] = result.priority_tier.capitalize()
    scored_lead["score"] = result.overall_score
    scored_lead["score_breakdown"] = result.score_breakdown
    scored_lead["notes"] = "; ".join(result.explanation)
    scored_lead["discovery_date"] = datetime.now().strftime("%Y-%m-%d")

    return scored_lead


def process_and_score_leads(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicates raw leads, calculates deterministic priority scoring, and sorts descending."""
    unique_leads = deduplicate_leads(leads)
    logger.info(
        f"Deduplicated raw leads: {len(leads)} -> {len(unique_leads)} unique listings."
    )

    scored_leads = [score_lead(lead) for lead in unique_leads]
    scored_leads.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return scored_leads

