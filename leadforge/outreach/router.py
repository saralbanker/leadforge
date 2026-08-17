import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from leadforge.config import BASE_DIR
from leadforge.utils import get_logger

logger = get_logger()


class CampaignRouter:
    """Deterministic Campaign & Offer Router.

    Parses campaign_routing.yaml from the project root and evaluates
    lead metrics to assign the best campaign template and target offer.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        if config_path is None:
            config_path = BASE_DIR / "campaign_routing.yaml"
        self.config_path = config_path
        self.campaigns = self._load_config()

    def _load_config(self) -> List[Dict[str, Any]]:
        """Loads and parses campaign config file safely."""
        try:
            if not self.config_path.exists():
                logger.error(f"Campaign routing configuration file not found at: {self.config_path}")
                return []
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data or "campaigns" not in data:
                    logger.warning("Campaign configuration file is empty or missing 'campaigns' key.")
                    return []
                return data.get("campaigns", [])
        except Exception as e:
            logger.error(f"Failed to load campaign routing config: {str(e)}")
            return []

    def route_lead(
        self,
        category: str,
        has_website: bool,
        ssl_valid: bool = True,
        load_time_seconds: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """Evaluates routing criteria against lead properties.

        Returns:
            Matched campaign dictionary containing name, target_offer, and copy_template
            or None if no campaign criteria are satisfied.
        """
        category_clean = (category or "").strip().lower()

        for campaign in self.campaigns:
            criteria = campaign.get("criteria", {})

            # 1. Check website presence criteria
            req_has_website = criteria.get("has_website")
            if req_has_website is not None and req_has_website != has_website:
                continue

            # 2. Check SSL validation criteria
            req_ssl_valid = criteria.get("ssl_valid")
            if req_ssl_valid is not None and req_ssl_valid != ssl_valid:
                continue

            # 3. Check load time criteria
            max_load_time = criteria.get("max_load_time_seconds")
            if max_load_time is not None and load_time_seconds > max_load_time:
                continue

            # 4. Check category list criteria
            req_categories = criteria.get("categories")
            if req_categories is not None:
                allowed_cats = [str(c).strip().lower() for c in req_categories]
                if category_clean not in allowed_cats:
                    continue

            # All conditions met, return matched campaign config
            return campaign

        return None
