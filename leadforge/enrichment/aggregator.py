"""Email Candidate Aggregator module for LeadForge Business Enrichment Layer.

Handles deduplication, syntax validation, generic ignore-list filtering,
async MX domain verification, and source-weighted confidence scoring.
"""

import asyncio
import re
import socket
from typing import List, Dict, Optional
from leadforge.enrichment.base import EnrichmentResult
from leadforge.utils import get_logger

logger = get_logger()

# Generic / boilerplate emails and domains ignored across all providers
GENERIC_EMAILS_IGNORE = {
    "sentry@example.com",
    "wix-code@example.com",
    "domain@example.com",
    "sentry-io@example.com",
    "noreply@example.com",
    "no-reply@example.com",
    "test@example.com",
    "example@example.com",
    "email@example.com",
    "info@example.com",
    "office@example.com",
    "support@wix.com",
    "info@wix.com",
    "feedback@justdial.com",
    "investor@justdial.com",
    "helpdesk@justdial.com",
    "support@indiamart.com",
    "customercare@indiamart.com",
    "helpdesk@tradeindia.com",
    "support@tradeindia.com",
}

IGNORED_EMAIL_DOMAINS = {
    "example.com",
    "justdial.com",
    "jdmagicbox.com",
    "indiamart.com",
    "tradeindia.com",
    "sentry.io",
    "w3.org",
    "schema.org",
    "cloudflare.com",
    "google.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "linkedin.com",
    "youtube.com",
    "wixpress.com",
    "wordpress.org",
    "gravatar.com",
}

_INVALID_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    ".pdf",
)
_EMAIL_SYNTAX_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


class EmailCandidateAggregator:
    """Aggregates, filters, ranks, and selects candidate emails from providers."""

    def __init__(self, verify_mx: bool = False):
        self._verify_mx = verify_mx
        self._mx_cache: Dict[str, bool] = {}

    async def aggregate(
        self, candidate_results: List[EnrichmentResult]
    ) -> tuple[Optional[EnrichmentResult], List[EnrichmentResult]]:
        """Deduplicates, validates, ranks, and selects the top email candidate.

        Returns:
            Tuple of (top_selected_candidate, list_of_all_valid_candidates_ranked)
        """
        if not candidate_results:
            return None, []

        valid_map: Dict[str, EnrichmentResult] = {}

        for item in candidate_results:
            email_clean = item.email.strip().lower()

            # 1. Syntax check
            if not _EMAIL_SYNTAX_REGEX.match(email_clean):
                continue

            # 2. Asset extension check
            if any(email_clean.endswith(ext) for ext in _INVALID_EXTENSIONS):
                continue

            # 3. Generic ignore-list & domain blacklist check
            domain = email_clean.split("@")[-1]
            if email_clean in GENERIC_EMAILS_IGNORE or domain in IGNORED_EMAIL_DOMAINS:
                continue

            # Deduplicate by email address, keeping the highest confidence score result
            if (
                email_clean not in valid_map
                or item.confidence_score > valid_map[email_clean].confidence_score
            ):
                valid_map[email_clean] = item

        candidates = list(valid_map.values())
        if not candidates:
            return None, []

        # 4. Optional MX verification check
        if self._verify_mx:
            verified_candidates = []
            for cand in candidates:
                cand_domain = cand.email.split("@")[-1]
                has_mx = await self._check_domain_has_mx(cand_domain)
                if has_mx:
                    verified_candidates.append(cand)
                else:
                    logger.debug(f"[Aggregator] Domain {cand_domain} failed MX lookup for {cand.email}")
            candidates = verified_candidates

        if not candidates:
            return None, []

        # 5. Rank candidates by confidence score DESC
        ranked = sorted(candidates, key=lambda c: c.confidence_score, reverse=True)
        top_candidate = ranked[0]

        return top_candidate, ranked

    async def _check_domain_has_mx(self, domain: str) -> bool:
        if not domain or "." not in domain:
            return False
        if domain in self._mx_cache:
            return self._mx_cache[domain]

        loop = asyncio.get_event_loop()
        try:
            # 1. Try resolving MX records using dnspython if installed
            try:
                import dns.asyncresolver
                answers = await dns.asyncresolver.resolve(domain, "MX")
                if answers:
                    self._mx_cache[domain] = True
                    return True
            except (ImportError, Exception):
                pass

            # 2. Fallback: Hostname address resolution for domain existence
            await loop.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
            self._mx_cache[domain] = True
            return True
        except Exception:
            self._mx_cache[domain] = False
            return False
