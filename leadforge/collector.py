import asyncio
import re
import json
from typing import List, Dict, Any
from playwright.async_api import async_playwright
from leadforge.config import USER_AGENT, HEADLESS_SCRAPING
from leadforge.parser import parse_business_details
from leadforge.utils import get_logger
from leadforge.repositories.settings import SQLiteSettingsRepository

logger = get_logger()

async def goto_with_retry(page, url: str, max_retries: int, base_backoff: float, timeout_ms: int) -> bool:
    """
    Navigates to a URL with exponential backoff retries.
    """
    retries = 0
    while retries <= max_retries:
        try:
            logger.info(f"Navigating to details URL (Attempt {retries + 1}/{max_retries + 1})")
            await page.goto(url, timeout=timeout_ms)
            # Sleep briefly to ensure maps javascript runs
            await asyncio.sleep(2.0)
            return True
        except Exception as e:
            retries += 1
            if retries > max_retries:
                logger.error(f"Failed to load details URL after {max_retries} retries: {str(e)}")
                raise e
            backoff_delay = base_backoff * (2 ** (retries - 1))
            logger.warning(f"Navigation failed. Retrying in {backoff_delay:.2f}s... Error: {str(e)}")
            await asyncio.sleep(backoff_delay)
    return False

async def collect_business_details(links: List[str], category: str) -> List[Dict[str, Any]]:
    """
    Given a list of Google Maps links, navigate to each and collect detailed attributes.
    Supports dynamic rate limits, retries, and extra attributes (ratings, reviews, hours, etc.).
    """
    logger.info(f"Starting detail collection for {len(links)} business links...")
    leads = []

    # Load dynamic scraper settings from the repository
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
            args=["--disable-gpu", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent=custom_user_agent,
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        for idx, link in enumerate(links, 1):
            try:
                logger.info(f"[{idx}/{len(links)}] Fetching business page...")

                # Apply request throttling delay before loading
                if idx > 1 and throttle_delay > 0:
                    await asyncio.sleep(throttle_delay)

                # Load detail page with retry backoff
                await goto_with_retry(page, link, max_retries, base_backoff, timeout_ms)

                # 1. Name
                name = ""
                name_el = await page.query_selector('h1.DUwDvf')
                if name_el:
                    name = await name_el.inner_text()
                if not name:
                    name_el = await page.query_selector('h1')
                    if name_el:
                        name = await name_el.inner_text()

                if not name:
                    logger.warning(f"[{idx}/{len(links)}] Could not retrieve business name, skipping.")
                    continue

                # 2. Phone
                phone_data = ""
                phone_el = await page.query_selector('button[data-item-id^="phone:tel:"]')
                if phone_el:
                    phone_data = await phone_el.get_attribute("data-item-id")

                # 3. Website
                website = ""
                website_el = await page.query_selector('a[data-item-id="authority"]')
                if website_el:
                    website = await website_el.get_attribute("href")

                # 4. Address
                address = ""
                address_el = await page.query_selector('button[data-item-id^="address"]')
                if address_el:
                    address = await address_el.get_attribute("aria-label")

                # 5. Rating (Phase 2)
                rating = None
                rating_el = await page.query_selector('div.F7nice span')
                if rating_el:
                    rating_text = await rating_el.inner_text()
                    if rating_text:
                        try:
                            rating = float(rating_text.strip())
                        except Exception:
                            pass

                # 6. Review Count (Phase 2)
                review_count = None
                reviews_el = await page.query_selector('div.F7nice span:nth-child(2)')
                if not reviews_el:
                    reviews_el = await page.query_selector('button.HH25fe')
                if reviews_el:
                    reviews_text = await reviews_el.inner_text()
                    if reviews_text:
                        digits = re.sub(r'\D', '', reviews_text)
                        if digits:
                            try:
                                review_count = int(digits)
                            except Exception:
                                pass

                # 7. Business Status (Phase 2)
                business_status = "OPERATIONAL"
                closed_el = await page.query_selector('span[style*="color: rgb(217, 48, 37)"]')
                if closed_el:
                    closed_text = await closed_el.inner_text()
                    if "closed" in closed_text.lower():
                        business_status = "TEMPORARILY_CLOSED" if "temporarily" in closed_text.lower() else "PERMANENTLY_CLOSED"

                # 8. Categories (Phase 2)
                categories_list = []
                cat_elements = await page.query_selector_all('button.DkEaCc')
                for cat_el in cat_elements:
                    cat_text = await cat_el.inner_text()
                    if cat_text and cat_text not in categories_list:
                        categories_list.append(cat_text)
                if category and category not in categories_list:
                    categories_list.insert(0, category)
                categories_json = json.dumps(categories_list)

                # 9. Opening Hours (Phase 2)
                opening_hours = ""
                hours_el = await page.query_selector('button[data-item-id="oh"]')
                if hours_el:
                    opening_hours = await hours_el.get_attribute("aria-label")
                if not opening_hours:
                    hours_el = await page.query_selector('div[data-item-id="oh"]')
                    if hours_el:
                        opening_hours = await hours_el.inner_text()

                # 10. Emails and Social Profiles (Phase 2 Link Scanning)
                email = ""
                social_links = []
                all_links = await page.query_selector_all('a[href]')
                for lnk in all_links:
                    href = await lnk.get_attribute("href")
                    if not href:
                        continue
                    if "mailto:" in href:
                        email = href.replace("mailto:", "").split("?")[0].strip()
                    elif any(dom in href for dom in ["facebook.com", "instagram.com", "twitter.com", "linkedin.com", "youtube.com"]):
                        if href not in social_links:
                            social_links.append(href)
                social_links_json = json.dumps(social_links)

                # Clean and parse basic attributes
                lead = parse_business_details(
                    name=name,
                    phone_data=phone_data,
                    website=website,
                    address=address,
                    category=category,
                    source_url=link
                )

                # Enrich with extra Phase 2 scraper columns
                lead["rating"] = rating
                lead["review_count"] = review_count
                lead["business_status"] = business_status
                lead["opening_hours"] = opening_hours
                lead["categories"] = categories_json
                lead["email"] = email
                lead["social_links"] = social_links_json

                leads.append(lead)
                logger.info(f"Collected details: '{lead['name']}' | Status: {lead['business_status']} | Rating: {lead['rating']} ({lead['review_count']} reviews)")

            except Exception as e:
                # Graceful recovery: Log error but continue session to prevent complete termination
                logger.error(f"[{idx}/{len(links)}] Transient error collecting business details: {str(e)}")
                continue

        await browser.close()

    return leads
