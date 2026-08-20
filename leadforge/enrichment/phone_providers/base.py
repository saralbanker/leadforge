"""Base classes and data structures for multi-platform phone number extraction."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Optional


@dataclass
class PhoneResult:
    """Standard container for phone numbers extracted across diverse platforms."""

    phone: str
    phone_type: str  # 'MOBILE', 'LANDLINE', 'TOLL_FREE', 'UNKNOWN'
    source_provider: str  # 'google_maps', 'indiamart', 'justdial', 'tradeindia', 'official_website'
    source_url: str
    confidence_score: float  # 0.0 to 1.0
    is_mobile: bool = False
    raw_text: Optional[str] = None


class BasePhoneProvider(ABC):
    """Abstract base class for all phone extraction providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider key."""
        pass

    @property
    @abstractmethod
    def priority_weight(self) -> float:
        """Priority weight (0.0 to 1.0) when ranking candidate phone numbers."""
        pass

    @abstractmethod
    async def extract_phones(
        self, business_profile: Dict[str, Any]
    ) -> List[PhoneResult]:
        """Extract candidate phone numbers given a business profile.

        business_profile may contain:
            - 'name': business name
            - 'city': target city
            - 'category': category / niche
            - 'website': official website domain or URL
            - 'source_url': primary listing URL (if available)
        """
        pass
