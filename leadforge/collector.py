import asyncio
import re
import json
from typing import AsyncGenerator, List, Dict, Any, Optional
from playwright.async_api import async_playwright
from leadforge.config import USER_AGENT, HEADLESS_SCRAPING, PLAYWRIGHT_SLOWMO
from leadforge.parser import parse_business_details
from leadforge.utils import get_logger
from leadforge.repositories.settings import SQLiteSettingsRepository

logger = get_logger()


async def goto_with_retry(
    page, url: str, max_retries: int, base_backoff: float, timeout_ms: int
) -> bool:
    """Navigates to a URL with exponential backoff retries."""
    retries = 0
    while retries <= max_retries:
        try:
            logger.info(
                f"Navigating to details URL (Attempt {retries + 1}/{max_retries + 1})"
            )
            await page.goto(url, timeout=timeout_ms)
            return True
        except Exception as e:
            retries += 1
            if retries > max_retries:
                logger.error(
                    f"Failed to load details URL after {max_retries} retries: {str(e)}"
                )
                raise e
            backoff_delay = base_backoff * (2 ** (retries - 1))
            logger.warning(
                f"Navigation failed. Retrying in {backoff_delay:.2f}s... Error: {str(e)}"
            )
            await asyncio.sleep(backoff_delay)
    return False


def _with_english_locale(url: str) -> str:
    """Force English UI text on Google Maps pages so deterministic extraction
    (status phrases, "reviews"/"stars" aria-labels) is language-stable."""
    if not url or "hl=" in url:
        return url
    return url + ("&hl=en" if "?" in url else "?hl=en")


# Aria-label patterns (English, guaranteed by hl=en):
#   "4.6 stars 1,234 Reviews"  — stars span on the header
#   "1,234 reviews"            — reviews button
_ARIA_RATING_RE = re.compile(r"^(\d(?:\.\d)?)\s+stars?\b", re.IGNORECASE)
_ARIA_REVIEWS_EXACT_RE = re.compile(r"^([\d,]+)\s+reviews?$", re.IGNORECASE)
_ARIA_REVIEWS_COMBINED_RE = re.compile(r"stars?\s+([\d,]+)\s+reviews?", re.IGNORECASE)


def _rating_from_aria(aria_labels: list) -> Optional[float]:
    """Deterministically parse the star rating from collected aria-labels."""
    for label in aria_labels or []:
        match = _ARIA_RATING_RE.match((label or "").strip())
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if 1.0 <= value <= 5.0:
                return value
    return None


def _reviews_from_aria(aria_labels: list) -> Optional[int]:
    """Deterministically parse the review count from collected aria-labels.

    Exact "<n> reviews" labels are preferred; the combined stars label is the
    secondary source. No other label shapes are considered.
    """
    for label in aria_labels or []:
        match = _ARIA_REVIEWS_EXACT_RE.match((label or "").strip())
        if match:
            return int(match.group(1).replace(",", ""))
    for label in aria_labels or []:
        match = _ARIA_REVIEWS_COMBINED_RE.search((label or "").strip())
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _detect_business_status(page_title: str, aria_labels: list[str]) -> str:
    """Detect closed status from aria-label text rather than volatile CSS selectors."""
    combined = " ".join(aria_labels).lower()
    if "permanently closed" in combined:
        return "PERMANENTLY_CLOSED"
    if "temporarily closed" in combined or "closed temporarily" in combined:
        return "TEMPORARILY_CLOSED"
    return "OPERATIONAL"


def _bump(stats: Optional[Dict[str, int]], key: str) -> None:
    """Increment a shared observability counter when a stats dict is wired in."""
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


