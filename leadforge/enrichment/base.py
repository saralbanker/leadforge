"""Base classes and value objects for the LeadForge Business Enrichment Layer."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Optional


@dataclass(frozen=True)
class EnrichmentResult:
    """Normalized value object produced by enrichment providers."""

    email: str
    source_provider: str
    source_url: str
    confidence_score: float
    discovery_context: str = "general"
    metadata: Optional[Dict[str, Any]] = None


class BaseEnrichmentProvider(ABC):
    """Abstract base class for all modular business enrichment providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier string for the provider (e.g. 'official_website')."""
        pass

    @property
    @abstractmethod
    def priority_weight(self) -> float:
        """Provider priority weight between 0.0 and 1.0 (e.g. 1.0 for official website)."""
        pass

    def is_enabled(self) -> bool:
        """Determines whether the provider is active. Defaults to True."""
        return True

    @abstractmethod
    async def enrich(
        self, business_profile: Dict[str, Any]
    ) -> List[EnrichmentResult]:
        """Asynchronously discovers email candidates for a given business profile.

        Args:
            business_profile: Business metadata dict (name, phone, website_domain, city, etc.)

        Returns:
            List of normalized EnrichmentResult objects.
        """
        pass
