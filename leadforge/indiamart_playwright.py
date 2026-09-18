"""IndiaMART Playwright Scraper for B2B Industrial Manufacturers.

Extracts verified manufacturing plants from IndiaMART category directories,
detects whether they have a standalone corporate website vs. only an IndiaMART
catalog profile, and returns structured lead profiles for outreach routing.
"""

import asyncio
import re
import urllib.parse
from typing import Dict, Any, List
from playwright.async_api import async_playwright
from leadforge.utils import get_logger

logger = get_logger()

CATEGORY_SLUG_MAP = {
    "industrial boilers": "industrial-boilers",
    "boiler manufacturer": "industrial-boilers",
    "boilers": "industrial-boilers",
    "chemical manufacturers": "industrial-chemicals",
    "chemical manufacturer": "industrial-chemicals",
    "chemicals": "industrial-chemicals",
    "speciality chemicals": "speciality-chemicals",
    "industrial valves": "industrial-valves",
    "valve manufacturer": "industrial-valves",
    "fabrication works": "fabrication-work",
    "fabrication engineer": "fabrication-work",
    "precision engineer": "cnc-machined-components",
    "cnc machining & precision components": "cnc-machined-components",
    "cnc machining manufacturer": "cnc-machined-components",
    "precision machining manufacturer": "cnc-machined-components",
    "machinery manufacturer": "industrial-machinery",
    "sheet metal manufacturer": "fabrication-work",
}


def get_indiamart_category_url(category: str, city: str = "Ahmedabad") -> str:
    """Constructs direct IndiaMART category URL for a city."""
    clean_cat = category.strip().lower().replace("-", " ")
    cat_slug = CATEGORY_SLUG_MAP.get(clean_cat)
    city_slug = city.strip().lower()

    if cat_slug:
        return f"https://dir.indiamart.com/{city_slug}/{cat_slug}.html"
    clean_query = urllib.parse.quote(f"{category} in {city}")
    return f"https://dir.indiamart.com/search.mp?ss={clean_query}"


