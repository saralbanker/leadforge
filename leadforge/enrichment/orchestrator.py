"""Email Enrichment Orchestrator for LeadForge Business Enrichment Layer."""

import asyncio
from typing import Dict, Any, List, Optional
from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult
from leadforge.enrichment.website import WebsiteProvider
from leadforge.enrichment.providers.indiamart import IndiaMartProvider
from leadforge.enrichment.providers.tradeindia import TradeIndiaProvider
from leadforge.enrichment.providers.justdial import JustdialProvider
from leadforge.enrichment.aggregator import EmailCandidateAggregator
from leadforge.repositories.enrichment import SQLiteEnrichmentRepository
from leadforge.utils import get_logger

logger = get_logger()


def get_default_providers() -> List[BaseEnrichmentProvider]:
    """Instantiates default multi-provider pipeline."""
    return [
        WebsiteProvider(),
        IndiaMartProvider(),
        TradeIndiaProvider(),
        JustdialProvider(),
    ]


class EmailEnrichmentOrchestrator:
    """Orchestrates modular multi-provider email discovery for a business."""

    def __init__(
        self,
        providers: Optional[List[BaseEnrichmentProvider]] = None,
        aggregator: Optional[EmailCandidateAggregator] = None,
        repository: Optional[SQLiteEnrichmentRepository] = None,
    ):
        self._providers = providers if providers is not None else get_default_providers()
        self._aggregator = aggregator or EmailCandidateAggregator()
        self._repo = repository or SQLiteEnrichmentRepository()

    def register_provider(self, provider: BaseEnrichmentProvider) -> None:
        """Dynamically registers a new enrichment provider."""
        self._providers.append(provider)

    async def enrich_business(
        self, business_profile: Dict[str, Any], global_timeout: float = 12.0
    ) -> tuple[Optional[EnrichmentResult], List[EnrichmentResult]]:
        """Executes multi-provider enrichment, aggregates results, and updates SQLite.

        Args:
            business_profile: Dict containing business_id, name, phone, website_domain, city, etc.
            global_timeout: Maximum execution timeout across all providers.

        Returns:
            Tuple of (top_selected_candidate, all_ranked_candidates)
        """
        business_id = (
            business_profile.get("business_id")
            or business_profile.get("id")
            or ""
        )
        domain = (
            business_profile.get("website_domain")
            or business_profile.get("website")
            or ""
        )

        active_providers = [p for p in self._providers if p.is_enabled()]
        if not active_providers:
            return None, []

        logger.info(
            f"[EnrichmentOrchestrator] Enriching business '{business_profile.get('name')}' "
            f"via {len(active_providers)} active provider(s)..."
        )

        raw_results: List[EnrichmentResult] = []

        async def _run_provider(prov: BaseEnrichmentProvider):
            try:
                res = await prov.enrich(business_profile)
                return res
            except Exception as exc:
                logger.warning(f"[EnrichmentOrchestrator] Provider '{prov.name}' failed: {exc}")
                return []

        tasks = [_run_provider(prov) for prov in active_providers]

        try:
            provider_outputs = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=global_timeout
            )
            for output in provider_outputs:
                if isinstance(output, list):
                    raw_results.extend(output)
        except asyncio.TimeoutError:
            logger.warning(
                f"[EnrichmentOrchestrator] Enrichment timed out after {global_timeout}s for '{business_profile.get('name')}'"
            )

        # Aggregate, deduplicate, syntax-check, and rank candidates
        top_candidate, ranked_candidates = await self._aggregator.aggregate(raw_results)

        # Persist results and update businesses.contact_email
        if business_id:
            try:
                self._repo.save_enrichment_result(
                    business_id=business_id,
                    domain=domain,
                    top_candidate=top_candidate,
                    all_candidates=ranked_candidates,
                )
            except Exception as e:
                logger.error(f"[EnrichmentOrchestrator] Persistence error: {e}")

        if top_candidate:
            logger.info(
                f"[EnrichmentOrchestrator] Discovered email '{top_candidate.email}' "
                f"from '{top_candidate.source_provider}' for '{business_profile.get('name')}'"
            )
        else:
            logger.info(f"[EnrichmentOrchestrator] No email discovered for '{business_profile.get('name')}'")

        return top_candidate, ranked_candidates
