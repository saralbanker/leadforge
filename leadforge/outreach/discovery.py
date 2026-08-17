import re
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from leadforge.database import get_db_connection
from leadforge.utils import get_logger

# Suppress insecure request warnings for self-signed certificates during fallback fetches
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_logger()

# Generic/Mock emails to filter out from discovered lists
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
    "info@wix.com"
}


def extract_emails_from_text(text: str) -> List[str]:
    """Scrapes clean, unique, and valid email strings from raw text blocks."""
    pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    found = pattern.findall(text)
    emails: List[str] = []
    for email in found:
        email_clean = email.strip().lower()
        if email_clean not in GENERIC_EMAILS_IGNORE and email_clean not in emails:
            # Skip media extension matches
            if not any(email_clean.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]):
                emails.append(email_clean)
    return emails


def is_duplicate_outreach(
    business_id: str,
    email: Optional[str] = None,
    domain: Optional[str] = None,
    exclude_draft_id: Optional[str] = None,
) -> bool:
    """Multi-tier deduplication check against the SQLite email_drafts queue.

    Prevents sending duplicate emails to the same company, address, or website domain.
    When exclude_draft_id is provided, ignores that draft to allow regeneration.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Tier 1: Check by business_id
        query1 = """
            SELECT 1 FROM email_drafts ed
            JOIN opportunities o ON ed.opportunity_id = o.id
            WHERE o.business_id = ?
        """
        params1 = [business_id]
        if exclude_draft_id:
            query1 += " AND ed.id != ?"
            params1.append(exclude_draft_id)
        cursor.execute(query1, tuple(params1))
        if cursor.fetchone():
            return True

        # Tier 2: Check by recipient_email
        if email:
            email_clean = email.strip().lower()
            query2 = "SELECT 1 FROM email_drafts WHERE recipient_email = ?"
            params2 = [email_clean]
            if exclude_draft_id:
                query2 += " AND id != ?"
                params2.append(exclude_draft_id)
            cursor.execute(query2, tuple(params2))
            if cursor.fetchone():
                return True

        # Tier 3: Check by website domain
        if domain:
            domain_clean = domain.strip().lower().replace("www.", "")
            query3 = """
                SELECT 1 FROM email_drafts ed
                JOIN opportunities o ON ed.opportunity_id = o.id
                JOIN businesses b ON o.business_id = b.id
                WHERE (b.website_domain LIKE ? OR b.website_domain LIKE ?)
            """
            params3 = [f"%{domain_clean}%", f"%www.{domain_clean}%"]
            if exclude_draft_id:
                query3 += " AND ed.id != ?"
                params3.append(exclude_draft_id)
            cursor.execute(query3, tuple(params3))
            if cursor.fetchone():
                return True

        return False
    finally:
        conn.close()


class WebsiteAuditor:
    """Deterministic crawler executing HTTP audits on target pages."""

    @staticmethod
    def audit_website(url: str) -> Dict[str, Any]:
        """Performs a secure and fast technical audit of the website.

        Returns:
            Dictionary containing has_website, ssl_valid, load_time_seconds,
            viewport_mobile, cms, has_booking, discovered_emails, and cleaned_text.
        """
        result: Dict[str, Any] = {
            "has_website": False,
            "ssl_valid": False,
            "load_time_seconds": 0.0,
            "viewport_mobile": True,
            "cms": "Custom",
            "has_booking": False,
            "discovered_emails": [],
            "cleaned_text": "",
        }

        if not url:
            return result

        # Standardize URL protocol
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        result["has_website"] = True
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        response = None
        start_time = time.time()

        # 1. Attempt secure request, fallback to unverified SSL if necessary to get page text
        try:
            response = requests.get(url, headers=headers, timeout=10, verify=True)
            result["load_time_seconds"] = round(response.elapsed.total_seconds(), 2)
            result["ssl_valid"] = True
        except requests.exceptions.SSLError:
            result["ssl_valid"] = False
            try:
                response = requests.get(url, headers=headers, timeout=10, verify=False)
                result["load_time_seconds"] = round(time.time() - start_time, 2)
            except Exception as e:
                logger.warning(f"Failed insecure fallback fetch on SSL mismatch for {url}: {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch website {url}: {e}")
            result["has_website"] = False

        if not response or response.status_code != 200:
            return result

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        # 2. Extract viewport meta-tag properties for mobile audit
        viewport = soup.find("meta", attrs={"name": "viewport"})
        if viewport and "width=device-width" not in str(viewport.get("content", "")):
            result["viewport_mobile"] = False

        # 3. Detect CMS based on file path naming conventions
        html_lower = html.lower()
        if "wp-content" in html_lower or "wp-includes" in html_lower:
            result["cms"] = "WordPress"
        elif "wix.com" in html_lower or "wixsite" in html_lower:
            result["cms"] = "Wix"
        elif "shopify.theme" in html_lower or "shopify.cdn" in html_lower:
            result["cms"] = "Shopify"
        elif "squarespace" in html_lower:
            result["cms"] = "Squarespace"

        # 4. Check for appointment scheduling system embeds
        booking_providers = ["calendly.com", "acuityscheduling.com", "bookingbug.com", "appointy.com"]
        if any(p in html_lower for p in booking_providers):
            result["has_booking"] = True

        # 5. Extract unique emails
        discovered_emails: List[str] = []

        # Find mailto tags
        for link in soup.find_all("a", href=re.compile(r"^mailto:", re.IGNORECASE)):
            href = str(link.get("href", ""))
            match = re.search(r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", href, re.IGNORECASE)
            if match:
                discovered_emails.append(match.group(1).lower())

        # Scan page text body
        raw_text = soup.get_text(separator=" ")
        text_emails = extract_emails_from_text(raw_text)
        discovered_emails.extend(text_emails)

        # Deduplicate list
        final_emails: List[str] = []
        for email in discovered_emails:
            email_clean = email.strip().lower()
            if email_clean not in final_emails and email_clean not in GENERIC_EMAILS_IGNORE:
                final_emails.append(email_clean)
        result["discovered_emails"] = final_emails

        # 6. Extract clean text snippet for model context, discarding boilerplates
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        body_text = soup.get_text(separator=" ")
        result["cleaned_text"] = " ".join(body_text.split())[:5000]

        return result
