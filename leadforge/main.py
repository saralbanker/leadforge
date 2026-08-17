import argparse
import asyncio
import sys
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from leadforge.control_plane import SearchOrchestrator

from leadforge.config import DEFAULT_CITY, DEFAULT_CATEGORY, DEFAULT_LIMIT
from leadforge.exporter import export_leads_to_excel
from leadforge.utils import get_logger

logger = get_logger()

# Holds the live orchestrator during a campaign run; None when idle.
# The /api/metrics endpoint reads this for in-flight metrics.
_active_orchestrator: Optional["SearchOrchestrator"] = None


async def run_pipeline(
    city: str,
    category: str,
    limit: int,
    output_file: str = None,
    no_website_only: bool = False,
    website_filter: str = "ALL",
) -> dict:
    """Main lead generation pipeline with SQLite persistence."""
    # 1. Initialize database & run migrations on startup
    from leadforge.database import initialize_database

    initialize_database()

    from datetime import datetime, timezone
    from leadforge.repositories.search import SQLiteSearchHistoryRepository
    import json

    search_repo = SQLiteSearchHistoryRepository()

    start_time = time.time()
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Construct safe output filename — unique per execution via campaign start timestamp.
    if not output_file:
        safe_city = "".join([c if c.isalnum() else "_" for c in city])
        safe_category = "".join([c if c.isalnum() else "_" for c in category])
        ts = started_at[:19].replace("-", "").replace("T", "_").replace(":", "")
        output_file = f"{safe_city}_{safe_category}_{ts}.xlsx"

    logger.info("=" * 60)
    logger.info("⚡ LEADFORGE - BUSINESS DISCOVERY & LEAD GENERATION")
    logger.info("=" * 60)
    logger.info(f"City:           {city}")
    logger.info(f"Category:       {category}")
    logger.info(f"Limit:          {limit}")
    logger.info(f"Website-filter: {website_filter}")
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
        scraper_version="2.0",
        campaign_filename=output_file,
    )

    new_count = 0
    updated_count = 0
    duplicate_count = 0
    failed_count = 0
    termination_reason = ""
    rejection_breakdown = {}
    tier1_rejections = {}
    extraction_rates = {}
    avg_confidence = 0.0

    try:
        from leadforge.control_plane import SearchOrchestrator

        global _active_orchestrator
        orchestrator = SearchOrchestrator()
        _active_orchestrator = orchestrator

        # Run the qualified control plane loop
        processed_leads = await orchestrator.run_qualified_campaign(
            city=city,
            category=category,
            limit=limit,
            no_website_only=no_website_only,
            website_filter=website_filter,
            search_id=search_id,
            campaign_name=output_file,
        )
        links = orchestrator.discovered_links
        found_count = getattr(orchestrator, "found_count", len(links))
        # Pull termination + rejection stats from the execution state
        state = getattr(orchestrator, "state", None)
        if state:
            termination_reason = state.termination_reason
            rejection_breakdown = state.rejection_breakdown()
            failed_count = state.rejected_count
            tier1_rejections = dict(state.tier1_rejections)
            extraction_rates = state.extraction_rates()
            avg_confidence = round(state.avg_confidence(), 4)

        # Retrieve cumulative stats directly from search history database
        from leadforge.database import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT new_businesses, updated_businesses, duplicate_detections FROM search_history WHERE id = ?",
            (search_id,),
        )
        stats = cursor.fetchone()
        if stats:
            new_count = stats["new_businesses"] or 0
            updated_count = stats["updated_businesses"] or 0
            duplicate_count = stats["duplicate_detections"] or 0
        conn.close()

        # Step 5: Export to Excel (Export utility only)
        _active_orchestrator = None
        export_path = export_leads_to_excel(processed_leads, output_file)

        duration = time.time() - start_time
        finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        qualified_count = len(processed_leads)
        # Count only leads created in this specific search run (scoped by search_id),
        # not all historical leads ever filed under the same campaign filename.
        conn2 = get_db_connection()
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT COUNT(*) FROM leads WHERE search_history_id = ?", (search_id,)
            )
            sqlite_count = cur2.fetchone()[0]
        finally:
            conn2.close()

        # Step 6: Log successful search run metrics
        search_repo.complete(
            search_id=search_id,
            results_count=qualified_count,
            new_count=new_count,
            updated_count=updated_count,
            failed_count=failed_count,
            duplicate_count=duplicate_count,
            finished_at=finished_at,
            duration=duration,
            status="COMPLETED",
            metadata=json.dumps(
                {
                    "campaign_filename": output_file,
                    "termination_reason": termination_reason,
                    "qualified_count": qualified_count,
                    "sqlite_count": sqlite_count,
                    "rejection_breakdown": rejection_breakdown,
                    "tier1_rejections": tier1_rejections,
                    "extraction_rates": extraction_rates,
                    "avg_confidence": avg_confidence,
                }
            ),
        )

        # Logging stats — full reconciliation report
        logger.info("=" * 60)
        logger.info("📊 EXECUTION METRICS")
        logger.info("=" * 60)
        logger.info(f"Requested Count:     {limit}")
        logger.info(f"Qualified Count:     {qualified_count}")
        logger.info(f"Export Count:        {qualified_count}")
        logger.info(f"SQLite Count:        {sqlite_count}")
        logger.info(f"Termination Reason:  {termination_reason}")
        logger.info("-" * 60)
        # Total businesses actually navigated in browser: Tier-2 survivors + Tier-1 rejections
        _tier1_total = sum(tier1_rejections.values())
        urls_navigated = qualified_count + failed_count + _tier1_total

        logger.info(f"Raw Listings Found:  {found_count}")
        logger.info(f"Businesses Navigated: {urls_navigated}")
        logger.info(
            f"Duplicates:          {rejection_breakdown.get('duplicates', duplicate_count)}"
        )
        logger.info(
            f"Rejected Total:      {rejection_breakdown.get('rejected_total', failed_count)}"
        )
        logger.info(f"  No Phone:          {rejection_breakdown.get('no_phone', 0)}")
        logger.info(f"  Has Website:       {rejection_breakdown.get('has_website', 0)}")
        logger.info(f"  Wrong City:        {rejection_breakdown.get('wrong_city', 0)}")
        logger.info(
            f"  Wrong Category:    {rejection_breakdown.get('wrong_category', 0)}"
        )
        logger.info(
            f"  Perm. Closed:      {rejection_breakdown.get('permanently_closed', 0)}"
        )
        if tier1_rejections:
            logger.info(
                "Tier-1 Rejections:   "
                f"No Name: {tier1_rejections.get('NO_NAME', 0)} | "
                f"No Phone: {tier1_rejections.get('NO_PHONE', 0)} | "
                f"Has Website: {tier1_rejections.get('HAS_WEBSITE', 0)} | "
                f"Closed: {tier1_rejections.get('CLOSED', 0)}"
            )
        logger.info(f"New Leads:           {new_count}")
        logger.info(f"Updated Leads:       {updated_count}")
        logger.info(f"Exported File:       {export_path.name}")
        logger.info(f"Execution Duration:  {duration:.2f} seconds")
        if qualified_count != sqlite_count:
            logger.warning(
                f"COUNT MISMATCH: export={qualified_count} vs sqlite={sqlite_count}. "
                "Investigate get_leads_by_campaign for duplicate lead rows."
            )
        logger.info("=" * 60)

        return {
            "requested_count": limit,
            "qualified_count": qualified_count,
            "export_count": qualified_count,
            "sqlite_count": sqlite_count,
            "termination_reason": termination_reason,
            "found_count": found_count,
            "searched_count": urls_navigated,
            "new_count": new_count,
            "updated_count": updated_count,
            "duplicate_count": rejection_breakdown.get("duplicates", duplicate_count),
            "rejected_count": rejection_breakdown.get("rejected_total", failed_count),
            "no_phone_count": rejection_breakdown.get("no_phone", 0),
            "has_website_count": rejection_breakdown.get("has_website", 0),
            "wrong_city_count": rejection_breakdown.get("wrong_city", 0),
            "wrong_category_count": rejection_breakdown.get("wrong_category", 0),
            "permanently_closed_count": rejection_breakdown.get(
                "permanently_closed", 0
            ),
            "category_unverified_count": rejection_breakdown.get(
                "category_unverified", 0
            ),
            "ghost_listing_count": rejection_breakdown.get("ghost_listing", 0),
            "tier1_rejections": tier1_rejections,
            "extraction_rates": extraction_rates,
            "avg_confidence": avg_confidence,
            "duration_sec": duration,
            "file_name": export_path.name,
        }

    except KeyboardInterrupt:
        _active_orchestrator = None
        duration = time.time() - start_time
        finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        try:
            search_repo.complete(
                search_id=search_id,
                results_count=0,
                new_count=0,
                updated_count=0,
                failed_count=0,
                duplicate_count=0,
                finished_at=finished_at,
                duration=duration,
                status="FAILED",
                metadata=json.dumps({"reason": "KeyboardInterrupt"}),
            )
        except Exception:
            pass
        raise

    except Exception as e:
        _active_orchestrator = None
        duration = time.time() - start_time
        finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
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
                metadata=json.dumps({"error": str(e)}),
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
        help=f"Target city name (default: {DEFAULT_CITY})",
    )
    parser.add_argument(
        "category",
        nargs="?",
        default=DEFAULT_CATEGORY,
        help=f"Target business category (default: {DEFAULT_CATEGORY})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum number of leads to fetch (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--output", type=str, default=None, help="Custom output Excel filename"
    )
    parser.add_argument(
        "--no-website",
        action="store_true",
        default=False,
        help="Only keep businesses that have no website (over-fetches to hit the limit)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            run_pipeline(
                args.city,
                args.category,
                args.limit,
                args.output,
                no_website_only=args.no_website,
            )
        )
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user.")
        # run_pipeline raises KeyboardInterrupt before returning search_id, so we
        # cannot update search_history here.  The RUNNING record will remain; a
        # startup reconciliation pass (or manual cleanup) can address it.
        sys.exit(130)
    except Exception as e:
        logger.error(f"Execution failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
