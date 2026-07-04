import asyncio
from typing import List
from playwright.async_api import async_playwright
from leadforge.config import USER_AGENT, HEADLESS_SCRAPING
from leadforge.utils import get_logger

logger = get_logger()

async def discover_business_links(city: str, category: str, limit: int = 50) -> List[str]:
    """
    Search for businesses using Google Maps via Playwright and return their page links.
    """
    search_query = f"{category} in {city}"
    search_url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"

    logger.info(f"Starting discovery on Google Maps for: '{search_query}' (limit: {limit})")

    links = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS_SCRAPING,
            args=["--disable-gpu", "--no-sandbox"]
        )
        # Load dynamic scraper settings from the repository
        from leadforge.repositories.settings import SQLiteSettingsRepository
        settings_repo = SQLiteSettingsRepository()
        request_timeout = settings_repo.get_int("REQUEST_TIMEOUT", 30)
        custom_user_agent = settings_repo.get_str("USER_AGENT", USER_AGENT)
        timeout_ms = request_timeout * 1000

        context = await browser.new_context(
            user_agent=custom_user_agent,
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        try:
            logger.info("Navigating to Google Maps search...")
            await page.goto(search_url, timeout=timeout_ms)

            # Wait for search results or feed panel
            try:
                await page.wait_for_selector('a[href*="/maps/place/"]', timeout=15000)
            except Exception:
                logger.warning("Timeout waiting for initial place links. Checking if empty page.")

            feed_selector = 'div[role="feed"]'
            scrolled_items = set()
            attempts = 0
            max_attempts = 15

            while len(scrolled_items) < limit and attempts < max_attempts:
                # Find all place links
                place_links = await page.query_selector_all('a[href*="/maps/place/"]')

                for link in place_links:
                    href = await link.get_attribute("href")
                    if href and href not in scrolled_items:
                        scrolled_items.add(href)

                if len(scrolled_items) >= limit:
                    break

                # Scroll down the feed panel
                feed_panel = await page.query_selector(feed_selector)
                if feed_panel:
                    await page.evaluate(
                        "(element) => element.scrollBy(0, 1200)",
                        feed_panel
                    )
                    await asyncio.sleep(1.5)
                else:
                    await page.evaluate("window.scrollBy(0, 1200)")
                    await asyncio.sleep(1.5)

                attempts += 1
                logger.info(f"Scroll iteration {attempts}: Found {len(scrolled_items)} leads so far...")

            links = list(scrolled_items)[:limit]
            logger.info(f"Discovered {len(links)} business listing URLs.")

        except Exception as e:
            logger.error(f"Search discovery error: {str(e)}")
        finally:
            await browser.close()

    return links
