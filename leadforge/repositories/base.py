from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class RepositoryException(Exception):
    """Base exception class for all repository errors."""
    pass


class OpportunityRepositoryInterface(ABC):
    @abstractmethod
    def get_active_for_business(self, business_id: str) -> List[Dict[str, Any]]:
        """Returns all non-deleted opportunities for a given business."""
        pass

    @abstractmethod
    def title_exists_for_business(self, business_id: str, title: str) -> bool:
        """Returns True when an active (non-deleted) opportunity with this exact title
        already exists for the business — used to prevent duplicates."""
        pass

    @abstractmethod
    def create_with_scoring_logs(
        self,
        business_id: str,
        title: str,
        pipeline_stage: str,
        score: float,
        close_probability: float,
        estimated_value: float,
        scoring_logs: List[Dict[str, Any]],
    ) -> str:
        """Inserts a new opportunity and its scoring-log rows atomically.
        Returns the new opportunity's UUIDv7."""
        pass

    @abstractmethod
    def list_ranked(
        self,
        limit: Optional[int] = None,
        pipeline_stage: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Lists opportunities ranked by score DESC, then close_probability DESC.
        Supports optional stage filter and row limit."""
        pass

    @abstractmethod
    def get_scoring_logs(self, opportunity_id: str) -> List[Dict[str, Any]]:
        """Returns all scoring-log rows for a given opportunity."""
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
    def create(self, city: str, category: str, results_count: int, status: str, search_query: Optional[str] = None, limit_requested: Optional[int] = None, started_at: Optional[str] = None, scraper_version: Optional[str] = "2.0") -> str:
        """Logs a search run history, returning its generated UUIDv7."""
        pass

    @abstractmethod
    def complete(self, search_id: str, results_count: int, new_count: int, updated_count: int, failed_count: int, duplicate_count: int, finished_at: str, duration: float, status: str = "COMPLETED", metadata: Optional[str] = None):
        """Updates search run details upon completion."""
        pass

    @abstractmethod
    def list_all(self) -> List[Dict[str, Any]]:
        """Lists all search history entries sorted by created_at descending."""
        pass

class LeadRepositoryInterface(ABC):
    @abstractmethod
    def save_lead_transaction(self, lead_data: Dict[str, Any], campaign_name: str, search_id: Optional[str] = None) -> str:
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
