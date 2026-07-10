from datetime import datetime
from typing import List, Dict, Any
from leadforge.config import SCORE_NO_WEBSITE, SCORE_WITH_WEBSITE
from leadforge.utils import deduplicate_leads, get_logger

logger = get_logger()


def score_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score a single business based on the digital presence rules:
    - No website: Priority High (+60 points)
    - Website exists: Priority Medium (0 points)
    """
    website = lead.get("website", "")

    if not website:
        score = SCORE_NO_WEBSITE
        priority = "High"
        notes = "No website found. High digital transformation opportunity."
    else:
        score = SCORE_WITH_WEBSITE
        priority = "Medium"
        notes = f"Website exists: {website}. Potential upgrade or SEO opportunity."

    scored_lead = lead.copy()
    scored_lead["priority"] = priority
    scored_lead["score"] = score
    scored_lead["notes"] = notes
    scored_lead["discovery_date"] = datetime.now().strftime("%Y-%m-%d")

    return scored_lead


def process_and_score_leads(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicates raw leads, calculates priority scoring, and sorts by priority score descending.
    """
    # 1. Deduplicate
    unique_leads = deduplicate_leads(leads)
    logger.info(
        f"Deduplicated raw leads: {len(leads)} -> {len(unique_leads)} unique listings."
    )

    # 2. Score
    scored_leads = [score_lead(lead) for lead in unique_leads]

    # 3. Sort (High priority / score 60 first, then Medium / score 0)
    scored_leads.sort(key=lambda x: x.get("score", 0), reverse=True)

    return scored_leads
