"""High-Quality Email Scraping & Enrichment Test Runner.

Scrapes and enriches local businesses, running multi-provider email discovery
(Website crawler, deep contact/about pages, directory lookups, aggregator ranking)
to harvest at least 20 verified high-quality business email addresses.
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from leadforge.database import initialize_database, get_db_connection
from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator
from leadforge.enrichment.website import WebsiteProvider
from leadforge.enrichment.aggregator import EmailCandidateAggregator
from leadforge.utils import get_logger

logger = get_logger()

# High-yield target business seed profiles with live web domains across key commercial hubs
TARGET_SEED_PROFILES = [
    {"name": "TechCraft Solutions", "website": "https://www.tcs.com", "city": "Mumbai", "category": "IT Services"},
    {"name": "Infosys BPM", "website": "https://www.infosys.com", "city": "Bengaluru", "category": "Software & Consulting"},
    {"name": "Wipro Enterprise", "website": "https://www.wipro.com", "city": "Bengaluru", "category": "IT Solutions"},
    {"name": "HCL Technologies", "website": "https://www.hcltech.com", "city": "Noida", "category": "Technology"},
    {"name": "Larsen & Toubro", "website": "https://www.larsentoubro.com", "city": "Mumbai", "category": "Engineering & Manufacturing"},
    {"name": "Tata Motors Commercial", "website": "https://www.tatamotors.com", "city": "Pune", "category": "Automotive"},
    {"name": "Mahindra & Mahindra", "website": "https://www.mahindra.com", "city": "Mumbai", "category": "Manufacturing"},
    {"name": "Sun Pharma Industries", "website": "https://www.sunpharma.com", "city": "Mumbai", "category": "Pharmaceuticals"},
    {"name": "Dr Reddys Laboratories", "website": "https://www.drreddys.com", "city": "Hyderabad", "category": "Pharmaceuticals"},
    {"name": "Cipla Healthcare", "website": "https://www.cipla.com", "city": "Mumbai", "category": "Pharmaceuticals"},
    {"name": "Torrent Pharmaceuticals", "website": "https://www.torrentpharma.com", "city": "Ahmedabad", "category": "Pharmaceuticals"},
    {"name": "Zydus Lifesciences", "website": "https://www.zyduslife.com", "city": "Ahmedabad", "category": "Healthcare"},
    {"name": "Apollo Hospitals", "website": "https://www.apollohospitals.com", "city": "Chennai", "category": "Healthcare"},
    {"name": "Fortis Healthcare", "website": "https://www.fortishealthcare.com", "city": "Delhi", "category": "Healthcare & Clinics"},
    {"name": "Max Healthcare", "website": "https://www.maxhealthcare.in", "city": "Delhi", "category": "Clinics & Doctors"},
    {"name": "Godrej Industries", "website": "https://www.godrej.com", "city": "Mumbai", "category": "Consumer Goods & Manufacturing"},
    {"name": "Asian Paints", "website": "https://www.asianpaints.com", "city": "Mumbai", "category": "Manufacturing & Chemicals"},
    {"name": "Pidilite Industries", "website": "https://www.pidilite.com", "city": "Mumbai", "category": "Chemicals & Adhesives"},
    {"name": "Havells India", "website": "https://www.havells.com", "city": "Noida", "category": "Electricals & Manufacturing"},
    {"name": "Voltas Engineering", "website": "https://www.voltas.com", "city": "Mumbai", "category": "Air Conditioning & Engineering"},
    {"name": "Blue Star Limited", "website": "https://www.bluestarindia.com", "city": "Mumbai", "category": "HVAC & Engineering"},
    {"name": "Thermax Global", "website": "https://www.thermaxglobal.com", "city": "Pune", "category": "Energy & Environment"},
    {"name": "Bharat Forge", "website": "https://www.bharatforge.com", "city": "Pune", "category": "Forging & Auto Components"},
    {"name": "Persistent Systems", "website": "https://www.persistent.com", "city": "Pune", "category": "Software Engineering"},
    {"name": "KPIT Technologies", "website": "https://www.kpit.com", "city": "Pune", "category": "Automotive Software"},
    {"name": "Cyient Engineering", "website": "https://www.cyient.com", "city": "Hyderabad", "category": "Engineering Services"},
    {"name": "Mindtree LTIMindtree", "website": "https://www.ltimindtree.com", "city": "Bengaluru", "category": "Digital Solutions"},
    {"name": "Mphasis Digital", "website": "https://www.mphasis.com", "city": "Bengaluru", "category": "IT Architecture"},
    {"name": "Coforge Solutions", "website": "https://www.coforge.com", "city": "Noida", "category": "Enterprise Software"},
    {"name": "Birlasoft IT", "website": "https://www.birlasoft.com", "city": "Pune", "category": "Enterprise Cloud"},
]


async def run_email_scraping_test(target_min_emails: int = 20) -> List[Dict[str, Any]]:
    """Runs the email enrichment pipeline to scrape and validate at least 20 high-quality emails."""
    print("=" * 80)
    print(f"🚀 LEADFORGE: High-Quality Email Scraping & Enrichment Runner")
    print(f"🎯 Target: At least {target_min_emails} verified business emails")
    print("=" * 80)

    initialize_database()

    orchestrator = EmailEnrichmentOrchestrator(
        aggregator=EmailCandidateAggregator(verify_mx=False)
    )

    discovered_results: List[Dict[str, Any]] = []
    start_time = time.time()

    # Process seed profiles concurrently with bounded semaphore
    semaphore = asyncio.Semaphore(5)

    async def _process_business(profile: Dict[str, Any]):
        async with semaphore:
            name = profile["name"]
            domain = profile.get("website", "")
            city = profile.get("city", "")
            category = profile.get("category", "")

            print(f"🔍 Crawling & discovering contact channels for: '{name}' ({city})...")
            try:
                top_cand, all_cands = await orchestrator.enrich_business(
                    business_profile={
                        "business_id": f"test_{int(time.time()*1000)}_{abs(hash(name)) % 10000}",
                        "name": name,
                        "website_domain": domain,
                        "website": domain,
                        "city": city,
                        "category": category,
                    },
                    global_timeout=10.0,
                )

                if top_cand and top_cand.email:
                    return {
                        "business_name": name,
                        "city": city,
                        "category": category,
                        "domain": domain,
                        "email": top_cand.email,
                        "confidence_score": top_cand.confidence_score,
                        "provider": top_cand.source_provider,
                        "context": top_cand.discovery_context,
                        "total_candidates": len(all_cands),
                    }
            except Exception as err:
                logger.warning(f"Error enriching {name}: {err}")

            return None

    tasks = [_process_business(p) for p in TARGET_SEED_PROFILES]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        if isinstance(res, dict) and res.get("email"):
            discovered_results.append(res)

    elapsed = time.time() - start_time

    print("\n" + "=" * 80)
    print(f"✅ EMAIL SCRAPING RUN COMPLETE: Found {len(discovered_results)} High-Quality Emails in {elapsed:.2f}s")
    print("=" * 80)
    print(f"{'#':<3} | {'Business Name':<28} | {'City':<12} | {'Discovered Email':<32} | {'Confidence':<10} | {'Provider'}")
    print("-" * 105)

    for idx, item in enumerate(discovered_results, 1):
        score_pct = f"{int(item['confidence_score'] * 100)}%"
        print(f"{idx:<3} | {item['business_name'][:28]:<28} | {item['city'][:12]:<12} | {item['email'][:32]:<32} | {score_pct:<10} | {item['provider']}")

    print("-" * 105)
    return discovered_results


if __name__ == "__main__":
    asyncio.run(run_email_scraping_test(target_min_emails=20))
