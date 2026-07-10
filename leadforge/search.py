import asyncio
from typing import AsyncGenerator, List, Tuple
from playwright.async_api import async_playwright
from leadforge.config import USER_AGENT, HEADLESS_SCRAPING, PLAYWRIGHT_SLOWMO
from leadforge.utils import get_logger

logger = get_logger()

# One CDP round-trip per scroll iteration: collect non-sponsored place links and
# detect Google's actual end-of-results marker. Sponsored cards carry a literal
# "Sponsored" line (English guaranteed by hl=en); the end marker is the
# "You've reached the end of the list." feed footer (apostrophe variant-safe).
_FEED_SCAN_JS = """
    () => {
        const feed = document.querySelector('div[role="feed"]');
        const root = feed || document;
        const links = [];
        let sponsored = 0;
        for (const a of root.querySelectorAll('a[href*="/maps/place/"]')) {
            const card = a.closest('div[jsaction]') || a.parentElement;
            const text = card ? (card.innerText || '') : '';
            const isSponsored = text.split('\\n').some(
                (line) => line.trim().toLowerCase() === 'sponsored'
            );
            if (isSponsored) { sponsored += 1; continue; }
            links.push(a.href);
        }
        const feedText = (feed ? feed.innerText : document.body.innerText) || '';
        const end = /You.ve reached the end of the list/.test(feedText);
        return { links, sponsored, end };
    }
"""