async def scrape_indiamart_suppliers(
    city: str,
    category: str,
    limit: int = 30,
    timeout_seconds: float = 20.0,
) -> List[Dict[str, Any]]:
    """Scrapes industrial suppliers from IndiaMART with standalone website detection."""
    url = get_indiamart_category_url(category, city)
    logger.info(f"[IndiaMART Scraper] Fetching category page: {url}...")

    results: List[Dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )

                await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
                await page.wait_for_timeout(2500)

                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, 1500)")
                    await page.wait_for_timeout(800)

                raw_cards = await page.evaluate(r'''() => {
                    const cards = document.querySelectorAll('article, .template7-product-card, .pCard2, .lst_cl, [class*="product-card"]');
                    const nonCompanyWords = ["website", "visit website", "click here", "view details", "view catalog", "company profile", "get best quote", "call now", "contact supplier", "leading supplier", "view more"];

                    const isNonCorporateHost = (href) => {
                        const h = href.toLowerCase();
                        return (
                            h.includes('indiamart.com') ||
                            h.includes('google.com') ||
                            h.includes('imimg.com') ||
                            h.includes('facebook.com') ||
                            h.includes('twitter.com') ||
                            h.includes('x.com') ||
                            h.includes('linkedin.com') ||
                            h.includes('instagram.com') ||
                            h.includes('youtube.com') ||
                            h.includes('whatsapp.com') ||
                            h.includes('wa.me') ||
                            h.includes('schema.org') ||
                            h.includes('w3.org')
                        );
                    };

                    return Array.from(cards).map(c => {
                        const links = Array.from(c.querySelectorAll('a')).map(a => ({href: a.href, text: a.innerText.trim()}));
                        
                        // Strict Company Name Selector from verified elements
                        const sellerEl = c.querySelector('.template7-seller-name, [class*="seller-name"], [class*="company-name"], .cncf1, h3, h4');
                        let explicitName = sellerEl ? sellerEl.innerText.trim() : null;

                        // Priority 1: External company website
                        let externalLink = links.find(l => 
                            l.href && l.href.startsWith('http') && 
                            !isNonCorporateHost(l.href) &&
                            l.text.length > 2
                        );
                        
                        // Priority 2: IndiaMART seller profile page
                        let profileLink = links.find(l => 
                            l.href && l.href.includes('indiamart.com/') && 
                            !l.href.includes('proddetail') && 
                            !l.href.includes('search') && 
                            !l.href.includes('impcat') &&
                            !l.href.includes('dir.indiamart') &&
                            !l.href.includes('indianexporters') &&
                            l.text.length > 2
                        );
                        
                        // Determine clean company name
                        let companyName = explicitName;
                        if (!companyName || nonCompanyWords.includes(companyName.toLowerCase())) {
                            if (profileLink && !nonCompanyWords.includes(profileLink.text.toLowerCase())) {
                                companyName = profileLink.text;
                            } else if (externalLink && !nonCompanyWords.includes(externalLink.text.toLowerCase())) {
                                companyName = externalLink.text;
                            }
                        }

                        let hasExternalWebsite = Boolean(externalLink);
                        let websiteDomain = null;
                        let indiamartProfileUrl = profileLink ? profileLink.href : null;

                        if (externalLink) {
                            try {
                                const u = new URL(externalLink.href);
                                websiteDomain = u.hostname.replace(/^www\\./, '');
                            } catch(e) {}
                        }

                        // Robust phone extraction across tel:, data-phone, and contact spans
                        let phone = c.querySelector('a[href^="tel:"]')?.href?.replace(/^tel:/i, '') || '';
                        if (!phone) {
                            const phoneEl = c.querySelector('[data-phone], [data-mobile], [data-phn], .du-phn, .ls_ph, .du-num, .pno, .mob');
                            if (phoneEl) {
                                phone = phoneEl.getAttribute('data-phone') || phoneEl.getAttribute('data-mobile') || phoneEl.getAttribute('data-phn') || phoneEl.innerText.trim();
                            }
                        }
                        if (!phone) {
                            const match = c.innerText.match(/(?:(?:\+|0{0,2})91[\s-]?)?([6-9]\d{9})\b/);
                            if (match) phone = match[0];
                        }

                        const location = c.querySelector('[class*="location"], [class*="city"], [class*="locality"], [class*="address"], [class*="cty"]')?.innerText?.trim() || '';
                        
                        return {
                            company: companyName,
                            has_website: hasExternalWebsite,
                            website_domain: websiteDomain,
                            indiamart_url: indiamartProfileUrl,
                            phone: phone,
                            location: location,
                        };
                    }).filter(x => x.company && x.company.length > 2 && !nonCompanyWords.includes(x.company.toLowerCase()));
                }''')

            finally:
                await browser.close()

            from leadforge.normalizer import normalize_phone

            seen_names = set()
            for c in raw_cards:
                name = c["company"].split("\n")[0].strip()
                if not name or name.lower() in seen_names:
                    continue
                if any(k in name.lower() for k in ["indiamart", "view more", "seller", "contact supplier", "leading supplier", "website"]):
                    continue

                seen_names.add(name.lower())

                loc = c.get("location") or city
                area = "Vatva" if "vatva" in loc.lower() else ("Odhav" if "odhav" in loc.lower() else ("Naroda" if "naroda" in loc.lower() else city))

                clean_phone = normalize_phone(c.get("phone") or "")

                results.append({
                    "name": name,
                    "city": city,
                    "area": area,
                    "category": category,
                    "phone": clean_phone,
                    "has_website": c.get("has_website", False),
                    "website_domain": c.get("website_domain"),
                    "indiamart_url": c.get("indiamart_url"),
                    "source_platform": "indiamart",
                    "contact_email": None,
                })
                if len(results) >= limit:
                    break

    except Exception as e:
        logger.error(f"[IndiaMART Scraper] Scraping error: {e}")

    logger.info(f"[IndiaMART Scraper] Harvested {len(results)} industrial manufacturers.")
    return results
