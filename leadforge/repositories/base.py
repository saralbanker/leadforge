from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class RepositoryException(Exception):
    """Base exception class for all repository errors."""
    pass

class SettingsRepositoryInterface(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Gets value for a given key. Returns None if key not found."""
        pass

    @abstractmethod
    def set(self, key: str, value: str, description: Optional[str] = None):
        """Sets/updates value for a given key."""
        pass

class SearchHistoryRepositoryInterface(ABC):
    @abstractmethod
    def create(self, city: str, category: str, results_count: int, status: str, search_query: Optional[str] = None) -> str:
        """Logs a search run history, returning its generated UUIDv7."""
        pass

    @abstractmethod
    def list_all(self) -> List[Dict[str, Any]]:
        """Lists all search history entries sorted by created_at descending."""
        pass

class LeadRepositoryInterface(ABC):
    @abstractmethod
    def save_lead_transaction(self, lead_data: Dict[str, Any], campaign_name: str) -> str:
        """
        Saves a single lead transactionally into the DB.
        Inserts/updates businesses, addresses, digital_presences, leads, and opportunities.
        Returns the business_id.
        """
        pass

    @abstractmethod
    def get_leads_by_campaign(self, campaign_name: str) -> List[Dict[str, Any]]:
        """
        Retrieves all parsed lead dicts belonging to a specific campaign/filename.
        Matches the properties expected by the original API client (name, phone, website, etc.).
        """
        pass

    @abstractmethod
    def check_duplicate(self, google_place_id: Optional[str], name: str, phone: Optional[str]) -> bool:
        """
        Deduplicates against historical database records.
        """
        pass