async def discover_business_links(
    city: str, category: str, limit: int = 50, settings_cache=None
) -> Tuple[List[str], bool]:
    """Search Google Maps and return (links, discovery_failed).

    Returns a tuple so callers can distinguish "no results" (discovery_failed=False,
    links=[]) from "scraper error" (discovery_failed=True, links=[]).
    """
    search_query = f"{category} in {city}"
    search_url = (
        f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}?hl=en"
    )

    logger.info(
        f"Starting discovery on Google Maps for: '{search_query}' (limit: {limit})"
    )

    links: List[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS_SCRAPING,
            slow_mo=PLAYWRIGHT_SLOWMO,
            args=["--disable-gpu", "--no-sandbox"],
        )
        from leadforge.repositories.settings import SQLiteSettingsRepository

        settings_repo = settings_cache or SQLiteSettingsRepository()
        request_timeout = settings_repo.get_int("REQUEST_TIMEOUT", 30)
        max_retries = settings_repo.get_int("MAX_RETRIES", 3)
        base_backoff = settings_repo.get_float("BASE_BACKOFF_SECONDS", 2.0)
        custom_user_agent = settings_repo.get_str("USER_AGENT", USER_AGENT)
        timeout_ms = request_timeout * 1000

        context = await browser.new_context(
            user_agent=custom_user_agent, viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        try:
            logger.info("Navigating to Google Maps search...")

            # Retry the initial navigation — a transient failure here would
            # silently return an empty list and be misdiagnosed as no results.
            nav_succeeded = False
            for attempt in range(max_retries + 1):
                try:
                    await page.goto(search_url, timeout=timeout_ms)
                    nav_succeeded = True
                    break
                except Exception as nav_err:
                    if attempt < max_retries:
                        backoff = base_backoff * (2**attempt)
                        logger.warning(
                            f"Maps navigation attempt {attempt + 1} failed, "
                            f"retrying in {backoff:.1f}s: {nav_err}"
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            f"Maps navigation failed after {max_retries + 1} attempts: {nav_err}"
                        )
                        return [], True  # discovery_failed=True

            if not nav_succeeded:
                return [], True

            # Wait for search results feed
            try:
                await page.wait_for_selector('a[href*="/maps/place/"]', timeout=15000)
            except Exception:
                logger.warning(
                    "Timeout waiting for initial place links — may be CAPTCHA or empty results."
                )

            feed_selector = 'div[role="feed"]'
            scrolled_items = set()
            attempts = 0
            max_attempts = max(30, limit // 4)
            dry_streak = 0
            sponsored_skipped = 0

            while len(scrolled_items) < limit and attempts < max_attempts:
                prev_count = len(scrolled_items)

                scan = await page.evaluate(_FEED_SCAN_JS)
                sponsored_skipped = max(sponsored_skipped, scan["sponsored"])
                for href in scan["links"]:
                    if href and href not in scrolled_items:
                        scrolled_items.add(href)

                if scan["end"]:
                    logger.info(
                        "Google end-of-results marker detected "
                        f"({len(scrolled_items)} links found). Stopping discovery."
                    )
                    break

                if len(scrolled_items) >= limit:
                    break

                if len(scrolled_items) == prev_count:
                    dry_streak += 1
                    if dry_streak >= 2:
                        logger.info(
                            f"End of Google Maps results after {attempts + 1} scroll(s) "
                            f"({len(scrolled_items)} links found). Search space exhausted."
                        )
                        break
                else:
                    dry_streak = 0

                feed_panel = await page.query_selector(feed_selector)
                if feed_panel:
                    await page.evaluate("(el) => el.scrollBy(0, 1200)", feed_panel)
                    await asyncio.sleep(1.5)
                else:
                    await page.evaluate("window.scrollBy(0, 1200)")
                    await asyncio.sleep(1.5)

                attempts += 1
                logger.info(
                    f"Scroll iteration {attempts}: Found {len(scrolled_items)} links so far..."
                )

            links = list(scrolled_items)[:limit]
            if sponsored_skipped:
                logger.info(f"Skipped {sponsored_skipped} sponsored listing(s).")
            logger.info(f"Discovered {len(links)} business listing URLs.")

        except Exception as e:
            logger.error(f"Search discovery error: {str(e)}")
            return [], True  # discovery_failed=True
        finally:
            await browser.close()

    return links, False  # discovery_failed=False


async def discover_business_links_stream(
    city: str, category: str, limit: int = 50, settings_cache=None, context=None
) -> AsyncGenerator[str, None]:
    """Async generator: yields Google Maps place URLs one at a time during scrolling.

    context: optional externally-managed Playwright BrowserContext.  When provided
        the function creates a page within it and closes only that page on exit —
        the browser lifecycle is the caller's responsibility.  When None, the
        function creates and destroys its own browser (backward-compatible mode).
    Raises RuntimeError("DISCOVERY_FAILED") if the initial navigation fails.
    """
    search_query = f"{category} in {city}"
    search_url = (
        f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}?hl=en"
    )

    logger.info(f"Starting streaming discovery for: '{search_query}' (budget: {limit})")

    from leadforge.repositories.settings import SQLiteSettingsRepository

    settings_repo = settings_cache or SQLiteSettingsRepository()
    request_timeout = settings_repo.get_int("REQUEST_TIMEOUT", 30)
    max_retries = settings_repo.get_int("MAX_RETRIES", 3)
    base_backoff = settings_repo.get_float("BASE_BACKOFF_SECONDS", 2.0)
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
        nav_succeeded = False
        for attempt in range(max_retries + 1):
            try:
                await page.goto(search_url, timeout=timeout_ms)
                nav_succeeded = True
                break
            except Exception as nav_err:
                if attempt < max_retries:
                    backoff = base_backoff * (2**attempt)
                    logger.warning(
                        f"Maps navigation attempt {attempt + 1} failed, "
                        f"retrying in {backoff:.1f}s: {nav_err}"
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        f"Maps navigation failed after {max_retries + 1} attempts: {nav_err}"
                    )
                    raise RuntimeError("DISCOVERY_FAILED") from nav_err

        if not nav_succeeded:
            raise RuntimeError("DISCOVERY_FAILED")

        try:
            await page.wait_for_selector('a[href*="/maps/place/"]', timeout=15000)
        except Exception:
            logger.warning(
                "Timeout waiting for initial place links — may be CAPTCHA or empty results."
            )

        feed_selector = 'div[role="feed"]'
        scrolled_items: set = set()
        attempts = 0
        max_attempts = max(30, limit // 4)
        dry_streak = 0
        sponsored_skipped = 0

        while len(scrolled_items) < limit and attempts < max_attempts:
            prev_count = len(scrolled_items)

            scan = await page.evaluate(_FEED_SCAN_JS)
            sponsored_skipped = max(sponsored_skipped, scan["sponsored"])
            for href in scan["links"]:
                if href and href not in scrolled_items:
                    scrolled_items.add(href)
                    yield href

            if scan["end"]:
                logger.info(
                    "Google end-of-results marker detected "
                    f"({len(scrolled_items)} links yielded). Stopping discovery."
                )
                break

            if len(scrolled_items) >= limit:
                break

            if len(scrolled_items) == prev_count:
                dry_streak += 1
                if dry_streak >= 2:
                    logger.info(
                        f"End of Google Maps results after {attempts + 1} scroll(s) "
                        f"({len(scrolled_items)} links found). Search space exhausted."
                    )
                    break
            else:
                dry_streak = 0

            feed_panel = await page.query_selector(feed_selector)
            if feed_panel:
                await page.evaluate("(el) => el.scrollBy(0, 1200)", feed_panel)
                await asyncio.sleep(1.5)
            else:
                await page.evaluate("window.scrollBy(0, 1200)")
                await asyncio.sleep(1.5)

            attempts += 1
            logger.info(
                f"Scroll iteration {attempts}: Found {len(scrolled_items)} links so far..."
            )

        if sponsored_skipped:
            logger.info(f"Skipped {sponsored_skipped} sponsored listing(s).")
        logger.info(
            f"Streaming discovery complete: {len(scrolled_items)} URLs yielded."
        )

    finally:
        await page.close()
        if own_browser:
            await browser.close()
            await pw.stop()
