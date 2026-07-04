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

async def run_pipeline(
    city: str,
    category: str,
    limit: int,
    output_file: str = None,
    no_website_only: bool = False,
) -> dict:
    """
    Main lead generation execution pipeline with SQLite database integration.
    When no_website_only=True the pipeline over-fetches by 3× and trims down
    to exactly `limit` businesses that have no website.
    """
    # 1. Initialize database & run migrations on startup
    from leadforge.database import initialize_database
    initialize_database()

    from datetime import datetime, timezone
    from leadforge.repositories.search import SQLiteSearchHistoryRepository
    from leadforge.repositories.lead import SQLiteLeadRepository
    import json

    search_repo = SQLiteSearchHistoryRepository()
    lead_repo = SQLiteLeadRepository()

    start_time = time.time()
    started_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%fZ')

    # Construct safe output filename
    if not output_file:
        safe_city = "".join([c if c.isalnum() else "_" for c in city])
        safe_category = "".join([c if c.isalnum() else "_" for c in category])
        output_file = f"{safe_city}_{safe_category}.xlsx"

    logger.info("=" * 60)
    logger.info("⚡ LEADFORGE - BUSINESS DISCOVERY & LEAD GENERATION")
    logger.info("=" * 60)
    logger.info(f"City:         {city}")
    logger.info(f"Category:     {category}")
    logger.info(f"Limit:        {limit}")
    logger.info(f"No-website:   {no_website_only}")
    logger.info("-" * 60)

    # Initialize a RUNNING search run log entry in the database
    search_id = search_repo.create(
        city=city,
        category=category,
        results_count=0,
        status="RUNNING",
        search_query=f"{category} in {city}",
        limit_requested=limit,
        started_at=started_at,
        scraper_version="2.0"
    )

    new_count = 0
    updated_count = 0
    duplicate_count = 0
    failed_count = 0

    try:
        # Step 1: Discover listing URLs
        # Over-fetch by 3× when filtering no-website so we can still hit limit after trim
        discovery_limit = limit * 3 if no_website_only else limit
        links = await discover_business_links(city, category, discovery_limit)

        # Step 2: Collect details from each listing page
        raw_leads = await collect_business_details(links, category)
        failed_count = len(links) - len(raw_leads)

        # Step 2b: Apply no-website filter then trim to requested limit
        if no_website_only:
            before = len(raw_leads)
            raw_leads = [l for l in raw_leads if not l.get("website", "").strip()]
            raw_leads = raw_leads[:limit]
            logger.info(f"No-website filter: {before} → {len(raw_leads)} leads (target {limit})")

        # Step 3: Score and prioritize leads
        processed_leads = process_and_score_leads(raw_leads)

        # Step 4: Save to SQLite database via Repository Pattern with Search run mapping
        for lead in processed_leads:
            lead_repo.save_lead_transaction(lead, output_file, search_id)

        # Retrieve cumulative stats directly from search history database
        from leadforge.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT new_businesses, updated_businesses, duplicate_detections FROM search_history WHERE id = ?", (search_id,))
        stats = cursor.fetchone()
        if stats:
            new_count = stats["new_businesses"]
            updated_count = stats["updated_businesses"]
            duplicate_count = stats["duplicate_detections"]
        conn.close()

        # Step 5: Export to Excel (Export utility only)
        export_path = export_leads_to_excel(processed_leads, output_file)

        duration = time.time() - start_time
        finished_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%fZ')

        # Step 6: Log successful search run metrics
        search_repo.complete(
            search_id=search_id,
            results_count=len(processed_leads),
            new_count=new_count,
            updated_count=updated_count,
            failed_count=failed_count,
            duplicate_count=duplicate_count,
            finished_at=finished_at,
            duration=duration,
            status="COMPLETED",
            metadata=json.dumps({
                "discovered_links": len(links),
                "successful_details": len(raw_leads),
                "campaign_filename": output_file
            })
        )

        # Logging stats
        logger.info("=" * 60)
        logger.info("📊 EXECUTION METRICS")
        logger.info("=" * 60)
        logger.info(f"Businesses Searched: {len(links)}")
        logger.info(f"Leads Found:         {len(raw_leads)}")
        logger.info(f"New Leads:           {new_count}")
        logger.info(f"Updated Leads:       {updated_count}")
        logger.info(f"Duplicate Leads:     {duplicate_count}")
        logger.info(f"Failed Leads:        {failed_count}")
        logger.info(f"Exported File:       {export_path.name}")
        logger.info(f"Execution Duration:  {duration:.2f} seconds")
        logger.info("=" * 60)

        return {
            "searched_count": len(links),
            "found_count": len(raw_leads),
            "new_count": new_count,
            "updated_count": updated_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
            "duration_sec": duration,
            "file_name": export_path.name
        }

    except Exception as e:
        duration = time.time() - start_time
        finished_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%fZ')
        try:
            search_repo.complete(
                search_id=search_id,
                results_count=0,
                new_count=0,
                updated_count=0,
                failed_count=limit,
                duplicate_count=0,
                finished_at=finished_at,
                duration=duration,
                status="FAILED",
                metadata=json.dumps({"error": str(e)})
            )
        except Exception:
            pass
        raise e

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
    parser.add_argument(
        "--no-website",
        action="store_true",
        default=False,
        help="Only keep businesses that have no website (over-fetches to hit the limit)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_pipeline(
            args.city, args.category, args.limit, args.output,
            no_website_only=args.no_website,
        ))
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Execution failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
