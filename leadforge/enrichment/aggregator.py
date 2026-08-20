"""Email Candidate Aggregator module for LeadForge Business Enrichment Layer.

Handles deduplication, syntax validation, generic ignore-list filtering,
async MX domain verification, and source-weighted confidence scoring.
"""

import asyncio
import re
import socket
from typing import List, Dict, Optional
from leadforge.enrichment.base import EnrichmentResult, is_non_business_host
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
# Local parts that reach a shared tray nobody owns, or an automated sink.
_ROLE_UNMONITORED = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "postmaster",
    "mailer-daemon", "bounce", "bounces", "abuse", "webmaster", "hostmaster",
    "privacy", "legal", "careers", "jobs", "hr", "recruitment", "unsubscribe",
}
# Shared but genuinely read by someone.
_ROLE_GENERIC = {"info", "office", "admin", "mail", "general", "reception", "care"}
# Shared, and read by someone who wants to hear from a supplier.
_ROLE_PREFERRED = {"sales", "enquiry", "enquiries", "inquiry", "contact", "marketing", "export", "purchase"}

# Fallback trust per provider when a result carries no priority_weight.
# Mirrors BaseEnrichmentProvider.priority_weight on each provider class.
_PROVIDER_WEIGHTS = {
    "official_website": 1.00,
    "indiamart": 0.85,
    "tradeindia": 0.80,
    "justdial": 0.75,
}

_EMAIL_SYNTAX_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


class EmailCandidateAggregator:
    """Aggregates, filters, ranks, and selects candidate emails from providers."""

    def __init__(self, verify_mx: bool = True):
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

            # An address at a platform/aggregator domain belongs to that platform.
            if is_non_business_host(domain):
                logger.debug(f"[Aggregator] Discarding platform address {email_clean}")
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

        # 5. Rank by effective score: provider trust x source quality x role.
        #    confidence_score alone is a per-provider constant, so without
        #    priority_weight a low-trust directory hit can outrank a website mailto:.
        ranked = sorted(candidates, key=self._effective_score, reverse=True)
        top_candidate = ranked[0]

        return top_candidate, ranked

    @staticmethod
    def role_multiplier(email: str) -> float:
        """Scores the local part by how likely a human is to read and reply to it."""
        local = email.split("@")[0].strip().lower()
        base = re.sub(r"[._-]?\d+$", "", local)
        if base in _ROLE_UNMONITORED:
            return 0.55
        if base in _ROLE_GENERIC:
            return 0.80
        if base in _ROLE_PREFERRED:
            return 1.0
        # Looks like a person's name (rajesh@, r.patel@) — the best kind of hit.
        if re.fullmatch(r"[a-z]+([._-][a-z]+)?", base) and len(base) >= 3:
            return 1.10
        return 0.90

    def _effective_score(self, cand: EnrichmentResult) -> float:
        weight = getattr(cand, "priority_weight", None)
        if not weight:
            weight = _PROVIDER_WEIGHTS.get(cand.source_provider, 0.75)
        return cand.confidence_score * weight * self.role_multiplier(cand.email)

    async def _check_domain_has_mx(self, domain: str) -> bool:
        if not domain or "." not in domain:
            return False
        if domain in self._mx_cache:
            return self._mx_cache[domain]

        loop = asyncio.get_event_loop()
        try:
            # 1. Authoritative check: does the domain publish an MX record?
            try:
                import dns.asyncresolver
            except ImportError:
                logger.debug(
                    "[Aggregator] dnspython not installed; falling back to A-record "
                    "resolution, which cannot prove the domain accepts mail."
                )
            else:
                try:
                    answers = await dns.asyncresolver.resolve(domain, "MX")
                    self._mx_cache[domain] = bool(answers)
                    return bool(answers)
                except Exception as exc:
                    # A real negative (NXDOMAIN / NoAnswer) — the domain takes no mail.
                    logger.debug(f"[Aggregator] No MX for {domain}: {type(exc).__name__}")
                    self._mx_cache[domain] = False
                    return False

            # 2. Fallback only when dnspython is absent: prove the domain at least exists.
            # family/type must be keyword args here — asyncio's getaddrinfo takes
            # only (host, port) positionally, unlike socket.getaddrinfo.
            await loop.getaddrinfo(
                domain, None, family=socket.AF_INET, type=socket.SOCK_STREAM
            )
            self._mx_cache[domain] = True
            return True
        except Exception:
            self._mx_cache[domain] = False
            return False
