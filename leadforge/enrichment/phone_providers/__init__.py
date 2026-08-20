"""Multi-platform phone number extraction and enrichment providers."""

from leadforge.enrichment.phone_providers.base import BasePhoneProvider, PhoneResult
from leadforge.enrichment.phone_providers.justdial_phone import JustdialPhoneProvider
from leadforge.enrichment.phone_providers.indiamart_phone import IndiaMartPhoneProvider
from leadforge.enrichment.phone_providers.tradeindia_phone import TradeIndiaPhoneProvider
from leadforge.enrichment.phone_providers.website_phone import WebsitePhoneProvider
from leadforge.enrichment.phone_providers.phone_aggregator import PhoneCandidateAggregator

__all__ = [
    "BasePhoneProvider",
    "PhoneResult",
    "JustdialPhoneProvider",
    "IndiaMartPhoneProvider",
    "TradeIndiaPhoneProvider",
    "WebsitePhoneProvider",
    "PhoneCandidateAggregator",
]