async def _scrape_page(
    page,
    category: str,
    city: str,
    link: str,
    idx: int,
    total: int,
    no_website_only: bool = False,
    website_filter: str = "ALL",
    tier1_stats: Optional[Dict[str, int]] = None,
    extraction_stats: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """Scrape one Google Maps business page using a two-tier extraction strategy.

    Tier-1: one CDP round-trip for qualification-critical fields (name, phone,
    website, aria-labels for status).  Businesses that fail early qualification
    are rejected immediately — Tier-2 extraction never runs for them.

    Tier-2: one CDP round-trip for all enrichment fields (address, rating,
    reviews, hours, categories, hrefs).  Runs only for Tier-1 survivors.
    """
    try:
        await page.wait_for_selector("h1.DUwDvf", timeout=8000)
    except Exception:
        try:
            await page.wait_for_selector("h1", timeout=3000)
        except Exception:
            pass

    # --- Tier-1: single CDP round-trip ---
    try:
        t1: dict = await page.evaluate("""
            () => {
                const h1 = document.querySelector('h1.DUwDvf') || document.querySelector('h1');
                const ph = document.querySelector('button[data-item-id^="phone:tel:"]');
                const ws = document.querySelector('a[data-item-id="authority"]');
                const al = Array.from(document.querySelectorAll('[aria-label]'))
                    .map(el => el.getAttribute('aria-label')).filter(Boolean);
                return {
                    name:        h1 ? h1.innerText.trim() : '',
                    phone:       ph ? ph.getAttribute('data-item-id') : '',
                    website:     ws ? ws.getAttribute('href') : '',
                    aria_labels: al
                };
            }
        """)
    except Exception:
        logger.warning(f"[{idx}] Tier-1 evaluate failed, skipping.")
        return None

    name = t1.get("name", "")
    phone_data = t1.get("phone", "")
    website = t1.get("website", "")
    aria_labels = t1.get("aria_labels", [])

    if not name:
        logger.warning(f"[{idx}/{total}] No business name found, skipping.")
        _bump(tier1_stats, "NO_NAME")
        return None

    business_status = _detect_business_status("", aria_labels)
    if business_status == "PERMANENTLY_CLOSED":
        logger.info(f"[{idx}] '{name}' permanently closed — skipping (Tier-1).")
        _bump(tier1_stats, "CLOSED")
        return None

    if not phone_data:
        logger.info(f"[{idx}] '{name}' has no phone — skipping (Tier-1).")
        _bump(tier1_stats, "NO_PHONE")
        return None

    # Tier-1 Website Filtering
    effective_no_website = no_website_only or (website_filter == "NO_WEBSITE")
    if effective_no_website and website:
        logger.info(
            f"[{idx}] '{name}' has a website — skipping (Tier-1 no-website filter)."
        )
        _bump(tier1_stats, "HAS_WEBSITE")
        return None

    if website_filter == "HAS_WEBSITE" and not website:
        logger.info(
            f"[{idx}] '{name}' has no website — skipping (Tier-1 has-website filter)."
        )
        _bump(tier1_stats, "NO_WEBSITE")
        return None

    # --- Tier-2: single CDP round-trip for enrichment (only qualified businesses reach here) ---
    try:
        t2: dict = await page.evaluate("""
            () => {
                const addr     = document.querySelector('button[data-item-id^="address"]');
                const rat      = document.querySelector('div.F7nice span');
                const rev      = document.querySelector('div.F7nice span:nth-child(2)')
                               || document.querySelector('button.HH25fe');
                const hoursBtn = document.querySelector('button[data-item-id="oh"]');
                const hoursAttr = hoursBtn ? hoursBtn.getAttribute('aria-label') : null;
                const hoursDiv  = !hoursAttr
                    ? document.querySelector('div[data-item-id="oh"]') : null;
                const hours = hoursAttr || (hoursDiv ? hoursDiv.innerText.trim() : '');
                const cats  = Array.from(document.querySelectorAll(
                        'button.DkEaL, button.DkEaCc, button[jsaction*="category"]'
                    )).map(el => el.innerText.trim()).filter(Boolean);
                const hrefs = Array.from(document.querySelectorAll('a[href]'))
                    .map(el => el.getAttribute('href')).filter(Boolean);
                return {
                    address:     addr ? addr.getAttribute('aria-label') : '',
                    rating_text: rat  ? rat.innerText.trim()             : null,
                    review_text: rev  ? rev.innerText.trim()             : null,
                    hours:       hours,
                    categories:  cats,
                    hrefs:       hrefs
                };
            }
        """)
    except Exception:
        t2 = {
            "address": "",
            "rating_text": None,
            "review_text": None,
            "hours": "",
            "categories": [],
            "hrefs": [],
        }

    address = t2.get("address", "")

    # Rating: aria-label is the primary deterministic source ("4.6 stars …");
    # the volatile CSS selector text is only a plausibility-checked fallback.
    rating = _rating_from_aria(aria_labels)
    if rating is None and t2.get("rating_text"):
        try:
            candidate = float(str(t2["rating_text"]).strip())
            if 1.0 <= candidate <= 5.0:
                rating = candidate
        except Exception:
            pass

    # Review count: aria-label first ("1,234 reviews"); selector text is a
    # fallback only when it actually looks like a count ("(1,234)" / "1,234").
    review_count = _reviews_from_aria(aria_labels)
    if review_count is None and t2.get("review_text"):
        review_text = str(t2["review_text"]).strip()
        if re.fullmatch(r"\(?[\d,]+\)?", review_text):
            digits = re.sub(r"\D", "", review_text)
            if digits:
                try:
                    review_count = int(digits)
                except Exception:
                    pass

    opening_hours = t2.get("hours", "")

    seen_cats: set = set()
    categories_list: list = []
    for c in t2.get("categories", []):
        if c not in seen_cats:
            seen_cats.add(c)
            categories_list.append(c)
    categories_json = json.dumps(categories_list)

    email = ""
    social_links: list = []
    for href in t2.get("hrefs", []):
        if "mailto:" in href:
            candidate = href.replace("mailto:", "").split("?")[0].strip()
            if candidate and not email:
                email = candidate
        elif any(
            dom in href
            for dom in [
                "facebook.com",
                "instagram.com",
                "twitter.com",
                "linkedin.com",
                "youtube.com",
            ]
        ):
            if href not in social_links:
                social_links.append(href)

    lead = parse_business_details(
        name=name,
        phone_data=phone_data,
        website=website,
        address=address,
        category=category,
        source_url=link,
        city=city,
    )
    lead["rating"] = rating
    lead["review_count"] = review_count
    lead["business_status"] = business_status
    lead["opening_hours"] = opening_hours
    lead["categories"] = categories_json
    # Google's own primary category — kept independent of the requested
    # search category so validation never compares a value against itself.
    lead["google_primary_category"] = categories_list[0] if categories_list else ""
    lead["email"] = email
    lead["social_links"] = json.dumps(social_links)

    # Extraction success observability (Tier-2 survivors only).
    if extraction_stats is not None:
        _bump(extraction_stats, "attempts")
        if rating is not None:
            _bump(extraction_stats, "rating")
        if review_count is not None:
            _bump(extraction_stats, "reviews")
        if categories_list:
            _bump(extraction_stats, "categories")
        if (lead.get("address") or "").strip():
            _bump(extraction_stats, "address")
        if (opening_hours or "").strip():
            _bump(extraction_stats, "opening_hours")

    return lead


async def collect_business_details(
    links: List[str], category: str, city: str = ""
) -> List[Dict[str, Any]]:
    """
    Given a list of Google Maps links, navigate to each and collect detailed attributes.
    Legacy non-streaming variant; used for batch collection outside the control plane.
    """
    logger.info(f"Starting detail collection for {len(links)} business links...")
    leads = []

    settings_repo = SQLiteSettingsRepository()
    max_retries = settings_repo.get_int("MAX_RETRIES", 3)
    base_backoff = settings_repo.get_float("BASE_BACKOFF_SECONDS", 2.0)
    throttle_delay = settings_repo.get_float("THROTTLE_DELAY", 1.0)
    request_timeout = settings_repo.get_int("REQUEST_TIMEOUT", 30)
    custom_user_agent = settings_repo.get_str("USER_AGENT", USER_AGENT)
    timeout_ms = request_timeout * 1000

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS_SCRAPING,
            slow_mo=PLAYWRIGHT_SLOWMO,
            args=["--disable-gpu", "--no-sandbox"],
        )
        try:
            context = await browser.new_context(
                user_agent=custom_user_agent, viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()

            for idx, link in enumerate(links, 1):
                try:
                    if idx > 1 and throttle_delay > 0:
                        await asyncio.sleep(throttle_delay)

                    logger.info(f"[{idx}/{len(links)}] Fetching business page...")
                    await goto_with_retry(
                        page,
                        _with_english_locale(link),
                        max_retries,
                        base_backoff,
                        timeout_ms,
                    )

                    lead = await _scrape_page(
                        page, category, city, link, idx, len(links)
                    )
                    if lead is None:
                        continue

                    leads.append(lead)
                    logger.info(
                        f"Collected: '{lead['name']}' | "
                        f"Status: {lead['business_status']} | Rating: {lead['rating']}"
                    )
                except Exception as e:
                    logger.error(f"[{idx}/{len(links)}] Transient error: {str(e)}")
                    continue
        finally:
            await browser.close()

    return leads


async def collect_business_details_stream(
    links,
    category: str,
    city: str = "",
    settings_cache=None,
    context=None,
    no_website_only: bool = False,
    website_filter: str = "ALL",
    tier1_stats: Optional[Dict[str, int]] = None,
    extraction_stats: Optional[Dict[str, int]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield one scraped lead dict per URL in links.

    links: List[str] or AsyncIterable[str].
    context: optional externally-managed Playwright BrowserContext.  When provided
        the function creates a page within it and closes only that page on exit —
        the browser lifecycle is the caller's responsibility.  When None, the
        function creates and destroys its own browser (backward-compatible mode).
    no_website_only: when True, Tier-1 rejects businesses that have a website
        before Tier-2 extraction runs.
    settings_cache: optional SettingsCache; avoids per-invocation DB lookups.
    tier1_stats / extraction_stats: optional shared counter dicts the caller
        owns (e.g. ScraperExecutionState) — incremented in place for
        observability; never alter scraping behaviour.
    """
    if isinstance(links, list) and not links:
        return

    if hasattr(links, "__aiter__"):
        links_iter = links
    else:

        async def _list_to_async_iter(lst):
            for item in lst:
                yield item

        links_iter = _list_to_async_iter(links)

    total_hint: Optional[int] = len(links) if isinstance(links, list) else None

    settings_repo = settings_cache or SQLiteSettingsRepository()
    max_retries = settings_repo.get_int("MAX_RETRIES", 3)
    base_backoff = settings_repo.get_float("BASE_BACKOFF_SECONDS", 2.0)
    throttle_delay = settings_repo.get_float("THROTTLE_DELAY", 1.0)
    request_timeout = settings_repo.get_int("REQUEST_TIMEOUT", 30)
    timeout_ms = request_timeout * 1000

    own_browser = context is None
    if own_browser:
        custom_user_agent = settings_repo.get_str("USER_AGENT", USER_AGENT)
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=HEADLESS_SCRAPING,
            slow_mo=PLAYWRIGHT_SLOWMO,
            args=["--disable-gpu", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=custom_user_agent, viewport={"width": 1280, "height": 800}
        )

    page = await context.new_page()

    try:
        idx = 0
        async for link in links_iter:
            idx += 1
            try:
                if idx > 1 and throttle_delay > 0:
                    await asyncio.sleep(throttle_delay)

                pos = f"{idx}/{total_hint}" if total_hint is not None else str(idx)
                logger.info(f"[{pos}] Fetching business page...")
                await goto_with_retry(
                    page,
                    _with_english_locale(link),
                    max_retries,
                    base_backoff,
                    timeout_ms,
                )

                total_for_scrape = total_hint if total_hint is not None else idx
                lead = await _scrape_page(
                    page,
                    category,
                    city,
                    link,
                    idx,
                    total_for_scrape,
                    no_website_only=no_website_only,
                    website_filter=website_filter,
                    tier1_stats=tier1_stats,
                    extraction_stats=extraction_stats,
                )
                if lead is None:
                    continue

                logger.info(
                    f"Collected: '{lead['name']}' | "
                    f"Status: {lead['business_status']} | Rating: {lead['rating']}"
                )
                yield lead

            except Exception as e:
                logger.error(f"[{idx}] Error collecting details: {e}")
                continue
    finally:
        await page.close()
        if own_browser:
            await browser.close()
            await pw.stop()
        # Release any blocked queue.get() in the upstream async iterator.
        aclose_fn = getattr(links_iter, "aclose", None)
        if aclose_fn is not None:
            try:
                await aclose_fn()
            except Exception:
                pass
