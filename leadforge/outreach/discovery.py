import re
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from leadforge.database import get_db_connection
from leadforge.normalizer import normalize_email, is_valid_recipient_email
from leadforge.utils import get_logger

# Suppress insecure request warnings for self-signed certificates during fallback fetches
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_logger()

# Generic/Mock/Theme vendor emails to filter out from discovered lists
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
    "info@elementskit.com",
    "support@elementskit.com",
    "info@wpengine.com",
    "info@elementor.com",
    "support@elementor.com",
    "info@themeforest.net",
    "help@envato.com",
    "customercare@indiamart.com",
    "support@indiamart.com",
}

IGNORED_EMAIL_DOMAINS = (
    "@indiamart.com",
    "@example.com",
    "@wix.com",
    "@sentry.io",
    "@wordpress.org",
    "@wordpress.com",
)


def extract_emails_from_text(text: str) -> List[str]:
    """Scrapes clean, unique, and valid email strings from raw text blocks."""
    pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    found = pattern.findall(text)
    emails: List[str] = []
    for email in found:
        email_clean = normalize_email(email)
        is_valid, _ = is_valid_recipient_email(email_clean)
        if (
            is_valid
            and email_clean not in GENERIC_EMAILS_IGNORE
            and not any(email_clean.endswith(dom) for dom in IGNORED_EMAIL_DOMAINS)
            and email_clean not in emails
        ):
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

    Only drafts that were actually sent, or are still queued to be sent, count as
    outreach. A CANCELLED or REJECTED draft never reached anyone, so treating it as
    a duplicate would permanently lock that business out of the pipeline - which is
    exactly what happened to the leads whose drafts were cancelled after the
    fabricated-address incident.
    """
    live_statuses = ("PENDING_APPROVAL", "APPROVED", "QUEUED", "SENT", "FAILED")
    status_sql = " AND ed.status IN (%s)" % ",".join("?" * len(live_statuses))
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Tier 1: Check by business_id
        query1 = """
            SELECT 1 FROM email_drafts ed
            JOIN opportunities o ON ed.opportunity_id = o.id
            WHERE o.business_id = ?
        """ + status_sql
        params1 = [business_id, *live_statuses]
        if exclude_draft_id:
            query1 += " AND ed.id != ?"
            params1.append(exclude_draft_id)
        cursor.execute(query1, tuple(params1))
        if cursor.fetchone():
            return True

        # Tier 2: Check by recipient_email
        if email:
            email_clean = email.strip().lower()
            query2 = ("SELECT 1 FROM email_drafts ed WHERE ed.recipient_email = ?"
                      + status_sql)
            params2 = [email_clean, *live_statuses]
            if exclude_draft_id:
                query2 += " AND ed.id != ?"
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
            """ + status_sql
            params3 = [f"%{domain_clean}%", f"%www.{domain_clean}%", *live_statuses]
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
            "has_order_flow": False,
            "has_contact_form": False,
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
        elif "woocommerce" in html_lower:
            result["cms"] = "WooCommerce"

        # 4. Check for appointment scheduling system embeds & booking widgets
        booking_providers = [
            "calendly.com", "acuityscheduling.com", "bookingbug.com", "appointy.com",
            "setmore.com", "simplybook.me", "tidycal.com", "zcal.co", "youcanbook.me"
        ]
        has_booking = any(p in html_lower for p in booking_providers)
        if not has_booking:
            booking_patterns = [r"book[-_]appointment", r"appointment[-_]booking", r"booking[-_]widget", r"online[-_]booking"]
            has_booking = any(re.search(pat, html_lower) for pat in booking_patterns)
        result["has_booking"] = bool(has_booking)

        # 5. Check for e-commerce / online order flow
        ecommerce_indicators = [
            "shopify", "woocommerce", "magento", "prestashop", "bigcommerce",
            "opencart", "snipcart", "ecwid", "add-to-cart", "add_to_cart",
            "/cart", "/checkout", "shopping-cart", "buy-now"
        ]
        has_order = result["cms"] in ("Shopify", "WooCommerce", "Magento", "BigCommerce", "PrestaShop", "OpenCart")
        if not has_order:
            has_order = any(ind in html_lower for ind in ecommerce_indicators)
        result["has_order_flow"] = bool(has_order)

        # 6. Check for working contact / inquiry form
        has_contact = False
        forms = soup.find_all("form")
        for form in forms:
            form_str = str(form).lower()
            inputs = form.find_all(["input", "textarea", "select"])
            input_types = [inp.get("type", "text").lower() for inp in inputs]
            if all(t in ("search", "hidden", "submit", "button") for t in input_types) and "search" in form_str:
                continue
            has_text_input = any(t in ("text", "email", "tel", "textarea") for t in input_types) or form.find_all("textarea")
            contact_hints = ["contact", "wpforms", "contact-form", "formspree", "ninja", "gravity", "enquiry", "inquiry", "quote", "lead", "feedback", "reach-us"]
            if has_text_input or any(h in form_str for h in contact_hints):
                has_contact = True
                break
        result["has_contact_form"] = bool(has_contact)

        # 7. Extract unique emails
        discovered_emails: List[str] = []

        # Find mailto tags
        for link in soup.find_all("a", href=re.compile(r"^mailto:", re.IGNORECASE)):
            href = str(link.get("href", ""))
            match = re.search(r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", href, re.IGNORECASE)
            if match:
                clean_m = normalize_email(match.group(1))
                if is_valid_recipient_email(clean_m)[0]:
                    discovered_emails.append(clean_m)

        # Scan page text body
        raw_text = soup.get_text(separator=" ")
        text_emails = extract_emails_from_text(raw_text)
        discovered_emails.extend(text_emails)

        # Deduplicate list
        final_emails: List[str] = []
        for email in discovered_emails:
            email_clean = normalize_email(email)
            if is_valid_recipient_email(email_clean)[0] and email_clean not in final_emails and email_clean not in GENERIC_EMAILS_IGNORE:
                final_emails.append(email_clean)

        # Fallback: check contact pages if no emails found on homepage
        if not final_emails and response and response.status_code == 200:
            import urllib.parse
            contact_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if any(k in href.lower() for k in ["contact", "reach", "about-us"]):
                    contact_links.append(href)
            for cl in contact_links[:2]:
                try:
                    c_url = urllib.parse.urljoin(url, cl)
                    c_resp = requests.get(c_url, headers=headers, timeout=5, verify=False)
                    if c_resp.status_code == 200:
                        c_soup = BeautifulSoup(c_resp.text, "html.parser")
                        for link in c_soup.find_all("a", href=re.compile(r"^mailto:", re.IGNORECASE)):
                            m = re.search(r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", str(link.get("href", "")), re.IGNORECASE)
                            if m:
                                em = normalize_email(m.group(1))
                                if is_valid_recipient_email(em)[0] and em not in final_emails and em not in GENERIC_EMAILS_IGNORE:
                                    final_emails.append(em)
                        for em in extract_emails_from_text(c_soup.get_text(separator=" ")):
                            if is_valid_recipient_email(em)[0] and em not in final_emails and em not in GENERIC_EMAILS_IGNORE:
                                final_emails.append(em)
                        if final_emails:
                            break
                except Exception:
                    pass

        result["discovered_emails"] = final_emails

        # 8. Extract clean text snippet for model context, discarding boilerplates
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        body_text = soup.get_text(separator=" ")
        result["cleaned_text"] = " ".join(body_text.split())[:5000]

        return result
