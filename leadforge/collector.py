import asyncio
from typing import List, Dict, Any
from playwright.async_api import async_playwright
from leadforge.config import USER_AGENT, HEADLESS_SCRAPING, PLAYWRIGHT_TIMEOUT
from leadforge.parser import parse_business_details
from leadforge.utils import get_logger

logger = get_logger()

async def collect_business_details(links: List[str], category: str) -> List[Dict[str, Any]]:
    """
    Given a list of Google Maps links, navigate to each and collect name, phone, website, and address.
    """
    logger.info(f"Starting detail collection for {len(links)} business links...")
    leads = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS_SCRAPING,
            args=["--disable-gpu", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        for idx, link in enumerate(links, 1):
            try:
                logger.info(f"[{idx}/{len(links)}] Navigating to details for listing...")
                await page.goto(link, timeout=PLAYWRIGHT_TIMEOUT)
                # Wait for loading
                await asyncio.sleep(2.0)

                # Name
                name = ""
                name_el = await page.query_selector('h1.DUwDvf')
                if name_el:
                    name = await name_el.inner_text()
                if not name:
                    name_el = await page.query_selector('h1')
                    if name_el:
                        name = await name_el.inner_text()

                # Phone
                phone_data = ""
                phone_el = await page.query_selector('button[data-item-id^="phone:tel:"]')
                if phone_el:
                    phone_data = await phone_el.get_attribute("data-item-id")

                # Website
                website = ""
                website_el = await page.query_selector('a[data-item-id="authority"]')
                if website_el:
                    website = await website_el.get_attribute("href")

                # Address
                address = ""
                address_el = await page.query_selector('button[data-item-id^="address"]')
                if address_el:
                    address = await address_el.get_attribute("aria-label")

                if not name:
                    logger.warning(f"[{idx}/{len(links)}] Could not retrieve name, skipping.")
                    continue

                # Parse and clean details
                lead = parse_business_details(
                    name=name,
                    phone_data=phone_data,
                    website=website,
                    address=address,
                    category=category,
                    source_url=link
                )

                leads.append(lead)
                logger.info(f"Collected: '{lead['name']}' | Phone: {lead['phone']} | Website: {lead['website']}")

            except Exception as e:
                logger.error(f"[{idx}/{len(links)}] Error collecting listing details: {str(e)}")
                # Continue collecting from other links
                continue

        await browser.close()

    return leads
