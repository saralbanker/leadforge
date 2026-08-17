"""LeadForge Business Enrichment Package.

Modular, multi-provider email acquisition layer decoupled from Google Maps discovery.
"""

from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult
from leadforge.enrichment.aggregator import EmailCandidateAggregator
from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator

__all__ = [
    "BaseEnrichmentProvider",
    "EnrichmentResult",
    "EmailCandidateAggregator",
    "EmailEnrichmentOrchestrator",
]
