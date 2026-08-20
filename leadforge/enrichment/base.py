"""Base classes and value objects for the LeadForge Business Enrichment Layer."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Optional


# Domains that host many businesses' pages rather than belonging to one.
# Crawling these harvests the *platform's* contact details, not the lead's —
# three businesses whose website_domain was "linktr.ee" all came back with
# Linktree's own press address.
NON_BUSINESS_HOST_DOMAINS = {
    "linktr.ee", "linktree.com", "bit.ly", "tinyurl.com", "rb.gy", "cutt.ly",
    "instagram.com", "facebook.com", "fb.com", "m.facebook.com", "twitter.com",
    "x.com", "linkedin.com", "youtube.com", "youtu.be", "wa.me", "t.me",
    "pinterest.com", "threads.net", "sites.google.com", "business.site",
    "google.com", "maps.google.com", "g.page", "wixsite.com", "blogspot.com",
    "wordpress.com", "weebly.com", "justdial.com", "indiamart.com",
    "tradeindia.com", "exportersindia.com", "sulekha.com",
}


def is_non_business_host(domain: str) -> bool:
    """True when the domain is a platform/aggregator rather than one business's own site."""
    host = (domain or "").strip().lower()
    host = host.split("//")[-1].split("/")[0].split(":")[0].rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return False
    if host in NON_BUSINESS_HOST_DOMAINS:
        return True
    # Subdomains of a blocked host (m.facebook.com, foo.wixsite.com).
    return any(host.endswith("." + blocked) for blocked in NON_BUSINESS_HOST_DOMAINS)


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
