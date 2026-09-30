"""Multi-Platform Phone Enrichment Orchestrator."""

import asyncio
from typing import Dict, Any, List, Optional, Tuple

from leadforge.enrichment.phone_providers.base import BasePhoneProvider, PhoneResult
from leadforge.enrichment.phone_providers.indiamart_phone import IndiaMartPhoneProvider
from leadforge.enrichment.phone_providers.justdial_phone import JustdialPhoneProvider
from leadforge.enrichment.phone_providers.tradeindia_phone import TradeIndiaPhoneProvider
from leadforge.enrichment.phone_providers.website_phone import WebsitePhoneProvider
from leadforge.enrichment.phone_providers.phone_aggregator import PhoneCandidateAggregator
from leadforge.utils import get_logger

logger = get_logger()


class PhoneEnrichmentOrchestrator:
    """Coordinates multi-platform phone number extraction across enabled providers."""

    def __init__(
        self,
        providers: Optional[List[BasePhoneProvider]] = None,
        aggregator: Optional[PhoneCandidateAggregator] = None,
    ):
        self.providers: Dict[str, BasePhoneProvider] = {}
        default_providers = providers or [
            WebsitePhoneProvider(),
            IndiaMartPhoneProvider(),
            JustdialPhoneProvider(),
            TradeIndiaPhoneProvider(),
        ]
        for p in default_providers:
            self.providers[p.name] = p

        self.aggregator = aggregator or PhoneCandidateAggregator()

    async def enrich_phone(
        self,
        business_profile: Dict[str, Any],
        enabled_platforms: Optional[List[str]] = None,
        initial_phone: Optional[str] = None,
        initial_source: str = "google_maps",
        timeout_seconds: float = 8.0,
    ) -> Tuple[Optional[str], Optional[str], Optional[str], List[Dict[str, Any]]]:
        """Runs multi-provider phone extraction and aggregates results.

        Returns:
            Tuple of:
            (primary_display_phone, primary_source, canonical_primary_phone, phone_candidates_list)
        """
        # Map user-friendly platform keys to provider names
        platform_key_map = {
            "google_maps": "google_maps",
            "indiamart": "indiamart",
            "justdial": "justdial",
            "tradeindia": "tradeindia",
            "website": "official_website",
            "official_website": "official_website",
        }

        active_provider_keys = set()
        if enabled_platforms is not None:
            for p in enabled_platforms:
                k = platform_key_map.get(p.lower().strip(), p)
                if k in self.providers:
                    active_provider_keys.add(k)
        else:
            from leadforge.enrichment.orchestrator import directory_providers_enabled
            if directory_providers_enabled():
                active_provider_keys = set(self.providers.keys())
            else:
                active_provider_keys = {
                    k for k in self.providers.keys()
                    if k not in {"indiamart", "justdial", "tradeindia"}
                }

        # If business has a website and website is not explicitly excluded, include website phone provider
        if business_profile.get("website") or business_profile.get("website_domain"):
            if enabled_platforms is None or "website" in enabled_platforms or "official_website" in enabled_platforms:
                active_provider_keys.add("official_website")

        # Exclude initial discovery source from redundant secondary search if not needed
        # (e.g. if initial came from Google Maps, we search secondary directories)
        tasks = []
        for key in active_provider_keys:
            if key in self.providers:
                tasks.append(self.providers[key].extract_phones(business_profile))

        extracted_results: List[PhoneResult] = []
        if tasks:
            try:
                responses = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout_seconds,
                )
                for res in responses:
                    if isinstance(res, list):
                        extracted_results.extend(res)
                    elif isinstance(res, Exception):
                        logger.debug(f"[PhoneEnrichmentOrchestrator] Provider exception: {res}")
            except asyncio.TimeoutError:
                logger.warning("[PhoneEnrichmentOrchestrator] Timeout during phone extraction.")
            except Exception as exc:
                logger.error(f"[PhoneEnrichmentOrchestrator] Extraction error: {exc}")

        # Aggregate and rank candidates
        return self.aggregator.aggregate(
            candidate_results=extracted_results,
            initial_phone=initial_phone,
            initial_source=initial_source,
        )
