"""Unified Deterministic Decision Engine (LF-DEC-002 & LF-DEC-003).

Combines Offer Selection (LF-DEC-002) and Campaign & CTA Routing (LF-DEC-003)
into a single pure, deterministic decision pipeline consuming structured data
from the Relational Knowledge Graph.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from leadforge.outreach.router import CampaignRouter
from leadforge.repositories.knowledge import SQLiteKnowledgeRepository


@dataclass(frozen=True)
class DecisionObject:
    """Canonical structured decision payload returned by the Decision Engine."""

    offer_id: Optional[str]
    service_name: str
    campaign_name: str
    outreach_strategy: str
    primary_cta: str
    secondary_cta: str
    personalization_focus: str
    reasoning: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "service_name": self.service_name,
            "campaign_name": self.campaign_name,
            "outreach_strategy": self.outreach_strategy,
            "primary_cta": self.primary_cta,
            "secondary_cta": self.secondary_cta,
            "personalization_focus": self.personalization_focus,
            "reasoning": self.reasoning,
        }


class DecisionEngine:
    """Pure, rule-based deterministic Decision Engine pipeline."""

    BOOKING_CATEGORIES = {
        "dentist",
        "dentists",
        "clinic",
        "clinics",
        "doctor",
        "doctors",
        "salon",
        "salons",
        "spa",
        "consultant",
        "consultants",
        "chiropractor",
    }
    PORTAL_CATEGORIES = {
        "manufacturer",
        "manufacturers",
        "wholesaler",
        "wholesalers",
        "distributor",
        "distributors",
    }

    def __init__(
        self,
        knowledge_repo: Optional[SQLiteKnowledgeRepository] = None,
        campaign_router: Optional[CampaignRouter] = None,
    ) -> None:
        self._knowledge_repo = knowledge_repo or SQLiteKnowledgeRepository()
        self._router = campaign_router or CampaignRouter()

    def evaluate_decision(self, business_data: Dict[str, Any]) -> DecisionObject:
        """Evaluates structured business evidence and returns a canonical DecisionObject."""
        reasoning: List[str] = []

        category_raw = (
            business_data.get("category")
            or business_data.get("google_primary_category")
            or ""
        ).strip()
        category_clean = category_raw.lower()

        website = (business_data.get("website") or business_data.get("website_domain") or "").strip()
        has_website = business_data.get("has_website")
        if has_website is None:
            has_website = bool(website)

        ssl_valid = business_data.get("ssl_valid", True)
        load_time = float(business_data.get("load_time_seconds") or 0.0)

        # 1. Query Knowledge Graph for Industry Profile & Offers
        industry_profile = None
        try:
            industry_code = f"IND_{category_clean.upper()}"
            industry_profile = self._knowledge_repo.get_industry_profile_by_code(industry_code)
        except Exception:
            industry_profile = None

        offer_id: Optional[str] = None
        service_name: str = ""

        # 2. Offer Selection Logic (LF-DEC-002)
        if not has_website:
            service_name = "Professional Website Design & Speed Optimization"
            reasoning.append("No website detected -> Selected Digital Transformation Website Package")
        elif ssl_valid is False:
            service_name = "Website Security & SSL Infrastructure Upgrade"
            reasoning.append("Invalid/Missing SSL detected -> Selected Security Upgrade Package")
        elif load_time > 3.0:
            service_name = "Page Speed Optimization & Core Web Vitals Overhaul"
            reasoning.append(f"Slow page load time ({load_time:.1f}s) -> Selected Speed Optimization Package")
        elif any(b in category_clean for b in self.BOOKING_CATEGORIES):
            service_name = "Custom Software Integration & Appointment Booking Portals"
            reasoning.append(f"Category '{category_raw}' is booking-intensive -> Selected Appointment Portal Offer")
        elif any(p in category_clean for p in self.PORTAL_CATEGORIES):
            service_name = "Custom Order Entry & Distributor Client Portals"
            reasoning.append(f"Category '{category_raw}' is wholesale/distributor -> Selected B2B Order Portal Offer")
        else:
            service_name = "Local SEO & Digital Infrastructure Upgrade"
            reasoning.append("Standard business profile -> Selected Baseline Local SEO Offer")

        # 3. Campaign & CTA Routing Logic (LF-DEC-003)
        router_campaign = self._router.route_lead(
            category=category_raw,
            has_website=has_website,
            ssl_valid=ssl_valid,
            load_time_seconds=load_time,
            has_booking=business_data.get("has_booking"),
            has_order_flow=business_data.get("has_order_flow"),
            has_contact_form=business_data.get("has_contact_form"),
            audit_data=business_data.get("audit_data"),
        )

        if router_campaign:
            campaign_name = router_campaign.get("name", "Standard Outreach")
            reasoning.append(f"Matched CampaignRouter rule: '{campaign_name}'")
        elif not has_website:
            campaign_name = "Campaign A (No Website)"
        elif any(b in category_clean for b in self.BOOKING_CATEGORIES):
            campaign_name = "Campaign B (Booking)"
        elif any(p in category_clean for p in self.PORTAL_CATEGORIES):
            campaign_name = "Campaign B (Order Portal)"
        else:
            campaign_name = "Campaign C (General Optimization)"

        # Outreach Strategy & CTA Assignment
        if not has_website:
            outreach_strategy = "DIGITAL_TRANSFORMATION"
            primary_cta = "Would you like me to send over a 1-page mock design for your profile?"
            personalization_focus = "Highlight zero digital footprint vs local competitors"
        elif ssl_valid is False:
            outreach_strategy = "TECHNICAL_REMEDIATION"
            primary_cta = "Would you like our security checklist to fix the browser warning?"
            personalization_focus = "Highlight browser security warning & trust impact"
        elif load_time > 3.0:
            outreach_strategy = "PERFORMANCE_REMEDIATION"
            primary_cta = "Shall I send a breakdown of the scripts slowing down your load speed?"
            personalization_focus = "Highlight mobile visitor bounce rate due to load delay"
        elif any(b in category_clean for b in self.BOOKING_CATEGORIES):
            outreach_strategy = "CONVERSION_OPTIMIZATION"
            primary_cta = "Do you take bookings online or mostly by phone?"
            personalization_focus = "Highlight patient/client booking drop-off reduction"
        else:
            outreach_strategy = "GENERAL_GROWTH"
            primary_cta = "Are you accepting new clients in your area this month?"
            personalization_focus = "Highlight local search discovery improvement"

        secondary_cta = "Can I reply here with a quick 30-second audit link?"

        return DecisionObject(
            offer_id=offer_id,
            service_name=service_name,
            campaign_name=campaign_name,
            outreach_strategy=outreach_strategy,
            primary_cta=primary_cta,
            secondary_cta=secondary_cta,
            personalization_focus=personalization_focus,
            reasoning=reasoning,
        )
