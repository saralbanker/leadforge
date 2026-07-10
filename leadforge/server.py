from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from leadforge.config import OUTPUT_DIR, LOGS_DIR
from leadforge.main import run_pipeline
from leadforge.utils import get_logger

logger = get_logger()
app = FastAPI(title="LeadForge API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    from leadforge.database import initialize_database

    initialize_database()


# ── Scraper ────────────────────────────────────────────────────────────────────


class ScrapeRequest(BaseModel):
    city: str
    category: str
    limit: int = 50
    no_website_only: bool = False


task_status = {
    "is_running": False,
    "current_task": None,
    "last_result": None,
    "error": None,
}


async def run_scraper_task(
    city: str, category: str, limit: int, no_website_only: bool = False
):
    global task_status
    try:
        task_status["is_running"] = True
        task_status["error"] = None
        task_status["current_task"] = f"Searching for {category} in {city}..."
        result = await run_pipeline(
            city, category, limit, no_website_only=no_website_only
        )
        task_status["last_result"] = result
        task_status["current_task"] = "Completed successfully."
    except Exception as e:
        logger.error(f"Background task error: {str(e)}")
        task_status["error"] = str(e)
        task_status["current_task"] = "Failed."
    finally:
        task_status["is_running"] = False


@app.post("/api/scrape")
async def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    if task_status["is_running"]:
        raise HTTPException(status_code=400, detail="Scraper is already running.")
    background_tasks.add_task(
        run_scraper_task, req.city, req.category, req.limit, req.no_website_only
    )
    return {"message": "Scrape task started.", "status": "running"}


@app.get("/api/status")
async def get_status():
    return task_status


@app.get("/api/metrics")
async def get_metrics():
    """Live campaign metrics during a running scrape; snapshot of last run when idle."""
    from leadforge.main import _active_orchestrator

    orch = _active_orchestrator
    is_running = task_status["is_running"]

    if not is_running or orch is None or not hasattr(orch, "state"):
        last = task_status.get("last_result") or {}
        return {
            "is_running": False,
            "progress": None,
            "last_campaign": {
                "qualified": last.get("qualified_count"),
                "requested": last.get("requested_count"),
                "visited": last.get("searched_count"),
                "rejected": last.get("rejected_count"),
                "duplicates": last.get("duplicate_count"),
                "duration_sec": last.get("duration_sec"),
                "termination_reason": last.get("termination_reason"),
                "tier1_rejections": last.get("tier1_rejections"),
                "extraction_rates": last.get("extraction_rates"),
                "avg_confidence": last.get("avg_confidence"),
            }
            if last
            else None,
        }

    metrics = orch.state.to_metrics()
    return {
        "is_running": True,
        "progress": {
            "qualified": metrics["qualified"],
            "requested": metrics["requested"],
            "visited": metrics["visited"],
            "rejected": metrics["rejected"],
            "duplicates": metrics["duplicates"],
        },
        "yield_rate": metrics["yield_rate"],
        "qualification_rate": metrics["yield_rate"],
        "avg_scrape_rate": round(1.0 / metrics["avg_seconds_per_business"], 2)
        if metrics["avg_seconds_per_business"] > 0
        else 0.0,
        "avg_seconds_per_qualified_lead": metrics["avg_seconds_per_qualified_lead"],
        "avg_seconds_per_business": metrics["avg_seconds_per_business"],
        "estimated_remaining_visits": metrics["estimated_remaining_visits"],
        "estimated_remaining_sec": metrics["estimated_remaining_sec"],
        "elapsed_sec": metrics["elapsed_sec"],
        "adaptive_budget": metrics["adaptive_budget"],
        "initial_budget": metrics["initial_budget"],
        "active_termination_condition": metrics["active_termination_condition"],
        "tier1_rejections": metrics["tier1_rejections"],
        "extraction_rates": metrics["extraction_rates"],
        "avg_confidence": metrics["avg_confidence"],
    }


# ── Logs ───────────────────────────────────────────────────────────────────────


@app.get("/api/logs")
async def get_logs(lines: int = 50):
    log_file = LOGS_DIR / "run.log"
    if not log_file.exists():
        return {"logs": []}
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            return {"logs": [line.strip() for line in all_lines[-lines:]]}
    except Exception as e:
        return {"error": f"Could not read logs: {str(e)}", "logs": []}


# ── Search History ─────────────────────────────────────────────────────────────


@app.get("/api/history")
async def get_history() -> List[Dict[str, Any]]:
    from leadforge.repositories.search import SQLiteSearchHistoryRepository

    repo = SQLiteSearchHistoryRepository()
    try:
        return repo.list_all()
    except Exception as e:
        logger.error(f"Error querying history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Leads ──────────────────────────────────────────────────────────────────────


@app.get("/api/leads/{filename}")
async def get_leads(filename: str):
    from leadforge.repositories.lead import SQLiteLeadRepository

    repo = SQLiteLeadRepository()
    try:
        leads = repo.get_leads_by_campaign(filename)
        if not leads:
            file_path = OUTPUT_DIR / filename
            if file_path.exists() and file_path.is_file():
                from leadforge.database import get_db_connection, bootstrap_legacy_data

                conn = get_db_connection()
                try:
                    bootstrap_legacy_data(conn)
                finally:
                    conn.close()
                leads = repo.get_leads_by_campaign(filename)

        if not leads:
            raise HTTPException(status_code=404, detail="Campaign / leads not found.")
        return leads
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading leads campaign: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error reading leads: {str(e)}")


# ── Opportunities ──────────────────────────────────────────────────────────────


@app.get("/api/opportunities")
async def list_opportunities(
    limit: int = 200,
    stage: Optional[str] = None,
) -> List[Dict[str, Any]]:
    from leadforge.opportunity_engine import OpportunityIntelligenceEngine

    engine = OpportunityIntelligenceEngine()
    try:
        rows = engine.list_opportunities(limit=limit, pipeline_stage=stage)
        for row in rows:
            score = row.get("score", 0) or 0
            row["priority"] = (
                "HIGH" if score >= 60 else ("MEDIUM" if score >= 28 else "LOW")
            )
        return rows
    except Exception as e:
        logger.error(f"Error listing opportunities: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str) -> Dict[str, Any]:
    from leadforge.repositories.opportunity import SQLiteOpportunityRepository

    repo = SQLiteOpportunityRepository()
    try:
        opp = repo.get_with_signals(opportunity_id)
        if not opp:
            raise HTTPException(status_code=404, detail="Opportunity not found.")
        score = opp.get("score", 0) or 0
        opp["priority"] = (
            "HIGH" if score >= 60 else ("MEDIUM" if score >= 28 else "LOW")
        )
        return opp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching opportunity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Businesses ─────────────────────────────────────────────────────────────────


@app.get("/api/businesses")
async def list_businesses(
    search: Optional[str] = None,
    maturity_grade: Optional[str] = None,
    min_score: Optional[float] = None,
    sort_by: str = "score",
    sort_dir: str = "desc",
    limit: int = 200,
) -> List[Dict[str, Any]]:
    from leadforge.repositories.business import SQLiteBusinessRepository

    repo = SQLiteBusinessRepository()
    try:
        return repo.list(
            search=search,
            maturity_grade=maturity_grade,
            min_score=min_score,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Error listing businesses: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/businesses/{business_id}")
async def get_business(business_id: str) -> Dict[str, Any]:
    from leadforge.repositories.business import SQLiteBusinessRepository

    repo = SQLiteBusinessRepository()
    try:
        detail = repo.get_detail(business_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Business not found.")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching business detail: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Export ─────────────────────────────────────────────────────────────────────


class ExportRequest(BaseModel):
    mode: str = "all"  # all | high_priority | campaign | filtered
    campaign_name: Optional[str] = None
    min_score: Optional[float] = None
    search: Optional[str] = None
    limit: int = 1000


@app.post("/api/export")
async def export_leads(req: ExportRequest):
    """Export leads to an enriched Excel file and return it for download."""
    from leadforge.repositories.business import SQLiteBusinessRepository
    from leadforge.exporter import export_intelligence_to_excel

    valid_modes = {"all", "high_priority", "campaign", "filtered"}
    if req.mode not in valid_modes:
        raise HTTPException(
            status_code=400, detail=f"mode must be one of {valid_modes}"
        )

    repo = SQLiteBusinessRepository()
    try:
        data = repo.list_for_export(
            mode=req.mode,
            campaign_name=req.campaign_name,
            min_score=req.min_score,
            search=req.search,
            limit=req.limit,
        )
        if not data:
            raise HTTPException(
                status_code=404, detail="No data matched the export filter."
            )

        mode_tag = req.campaign_name or req.mode
        safe_tag = "".join(c if c.isalnum() else "_" for c in mode_tag)
        filename = f"export_{safe_tag}.xlsx"
        path = export_intelligence_to_excel(data, filename)
        return FileResponse(
            path=path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Analytics ─────────────────────────────────────────────────────────────────


@app.get("/api/analytics")
async def get_analytics() -> Dict[str, Any]:
    """Aggregated campaign history and quality metrics from search_history."""
    import json as _json
    from leadforge.database import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT city, category, results_count, status,
                   started_at, finished_at, execution_duration,
                   new_businesses, updated_businesses, duplicate_detections,
                   scraper_metadata, limit_requested
            FROM search_history
            ORDER BY started_at DESC
            LIMIT 50
            """
        )
        rows = cursor.fetchall()

        campaigns = []
        total_qualified = 0
        total_requested = 0
        total_duration = 0
        duration_count = 0
        conf_sum = 0.0
        conf_count = 0
        city_counts: Dict[str, int] = {}
        cat_counts: Dict[str, int] = {}
        agg_rejection: Dict[str, int] = {}

        for row in rows:
            meta: Dict[str, Any] = {}
            if row["scraper_metadata"]:
                try:
                    meta = _json.loads(row["scraper_metadata"])
                except Exception:
                    pass

            qualified = int(meta.get("qualified_count") or row["results_count"] or 0)
            requested = int(row["limit_requested"] or 0)
            duration = float(row["execution_duration"] or 0)
            avg_conf = float(meta.get("avg_confidence") or 0)

            total_qualified += qualified
            total_requested += requested
            if duration > 0:
                total_duration += duration
                duration_count += 1
            if avg_conf > 0:
                conf_sum += avg_conf
                conf_count += 1

            rb = meta.get("rejection_breakdown") or {}
            for k, v in rb.items():
                if k not in ("tier1", "rejected_total"):
                    agg_rejection[k] = agg_rejection.get(k, 0) + int(v or 0)

            city = row["city"] or ""
            cat = row["category"] or ""
            if city:
                city_counts[city] = city_counts.get(city, 0) + 1
            if cat:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1

            campaigns.append(
                {
                    "city": row["city"],
                    "category": row["category"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "duration_sec": duration,
                    "qualified_count": qualified,
                    "requested_count": requested,
                    "new_businesses": int(row["new_businesses"] or 0),
                    "duplicates": int(row["duplicate_detections"] or 0),
                    "termination_reason": meta.get("termination_reason") or "",
                    "avg_confidence": round(avg_conf, 4),
                }
            )

        top_locations = sorted(city_counts.items(), key=lambda x: -x[1])[:5]
        top_categories = sorted(cat_counts.items(), key=lambda x: -x[1])[:5]

        return {
            "campaigns": campaigns,
            "summary": {
                "total_campaigns": len(campaigns),
                "total_qualified": total_qualified,
                "total_requested": total_requested,
                "qualification_yield": round(total_qualified / total_requested, 4)
                if total_requested > 0
                else 0,
                "avg_runtime_sec": round(total_duration / duration_count, 1)
                if duration_count > 0
                else 0,
                "avg_confidence": round(conf_sum / conf_count, 4)
                if conf_count > 0
                else 0,
                "top_locations": [{"name": n, "count": c} for n, c in top_locations],
                "top_categories": [{"name": n, "count": c} for n, c in top_categories],
                "rejection_breakdown": agg_rejection,
            },
        }
    except Exception as e:
        logger.error(f"Analytics error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── Settings ───────────────────────────────────────────────────────────────────


@app.get("/api/settings")
async def list_settings() -> Dict[str, Any]:
    """Return all configurable settings except internal category maps."""
    from leadforge.database import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value, description FROM settings ORDER BY key")
        result: Dict[str, Any] = {}
        for row in cursor.fetchall():
            key = row["key"]
            if key.startswith("opp.category_map."):
                continue
            result[key] = {
                "value": row["value"],
                "description": row["description"] or "",
            }
        return result
    except Exception as e:
        logger.error(f"Settings list error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class SettingUpdateRequest(BaseModel):
    value: str


@app.put("/api/settings/{key}")
async def update_setting(key: str, req: SettingUpdateRequest) -> Dict[str, Any]:
    """Update a single setting by key."""
    if key.startswith("opp.category_map."):
        raise HTTPException(
            status_code=400, detail="Category map settings are internal."
        )
    from leadforge.repositories.settings import SQLiteSettingsRepository

    repo = SQLiteSettingsRepository()
    try:
        repo.set(key, req.value)
        return {"key": key, "value": req.value}
    except Exception as e:
        logger.error(f"Settings update error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Factory Reset ─────────────────────────────────────────────────────────────


@app.post("/api/factory-reset")
async def factory_reset():
    """Delete the database and all exports, then reinitialize from scratch."""
    from leadforge.database import DB_PATH, initialize_database

    if task_status["is_running"]:
        raise HTTPException(
            status_code=409,
            detail="A campaign is currently running. Stop it before performing a factory reset.",
        )

    # Delete all Excel exports
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("*.xlsx"):
            try:
                f.unlink()
            except Exception as e:
                logger.warning(f"Could not delete export {f.name}: {e}")

    # Delete the database file (WAL/SHM siblings too)
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH.parent / (DB_PATH.name + suffix)
        if p.exists():
            try:
                p.unlink()
            except Exception as e:
                logger.warning(f"Could not delete {p}: {e}")

    # Reinitialize — runs all migrations and seeds lookup data
    try:
        initialize_database()
    except Exception as e:
        logger.error(f"Factory reset reinit failed: {e}")
        raise HTTPException(status_code=500, detail=f"Reinitalization failed: {e}")

    # Clear in-memory last-result so metrics tab shows zero
    task_status["last_result"] = None
    task_status["current_task"] = None
    task_status["error"] = None

    logger.info("Factory reset completed successfully.")
    return {"message": "Factory reset completed. Database reinitialized."}


# ── Legacy file download ────────────────────────────────────────────────────────


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
