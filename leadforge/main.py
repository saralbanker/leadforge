import argparse
import asyncio
import sys
import time
from leadforge.config import DEFAULT_CITY, DEFAULT_CATEGORY, DEFAULT_LIMIT
from leadforge.search import discover_business_links
from leadforge.collector import collect_business_details
from leadforge.scorer import process_and_score_leads
from leadforge.exporter import export_leads_to_excel
from leadforge.utils import get_logger

logger = get_logger()

async def run_pipeline(city: str, category: str, limit: int, output_file: str = None) -> dict:
    """
    Main lead generation execution pipeline.
    """
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("⚡ LEADFORGE - BUSINESS DISCOVERY & LEAD GENERATION")
    logger.info("=" * 60)
    logger.info(f"City:      {city}")
    logger.info(f"Category:  {category}")
    logger.info(f"Limit:     {limit}")
    logger.info("-" * 60)

    # Step 1: Discover listing URLs
    links = await discover_business_links(city, category, limit)

    # Step 2: Collect details from each listing page
    raw_leads = await collect_business_details(links, category)

    # Step 3: Score and prioritize leads
    processed_leads = process_and_score_leads(raw_leads)

    # Step 4: Export to Excel
    if not output_file:
        safe_city = "".join([c if c.isalnum() else "_" for c in city])
        safe_category = "".join([c if c.isalnum() else "_" for c in category])
        output_file = f"{safe_city}_{safe_category}.xlsx"

    export_path = export_leads_to_excel(processed_leads, output_file)

    duration = time.time() - start_time

    # Logging stats (FR-7)
    logger.info("=" * 60)
    logger.info("📊 EXECUTION METRICS")
    logger.info("=" * 60)
    logger.info(f"Businesses Searched: {len(links)}")
    logger.info(f"Leads Found:         {len(raw_leads)}")
    logger.info(f"Unique Leads:        {len(processed_leads)}")
    logger.info(f"Exported File:       {export_path.name}")
    logger.info(f"Execution Duration:  {duration:.2f} seconds")
    logger.info("=" * 60)

    return {
        "searched_count": len(links),
        "found_count": len(raw_leads),
        "exported_count": len(processed_leads),
        "duration_sec": duration,
        "file_name": export_path.name
    }

def main():
    parser = argparse.ArgumentParser(
        description="LeadForge MVP - Local Business Discovery Scraper CLI"
    )
    parser.add_argument(
        "city",
        nargs="?",
        default=DEFAULT_CITY,
        help=f"Target city name (default: {DEFAULT_CITY})"
    )
    parser.add_argument(
        "category",
        nargs="?",
        default=DEFAULT_CATEGORY,
        help=f"Target business category (default: {DEFAULT_CATEGORY})"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum number of leads to fetch (default: {DEFAULT_LIMIT})"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output Excel filename"
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_pipeline(args.city, args.category, args.limit, args.output))
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Execution failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
