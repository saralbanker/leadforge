from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import asyncio
import os
import json
import re
import subprocess
from pathlib import Path
from pydantic import BaseModel
import pathlib
from typing import List, Dict, Any, Optional
from leadforge.config import OUTPUT_DIR, LOGS_DIR
from leadforge.main import run_pipeline
from leadforge.utils import get_logger

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    from leadforge.database import initialize_database
    initialize_database()
    yield

app = FastAPI(title="LeadForge API", version="1.0", lifespan=lifespan)
logger = get_logger()

from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator
enrichment_orchestrator = EmailEnrichmentOrchestrator()

from leadforge.enrichment.phone_orchestrator import PhoneEnrichmentOrchestrator
phone_enrichment_orchestrator = PhoneEnrichmentOrchestrator()


cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS")
if cors_origins_env:
    allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# ── Frontend Static Assets & Root Route ────────────────────────────────────────

frontend_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.exists(frontend_dist):
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    @app.get("/favicon.svg")
    async def serve_favicon():
        fav = os.path.join(frontend_dist, "favicon.svg")
        if os.path.exists(fav):
            return FileResponse(fav)
        return {"status": "ok"}
else:
    @app.get("/")
    async def serve_root():
        return {
            "name": "LeadForge API",
            "version": "2.0",
            "status": "operational",
            "docs_url": "/docs",
        }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "LeadForge"}


class ScrapeRequest(BaseModel):
    city: str
    category: str
    sub_category: Optional[str] = None
    platforms: Optional[List[str]] = ["google_maps", "indiamart", "justdial", "tradeindia"]
    limit: int = 50
    no_website_only: bool = False
    website_filter: Optional[str] = "ALL"


task_status = {
    "is_running": False,
    "current_task": None,
    "last_result": None,
    "error": None,
}


async def run_scraper_task(
    city: str,
    category: str,
    limit: int,
    no_website_only: bool = False,
    website_filter: str = "ALL",
    platforms: Optional[List[str]] = None,
    sub_category: Optional[str] = None,
):
    global task_status
    try:
        task_status["is_running"] = True
        task_status["error"] = None
        target_display = f"{sub_category} ({category})" if sub_category else category
        task_status["current_task"] = f"Searching for {target_display} in {city}..."
        result = await run_pipeline(
            city,
            category,
            limit,
            no_website_only=no_website_only,
            website_filter=website_filter,
            platforms=platforms,
            sub_category=sub_category,
        )
        task_status["last_result"] = result
        task_status["current_task"] = "Completed successfully."
    except Exception as e:
        logger.error(f"Background task error: {str(e)}")
        task_status["error"] = str(e)
        task_status["current_task"] = "Failed."
    finally:
        task_status["is_running"] = False


@app.get("/api/taxonomy")
async def get_taxonomy():
    """Returns the full hierarchical industry and manufacturing taxonomy."""
    from leadforge.taxonomy import get_taxonomy_tree
    return get_taxonomy_tree()


@app.post("/api/scrape")
async def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    if task_status["is_running"]:
        raise HTTPException(status_code=400, detail="Scraper is already running.")
    task_status["is_running"] = True
    task_status["error"] = None
    target_display = f"{req.sub_category} ({req.category})" if req.sub_category else req.category
    task_status["current_task"] = f"Initializing search for {target_display} in {req.city}..."
    
    # Sync no_website_only with website_filter if website_filter is explicitly NO_WEBSITE
    effective_no_website = req.no_website_only or (req.website_filter == "NO_WEBSITE")
    effective_filter = req.website_filter or ("NO_WEBSITE" if effective_no_website else "ALL")
    
    try:
        background_tasks.add_task(
            run_scraper_task,
            req.city,
            req.category,
            req.limit,
            effective_no_website,
            effective_filter,
            req.platforms,
            req.sub_category,
        )
    except Exception as e:
        task_status["is_running"] = False
        task_status["current_task"] = None
        task_status["error"] = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to start background task: {str(e)}")
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

        return leads or []
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


@app.get("/api/settings/defaults")
async def settings_defaults() -> Dict[str, Any]:
    """Canonical default values, read from the code that actually uses them.

    The UI used to carry its own hardcoded copy of the system prompt for its
    "Reset to Default" button. That copy drifted, so pressing reset silently
    reverted the prompt past the evidence-binding and anti-fabrication rules that
    later migrations added. Defaults must have exactly one source of truth.
    """
    from leadforge.outreach.generator import (
        DEFAULT_SYSTEM_PROMPT,
        DEFAULT_USER_PROMPT_TEMPLATE,
    )

    return {
        "llm.system_prompt": DEFAULT_SYSTEM_PROMPT,
        "llm.user_prompt_template": DEFAULT_USER_PROMPT_TEMPLATE,
    }


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


# ── Local LM (Ollama) Control ──────────────────────────────────────────────────


class LLMTestRequest(BaseModel):
    api_url: Optional[str] = None
    model_name: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt: Optional[str] = None
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 150


@app.get("/api/llm/status")
async def get_llm_status():
    """Checks connection to local LM (Ollama) and returns installed models and settings."""
    from leadforge.outreach.generator import OllamaHookGenerator
    from leadforge.repositories.settings import SQLiteSettingsRepository

    repo = SQLiteSettingsRepository()
    api_url = repo.get_str("llm.api_url", "http://localhost:11434")
    model_name = repo.get_str("llm.model_name", "llama3.1:8b")
    enabled = repo.get_str("llm.enabled", "true").lower() in ("true", "1", "yes")

    conn_status = await asyncio.to_thread(OllamaHookGenerator.test_connection, api_url)
    return {
        "enabled": enabled,
        "api_url": api_url,
        "model_name": model_name,
        "temperature": repo.get_float("llm.temperature", 0.2),
        "max_tokens": repo.get_int("llm.max_tokens", 150),
        "system_prompt": repo.get_str("llm.system_prompt", ""),
        "user_prompt_template": repo.get_str("llm.user_prompt_template", ""),
        "connection": conn_status,
    }


@app.post("/api/llm/test")
async def test_llm_inference(req: LLMTestRequest):
    """Executes a test inference run against the local LM."""
    from leadforge.outreach.generator import OllamaHookGenerator
    from leadforge.repositories.settings import SQLiteSettingsRepository

    repo = SQLiteSettingsRepository()
    api_url = req.api_url or repo.get_str("llm.api_url", "http://localhost:11434")
    model_name = req.model_name or repo.get_str("llm.model_name", "llama3.1:8b")
    system_prompt = req.system_prompt or repo.get_str("llm.system_prompt", "")
    temperature = req.temperature if req.temperature is not None else repo.get_float("llm.temperature", 0.2)
    max_tokens = req.max_tokens or repo.get_int("llm.max_tokens", 150)

    result = await asyncio.to_thread(
        OllamaHookGenerator.test_inference,
        api_url=api_url,
        model_name=model_name,
        system_prompt=system_prompt,
        prompt=req.prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return result



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


# ── Outreach API ───────────────────────────────────────────────────────────────


@app.get("/api/outreach/campaigns")
async def list_campaigns():
    """Returns the list of parsed campaigns from campaign_routing.yaml."""
    from leadforge.outreach.router import CampaignRouter

    router = CampaignRouter()
    return router.campaigns


@app.get("/api/outreach/drafts")
async def list_drafts(status: Optional[str] = None):
    """Lists email drafts joined with business names and opportunity scores."""
    from leadforge.database import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT ed.id, ed.opportunity_id, ed.campaign_name, ed.recipient_email, 
                   ed.subject, ed.body, ed.status, ed.error_message, ed.sent_at, 
                   ed.created_at, ed.updated_at,
                   b.name as business_name, b.website_domain, b.display_phone, b.rating, b.review_count,
                   o.score as opportunity_score
            FROM email_drafts ed
            JOIN opportunities o ON ed.opportunity_id = o.id
            JOIN businesses b ON o.business_id = b.id
        """
        params = []
        if status:
            query += " WHERE ed.status = ?"
            params.append(status)
        query += " ORDER BY ed.created_at DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error listing drafts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/outreach/metrics")
async def get_outreach_metrics():
    """Returns real-time delivery metrics: sent today, failed today, approved waiting, pending approval."""
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection
    from leadforge.repositories.settings import SettingsCache

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cursor.execute(
            "SELECT COUNT(*) FROM email_drafts WHERE status = 'SENT' AND substr(sent_at, 1, 10) = ?",
            (today_str,),
        )
        sent_today = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM email_drafts WHERE status = 'FAILED' AND substr(updated_at, 1, 10) = ?",
            (today_str,),
        )
        failed_today = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM email_drafts WHERE status = 'APPROVED'")
        approved_waiting = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM email_drafts WHERE status = 'PENDING_APPROVAL'")
        pending_approval = cursor.fetchone()[0]

        settings_cache = SettingsCache()
        daily_limit = settings_cache.get_int("outreach.daily_send_limit", 20)

        from leadforge.repositories.whatsapp_reporting import get_whatsapp_summary
        wa_summary = get_whatsapp_summary()

        return {
            "sent_today": sent_today,
            "failed_today": failed_today,
            "approved_waiting": approved_waiting,
            "pending_approval": pending_approval,
            "daily_send_limit": daily_limit,
            "whatsapp": wa_summary,
        }
    except Exception as e:
        logger.error(f"Error fetching outreach metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/whatsapp/metrics")
async def get_whatsapp_metrics():
    """Returns real-time WhatsApp outreach metrics (read-only from whatsapp_outreach.db)."""
    from leadforge.repositories.whatsapp_reporting import get_whatsapp_summary

    summary = get_whatsapp_summary()
    if summary is None:
        return {
            "status": "unavailable",
            "message": "WhatsApp outreach database not configured",
        }
    return {"status": "active", **summary}


class GenerateDraftRequest(BaseModel):
    opportunity_id: str
    force_regenerate: bool = False
    custom_subject: Optional[str] = None
    custom_body: Optional[str] = None


@app.post("/api/outreach/drafts/generate")
async def generate_draft(req: GenerateDraftRequest):
    """Crawls website, routes to campaign, generates LLM hook, and saves a draft."""
    import uuid
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection, append_event
    from leadforge.outreach.discovery import WebsiteAuditor, is_duplicate_outreach
    from leadforge.outreach.router import CampaignRouter
    from leadforge.outreach.generator import OllamaHookGenerator
    from leadforge.outreach.quality import EmailQualityEngine

    opportunity_id = req.opportunity_id

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Fetch opportunity details
        cursor.execute(
            """
            SELECT o.id as opportunity_id, o.business_id, b.name as business_name,
                   b.website_domain, b.contact_email, b.display_phone, b.rating, b.review_count,
                   bt.name as category, a.city, a.area
            FROM opportunities o
            JOIN businesses b ON o.business_id = b.id
            LEFT JOIN business_types bt ON b.business_type_id = bt.id
            LEFT JOIN addresses a ON b.id = a.business_id
            WHERE o.id = ?
            """,
            (opportunity_id,),
        )
        opp = cursor.fetchone()
        if not opp:
            raise HTTPException(status_code=404, detail="Opportunity not found.")

        business_id = opp["business_id"]
        business_name = opp["business_name"]
        website_domain = opp["website_domain"]
        contact_email = opp["contact_email"]
        display_phone = opp["display_phone"]
        rating = opp["rating"] or 0.0
        review_count = opp["review_count"] or 0
        category = opp["category"] or ""
        city = opp["city"] or "your city"

        # Check for existing draft
        cursor.execute("SELECT id, status FROM email_drafts WHERE opportunity_id = ?", (opportunity_id,))
        existing = cursor.fetchone()
        existing_draft_id = None
        if existing:
            if existing["status"] == "SENT":
                raise HTTPException(
                    status_code=400,
                    detail="Cannot regenerate an email draft that has already been SENT.",
                )
            if not req.force_regenerate:
                raise HTTPException(
                    status_code=400,
                    detail=f"Draft already exists (Status: {existing['status']}). Set force_regenerate=true to overwrite.",
                )
            existing_draft_id = existing["id"]

        # 1. Audit Website & Discover Emails
        audit = {
            "has_website": False,
            "ssl_valid": False,
            "load_time_seconds": 0.0,
            "viewport_mobile": True,
            "cms": "Custom",
            "has_booking": False,
            "discovered_emails": [],
            "cleaned_text": "",
        }
        recipient_email = contact_email

        if website_domain:
            from datetime import datetime, timezone, timedelta
            import uuid
            now = datetime.now(timezone.utc)
            now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            cache_hit = False

            cursor.execute(
                """
                SELECT dp.id as presence_id, wa.issues_json, wa.created_at, b.contact_email
                FROM digital_presences dp
                JOIN businesses b ON dp.business_id = b.id
                LEFT JOIN website_audits wa ON dp.id = wa.digital_presence_id
                WHERE dp.business_id = ?
                ORDER BY wa.created_at DESC LIMIT 1
                """,
                (business_id,),
            )
            cache_row = cursor.fetchone()

            if cache_row and cache_row["issues_json"]:
                try:
                    audited_time = datetime.fromisoformat(cache_row["created_at"].replace("Z", "+00:00"))
                    if now - audited_time < timedelta(days=7):
                        logger.info(f"Cache hit: Using cached website audit for domain {website_domain}")
                        audit = json.loads(cache_row["issues_json"])
                        if audit.get("discovered_emails"):
                            recipient_email = audit["discovered_emails"][0]
                        else:
                            recipient_email = cache_row["contact_email"] or contact_email
                        cache_hit = True
                except Exception as cache_err:
                    logger.warning(f"Failed to load cached website audit: {cache_err}. Recrawling.")

            if not cache_hit:
                audit = await asyncio.to_thread(WebsiteAuditor.audit_website, website_domain)
                if audit["discovered_emails"]:
                    recipient_email = audit["discovered_emails"][0]

                try:
                    cursor.execute("SELECT id FROM digital_presences WHERE business_id = ?", (business_id,))
                    dp_row = cursor.fetchone()
                    if dp_row:
                        presence_id = dp_row[0]
                        cursor.execute(
                            """
                            UPDATE digital_presences 
                            SET ssl_valid = ?, platform = ?, updated_at = ? 
                            WHERE id = ?
                            """,
                            (1 if audit["ssl_valid"] else 0, audit["cms"], now_str, presence_id),
                        )
                    else:
                        presence_id = str(uuid.uuid4())
                        cursor.execute(
                            """
                            INSERT INTO digital_presences (id, business_id, website_url, has_website, platform, ssl_valid, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (presence_id, business_id, website_domain, 1, audit["cms"], 1 if audit["ssl_valid"] else 0, now_str, now_str),
                        )

                    audit_id = str(uuid.uuid4())
                    cursor.execute(
                        """
                        INSERT INTO website_audits (id, digital_presence_id, page_speed_ms, issues_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            audit_id,
                            presence_id,
                            int(audit.get("load_time_seconds", 0.0) * 1000),
                            json.dumps(audit),
                            now_str,
                            now_str,
                        ),
                    )

                    if recipient_email and recipient_email != contact_email:
                        cursor.execute(
                            "UPDATE businesses SET contact_email = ?, updated_at = ? WHERE id = ?",
                            (recipient_email, now_str, business_id),
                        )
                    append_event(
                        event_type="WEBSITE_AUDITED",
                        entity_type="Business",
                        entity_id=business_id,
                        payload={
                            "has_website": audit.get("has_website"),
                            "ssl_valid": audit.get("ssl_valid"),
                            "load_time_seconds": audit.get("load_time_seconds"),
                            "cms": audit.get("cms"),
                        },
                        conn=conn,
                    )
                    conn.commit()
                except Exception as db_err:
                    logger.error(f"Failed to cache website audit results in SQLite: {db_err}")

        # If website crawl didn't yield an email, fallback to multi-provider enrichment (Justdial, IndiaMart, TradeIndia)
        if not recipient_email:
            try:
                biz_profile = {
                    "business_id": business_id,
                    "name": business_name,
                    "city": city,
                    "website_domain": website_domain,
                    "website": website_domain,
                }
                top_cand, _ = await enrichment_orchestrator.enrich_business(biz_profile)
                if top_cand and top_cand.email:
                    recipient_email = top_cand.email
                    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    cursor.execute(
                        "UPDATE businesses SET contact_email = ?, updated_at = ? WHERE id = ?",
                        (recipient_email, now_str, business_id),
                    )
                    conn.commit()
            except Exception as enrich_err:
                logger.warning(f"Multi-provider enrichment error for business {business_id}: {enrich_err}")

        # If the business has no phone on file, fallback to multi-provider phone enrichment
        # (IndiaMart, Justdial, TradeIndia, and the business's own website)
        if not display_phone:
            try:
                from leadforge.normalizer import canonical_phone

                p_phone, p_source, c_phone, cand_list = await phone_enrichment_orchestrator.enrich_phone(
                    business_profile={
                        "name": business_name,
                        "city": city,
                        "category": category,
                        "website": website_domain,
                        "website_domain": website_domain,
                    },
                )
                if p_phone:
                    display_phone = p_phone
                    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    cursor.execute(
                        "UPDATE businesses SET display_phone = ?, normalized_phone = ?, phone_source = ?, phone_candidates = ?, updated_at = ? WHERE id = ?",
                        (p_phone, canonical_phone(p_phone), p_source, json.dumps(cand_list), now_str, business_id),
                    )
                    conn.commit()
                    append_event(
                        event_type="PHONE_DISCOVERED",
                        entity_type="Business",
                        entity_id=business_id,
                        payload={"discovered_phone": p_phone, "source": p_source},
                        conn=conn,
                    )
                    conn.commit()
            except Exception as enrich_err:
                logger.warning(f"Phone enrichment error for business {business_id}: {enrich_err}")

        # Log discovery attempt
        attempt_id = str(uuid.uuid4())
        discovery_status = "SUCCESS" if recipient_email else "NO_EMAIL_FOUND"
        cursor.execute(
            """
            INSERT INTO email_discovery_attempts (id, business_id, domain, discovered_email, discovery_status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (attempt_id, business_id, website_domain or "NO_WEBSITE", recipient_email, discovery_status),
        )
        if recipient_email:
            append_event(
                event_type="EMAIL_DISCOVERED",
                entity_type="Business",
                entity_id=business_id,
                payload={"discovered_email": recipient_email, "domain": website_domain},
                conn=conn,
            )
        conn.commit()

        if not recipient_email:
            raise HTTPException(
                status_code=422,
                detail="No contact email found. Crawl and business profile contain no email addresses.",
            )

        # 2. Campaign Routing
        router = CampaignRouter()
        campaign = router.route_lead(
            category=category,
            has_website=audit["has_website"],
            ssl_valid=audit["ssl_valid"],
            load_time_seconds=audit["load_time_seconds"],
            has_booking=audit.get("has_booking"),
            has_order_flow=audit.get("has_order_flow"),
            has_contact_form=audit.get("has_contact_form"),
            audit_data=audit,
        )

        if not campaign:
            raise HTTPException(
                status_code=422,
                detail="No campaign matches this lead's technical profile or business category.",
            )

        # 3. Deduplication & Suppression Check
        cursor.execute("SELECT is_suppressed FROM businesses WHERE id = ?", (business_id,))
        b_row = cursor.fetchone()
        if b_row and b_row["is_suppressed"] == 1:
            raise HTTPException(
                status_code=422,
                detail="Opt-Out Guard: This business profile is unsubscribed and suppressed from outreach.",
            )

        if not req.force_regenerate and is_duplicate_outreach(business_id, email=recipient_email, domain=website_domain, exclude_draft_id=existing_draft_id):
            raise HTTPException(
                status_code=409,
                detail="Deduplication Alert: This company or email has already been contacted or queued.",
            )

        # 4. Ollama Hook Generation
        # Maps listings keyword-stuff their titles (one is 125 chars). Using that
        # verbatim reads as bulk mail in a subject line, and derails the model.
        from leadforge.normalizer import clean_business_name
        display_name = clean_business_name(business_name) or business_name or ""
        premise_verified = campaign.get("premise_verified", True)

        generator = OllamaHookGenerator()
        hook, hook_source = await asyncio.to_thread(
            generator.generate_hook_with_source,
            business_name=display_name,
            review_count=review_count,
            rating=rating,
            city=city,
            scraped_text=audit["cleaned_text"],
            category=category,
            area=opp["area"] if "area" in opp.keys() and opp["area"] else "",
            has_website=bool(website_domain),
            premise_verified=premise_verified,
        )

        # 5. Compile copy templates
        import collections
        from leadforge.repositories.settings import SettingsCache
        from leadforge.outreach.generator import compile_compliance_footer
        settings_cache = SettingsCache()

        # Custom template override from request or campaign default
        custom_sub = (req.custom_subject or "").strip()
        custom_bod = (req.custom_body or "").strip()

        subject_tpl = custom_sub or CampaignRouter.select_subject(campaign.get("copy_template", {}), business_id=business_id)
        body_tpl = custom_bod or CampaignRouter.select_body(
            campaign.get("copy_template", {}),
            business_id=business_id,
            premise_verified=premise_verified,
        )
        campaign_name = "Custom Template Outreach" if (custom_sub or custom_bod) else campaign["name"]

        area_val = opp["area"] if "area" in opp.keys() and opp["area"] else ""
        template_vars = collections.defaultdict(str, {
            "business_name": display_name,
            "business_name_full": business_name or "",
            "city": city or "",
            "category": category or "",
            "area": area_val or "",
            "observation_hook": hook or "",
            "rating": str(rating) if rating else "",
            "review_count": str(review_count) if review_count else "",
            "website_domain": website_domain or "",
            "scraped_text": audit["cleaned_text"] or "",
        })

        subject = subject_tpl.format_map(template_vars)
        body = body_tpl.format_map(template_vars)

        # Append compliance footer if present and not already in body
        footer = compile_compliance_footer(settings_cache)
        if footer and footer not in body:
            body = body + footer

        # 6. Quality Scoring (evaluated on email body)
        #    Recent drafts are passed in so the engine can catch a batch of
        #    near-identical openings — the failure that only shows up at scale.
        cursor.execute(
            """
            SELECT body FROM email_drafts
            WHERE status IN ('PENDING_APPROVAL', 'APPROVED', 'QUEUED', 'SENT')
              AND (? IS NULL OR id != ?)
            ORDER BY updated_at DESC LIMIT 25
            """,
            (existing_draft_id, existing_draft_id),
        )
        recent_bodies = [r["body"] for r in cursor.fetchall()]
        quality = EmailQualityEngine.score_draft(body, previous_bodies=recent_bodies)

        # 7. Store draft
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if existing_draft_id:
            draft_id = existing_draft_id
            cursor.execute(
                """
                UPDATE email_drafts
                SET campaign_name = ?, recipient_email = ?, subject = ?, body = ?, status = 'PENDING_APPROVAL',
                    error_message = NULL, quality_score = ?, quality_passed = ?, quality_issues = ?,
                    hook_source = ?, updated_at = ?
                WHERE id = ?
                """,
                (campaign_name, recipient_email, subject, body,
                 quality["quality_score"], 1 if quality["passed"] else 0,
                 json.dumps(quality["issues"]), hook_source, now_str, draft_id),
            )
            append_event(
                event_type="EMAIL_DRAFT_REGENERATED",
                entity_type="EmailDraft",
                entity_id=draft_id,
                payload={
                    "opportunity_id": opportunity_id,
                    "campaign_name": campaign_name,
                    "recipient_email": recipient_email,
                    "subject": subject,
                },
                conn=conn,
            )
        else:
            draft_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status,
                                          quality_score, quality_passed, quality_issues, hook_source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', ?, ?, ?, ?, ?, ?)
                """,
                (draft_id, opportunity_id, campaign_name, recipient_email, subject, body,
                 quality["quality_score"], 1 if quality["passed"] else 0,
                 json.dumps(quality["issues"]), hook_source, now_str, now_str),
            )
            append_event(
                event_type="EMAIL_DRAFT_GENERATED",
                entity_type="EmailDraft",
                entity_id=draft_id,
                payload={
                    "opportunity_id": opportunity_id,
                    "campaign_name": campaign_name,
                    "recipient_email": recipient_email,
                    "subject": subject,
                },
                conn=conn,
            )
        conn.commit()


        return {
            "id": draft_id,
            "opportunity_id": opportunity_id,
            "campaign_name": campaign["name"],
            "recipient_email": recipient_email,
            "recipient_phone": display_phone,
            "subject": subject,
            "body": body,
            "status": "PENDING_APPROVAL",
            "quality_score": quality["quality_score"],
            "quality_passed": quality["passed"],
            "quality_issues": quality["issues"],
            "hook_source": hook_source,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating draft: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/outreach/drafts/{draft_id}/approve")
async def approve_draft(draft_id: str):
    """Sets a draft status to APPROVED after state machine validation."""
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection, append_event
    from leadforge.execution_state import EntityStateMachine, InvalidTransitionError

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found.")

        current_status = row["status"]
        EntityStateMachine.validate_transition(
            entity_type="EmailDraft",
            current_state=current_status,
            next_state="APPROVED",
            triggering_event="EMAIL_APPROVED",
        )

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            "UPDATE email_drafts SET status = 'APPROVED', updated_at = ? WHERE id = ?", (now_str, draft_id)
        )
        append_event(
            event_type="EMAIL_APPROVED",
            entity_type="EmailDraft",
            entity_id=draft_id,
            payload={"status": "APPROVED", "previous_status": current_status},
            conn=conn,
        )
        conn.commit()
        return {"message": "Draft approved successfully."}

    except InvalidTransitionError as ite:
        raise HTTPException(status_code=400, detail=str(ite))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving draft: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/outreach/drafts/{draft_id}/reject")
async def reject_draft(draft_id: str):
    """Sets a draft status to REJECTED after state machine validation."""
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection, append_event
    from leadforge.execution_state import EntityStateMachine, InvalidTransitionError

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found.")

        current_status = row["status"]
        EntityStateMachine.validate_transition(
            entity_type="EmailDraft",
            current_state=current_status,
            next_state="REJECTED",
            triggering_event="EMAIL_REJECTED",
        )

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            "UPDATE email_drafts SET status = 'REJECTED', updated_at = ? WHERE id = ?", (now_str, draft_id)
        )
        append_event(
            event_type="EMAIL_REJECTED",
            entity_type="EmailDraft",
            entity_id=draft_id,
            payload={"status": "REJECTED", "previous_status": current_status},
            conn=conn,
        )
        conn.commit()
        return {"message": "Draft rejected."}

    except InvalidTransitionError as ite:
        raise HTTPException(status_code=400, detail=str(ite))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting draft: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class UpdateDraftRequest(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    recipient_email: Optional[str] = None


@app.put("/api/outreach/drafts/{draft_id}")
async def update_draft(draft_id: str, req: UpdateDraftRequest):
    """Updates subject, body, or recipient email of an existing draft."""
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection, append_event

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status, subject, body, recipient_email FROM email_drafts WHERE id = ?", (draft_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found.")

        if row["status"] == "SENT":
            raise HTTPException(status_code=400, detail="Cannot edit a draft that has already been SENT.")

        new_subject = req.subject if req.subject is not None else row["subject"]
        new_body = req.body if req.body is not None else row["body"]
        new_email = req.recipient_email if req.recipient_email is not None else row["recipient_email"]

        from leadforge.outreach.quality import EmailQualityEngine
        quality = EmailQualityEngine.score_draft(new_body)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            """
            UPDATE email_drafts
            SET subject = ?, body = ?, recipient_email = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_subject, new_body, new_email, now_str, draft_id),
        )
        append_event(
            event_type="EMAIL_DRAFT_UPDATED",
            entity_type="EmailDraft",
            entity_id=draft_id,
            payload={
                "subject": new_subject,
                "recipient_email": new_email,
                "quality_score": quality["quality_score"],
            },
            conn=conn,
        )
        conn.commit()
        return {
            "message": "Draft updated successfully.",
            "id": draft_id,
            "subject": new_subject,
            "body": new_body,
            "recipient_email": new_email,
            "quality_score": quality["quality_score"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating draft: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class BulkApproveRequest(BaseModel):
    draft_ids: Optional[List[str]] = None


@app.post("/api/outreach/drafts/bulk-approve")
async def bulk_approve_drafts(req: Optional[BulkApproveRequest] = None):
    """Bulk approves pending email drafts."""
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection, append_event

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Bulk approval is the automation path, so it enforces the quality
        # verdict that single approval leaves to human judgement.
        from leadforge.repositories.settings import SettingsCache
        settings_cache = SettingsCache()
        min_score = settings_cache.get_int("outreach.min_quality_score", 80)
        require_llm = settings_cache.get_str("outreach.require_llm_hook", "true").lower() in ("true", "1", "yes")

        cols = "id, body, quality_score, quality_passed, quality_issues, hook_source"
        if req and req.draft_ids:
            placeholders = ",".join(["?"] * len(req.draft_ids))
            cursor.execute(
                f"SELECT {cols} FROM email_drafts WHERE status = 'PENDING_APPROVAL' AND id IN ({placeholders})",
                req.draft_ids,
            )
        else:
            cursor.execute(f"SELECT {cols} FROM email_drafts WHERE status = 'PENDING_APPROVAL'")

        rows = cursor.fetchall()
        approved_count = 0
        skipped = []
        approved_bodies: List[str] = []

        from leadforge.outreach.quality import EmailQualityEngine

        for row in rows:
            draft_id = row["id"]
            body = row["body"] or ""
            score = row["quality_score"]
            reason = None

            if score is None:
                reason = "no quality score recorded — regenerate this draft before approving"
            elif score < min_score:
                issues = row["quality_issues"]
                reason = f"quality score {score} is below the minimum of {min_score}"
                if issues:
                    try:
                        parsed = json.loads(issues)
                        if parsed:
                            reason += f" ({'; '.join(parsed)})"
                    except (ValueError, TypeError):
                        pass
            elif require_llm and str(row["hook_source"] or "").startswith("fallback"):
                # Provenance is now a prefixed string, e.g. "fallback:degraded:too_long"
                # when the validator exhausted its retries and shipped the best bad
                # candidate. Matching the bare word "fallback" let every degraded
                # hook through the gate at quality 100.
                detail = str(row["hook_source"] or "")
                reason = (
                    f"the opening line did not pass hook validation ({detail}) — "
                    "it is not clean model output, so this draft is held back"
                )
            elif approved_bodies:
                sim_match = EmailQualityEngine.find_similar(body, approved_bodies)
                if sim_match:
                    ratio, offending = sim_match
                    clean_offending = offending.replace("\n", " ").strip()[:60]
                    reason = (
                        f"body is {int(ratio * 100)}% identical to another draft in this batch "
                        f'("{clean_offending}...") — held back to prevent repetitive bulk outreach'
                    )

            if reason:
                skipped.append({"draft_id": draft_id, "reason": reason})
                append_event(
                    event_type="EMAIL_APPROVAL_BLOCKED",
                    entity_type="EmailDraft",
                    entity_id=draft_id,
                    payload={"reason": reason, "quality_score": score, "hook_source": row["hook_source"]},
                    conn=conn,
                )
                continue

            cursor.execute(
                "UPDATE email_drafts SET status = 'APPROVED', updated_at = ? WHERE id = ?",
                (now_str, draft_id),
            )
            append_event(
                event_type="EMAIL_APPROVED",
                entity_type="EmailDraft",
                entity_id=draft_id,
                payload={"status": "APPROVED", "bulk": True, "quality_score": score},
                conn=conn,
            )
            approved_count += 1
            if body:
                approved_bodies.append(body)

        conn.commit()
        msg = f"Approved {approved_count} draft(s)."
        if skipped:
            msg += f" Held back {len(skipped)} that did not meet the quality bar."
        return {
            "message": msg,
            "approved_count": approved_count,
            "skipped_count": len(skipped),
            "skipped": skipped,
        }
    except Exception as e:
        logger.error(f"Error bulk approving drafts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/outreach/drafts/{draft_id}/retry")
async def retry_draft(draft_id: str):
    """Sets a FAILED draft back to APPROVED so it can be retried in the next delivery dispatch run."""
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection, append_event
    from leadforge.execution_state import EntityStateMachine, InvalidTransitionError

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found.")

        current_status = row["status"]
        if current_status != "FAILED":
            raise HTTPException(
                status_code=400,
                detail=f"Only drafts with status FAILED can be retried. Current status is {current_status}.",
            )

        EntityStateMachine.validate_transition(
            entity_type="EmailDraft",
            current_state=current_status,
            next_state="APPROVED",
            triggering_event="EMAIL_RETRIED",
        )

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            "UPDATE email_drafts SET status = 'APPROVED', error_message = NULL, updated_at = ? WHERE id = ?",
            (now_str, draft_id),
        )
        append_event(
            event_type="EMAIL_APPROVED",
            entity_type="EmailDraft",
            entity_id=draft_id,
            payload={"status": "APPROVED", "retried_from": "FAILED"},
            conn=conn,
        )
        conn.commit()
        return {"message": "Draft queued for retry successfully."}
    except InvalidTransitionError as ite:
        raise HTTPException(status_code=400, detail=str(ite))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying draft: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()



def run_delivery_task():
    """Background helper to execute the SMTP delivery queue."""
    from leadforge.outreach.deliverer import SMTPEmailDeliverer

    try:
        deliverer = SMTPEmailDeliverer()
        sent = deliverer.send_approved_drafts()
        logger.info(f"Background SMTP delivery finished. Sent: {sent} emails.")
    except Exception as e:
        logger.error(f"Background SMTP delivery error: {str(e)}")


@app.post("/api/outreach/deliver")
async def trigger_delivery(background_tasks: BackgroundTasks):
    """Triggers background sending of all APPROVED email drafts."""
    background_tasks.add_task(run_delivery_task)
    return {"message": "SMTP delivery task started in background."}


@app.get("/api/outreach/unsubscribe/{business_id}")
@app.post("/api/outreach/unsubscribe/{business_id}")
async def unsubscribe_lead(business_id: str):
    """Processes opt-out request: flags business profile as suppressed and records UNSUBSCRIBED event."""
    from datetime import datetime, timezone
    from leadforge.database import get_db_connection, append_event

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, contact_email FROM businesses WHERE id = ?", (business_id,))
        biz = cursor.fetchone()
        if not biz:
            raise HTTPException(status_code=404, detail="Business profile not found.")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            "UPDATE businesses SET is_suppressed = 1, updated_at = ? WHERE id = ?",
            (now_str, business_id),
        )
        append_event(
            event_type="UNSUBSCRIBED",
            entity_type="Business",
            entity_id=business_id,
            payload={
                "business_name": biz["name"],
                "contact_email": biz["contact_email"],
                "unsubscribed_at": now_str,
            },
            conn=conn,
        )
        conn.commit()
        return {
            "message": "You have been successfully unsubscribed from future outreach.",
            "business_id": business_id,
            "status": "SUPPRESSED",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing unsubscribe for business {business_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/enrichment/stats")
async def get_enrichment_stats():
    """Returns telemetry metrics for business email enrichment."""
    from leadforge.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM email_discovery_attempts WHERE discovery_status = 'SUCCESS'")
        success_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM email_discovery_attempts")
        total_attempts = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM businesses WHERE contact_email IS NOT NULL AND contact_email != ''")
        businesses_with_email = cursor.fetchone()[0]
        return {
            "total_attempts": total_attempts,
            "successful_discoveries": success_count,
            "businesses_with_email": businesses_with_email,
        }
    finally:
        conn.close()


class ThreadCreateRequest(BaseModel):
    business_id: str
    campaign_name: str = "General Outreach"


class InboundCommunicationRequest(BaseModel):
    thread_id: str
    sender_email: str
    subject: str = "Re: Outreach"
    body_text: str


@app.post("/api/communication/threads")
async def create_communication_thread(req: ThreadCreateRequest):
    """Creates a new communication thread for a business."""
    from leadforge.communication.repository import SQLiteCommunicationRepository
    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=req.business_id, campaign_name=req.campaign_name)
    return {
        "id": thread.id,
        "business_id": thread.business_id,
        "campaign_name": thread.campaign_name,
        "current_state": thread.current_state,
        "created_at": thread.created_at,
    }


@app.post("/api/communication/inbound")
async def process_inbound_communication(req: InboundCommunicationRequest):
    """Ingests and classifies an inbound communication reply."""
    from leadforge.communication.repository import SQLiteCommunicationRepository
    from leadforge.communication.classifier import LLMReplyClassifier
    from leadforge.communication.optout import OptOutManager

    repo = SQLiteCommunicationRepository()
    classifier = LLMReplyClassifier()
    optout = OptOutManager(repository=repo)

    label = classifier.classify_reply(req.body_text)

    msg = repo.add_message(
        thread_id=req.thread_id,
        direction="INBOUND",
        sender_email=req.sender_email,
        recipient_email="outreach@leadforge.ai",
        subject=req.subject,
        body_text=req.body_text,
        classification_label=label,
    )

    if label == "UNSUBSCRIBE":
        optout.process_opt_out(req.sender_email, thread_id=req.thread_id)

    return {
        "id": msg.id,
        "thread_id": msg.thread_id,
        "classification_label": label,
        "created_at": msg.created_at,
    }


@app.get("/api/communication/stats")
async def get_communication_stats():
    """Returns telemetry metrics for communication threads and messages."""
    from leadforge.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM communication_threads")
        total_threads = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM communication_messages WHERE direction = 'OUTBOUND'")
        outbound_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM communication_messages WHERE direction = 'INBOUND'")
        inbound_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM unsubscribe_suppressions")
        optout_count = cursor.fetchone()[0]
        return {
            "total_threads": total_threads,
            "outbound_messages": outbound_count,
            "inbound_messages": inbound_count,
            "unsubscribes": optout_count,
        }
    finally:
        conn.close()


@app.post("/api/outreach/poll-replies")
@app.post("/api/outreach/replies/poll")
async def poll_replies():
    """Polls IMAP inbox for new replies and bounces, ingests, classifies, and executes side effects."""
    from leadforge.communication.inbox import IMAPInboxMonitor
    monitor = IMAPInboxMonitor()
    result = await asyncio.to_thread(monitor.poll_inbox)
    return result


# ── Outreach Schedule & Systemd Timer ─────────────────────────────────────────

SCHEDULE_TIME_REGEX = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def get_systemd_timer_path() -> Path:
    override = os.environ.get("LEADFORGE_SYSTEMD_TIMER_PATH")
    if override:
        return Path(override)
    return Path.home() / ".config" / "systemd" / "user" / "leadforge-daily.timer"


def write_systemd_timer_unit(time_hhmm: str) -> None:
    if not SCHEDULE_TIME_REGEX.match(time_hhmm):
        raise ValueError(f"Invalid schedule time format: {time_hhmm}")
    unit_content = (
        f"[Unit]\n"
        f"Description=LeadForge daily outreach at {time_hhmm}\n\n"
        f"[Timer]\n"
        f"OnCalendar=*-*-* {time_hhmm}:00\n"
        f"# Catch up if the machine was asleep or off at {time_hhmm}.\n"
        f"Persistent=true\n"
        f"# Avoid every install firing on the same second.\n"
        f"RandomizedDelaySec=180\n\n"
        f"[Install]\n"
        f"WantedBy=timers.target\n"
    )
    timer_path = get_systemd_timer_path()
    timer_path.parent.mkdir(parents=True, exist_ok=True)
    timer_path.write_text(unit_content, encoding="utf-8")


def read_systemd_timer_status() -> Dict[str, Any]:
    """Reads actual systemd timer status for leadforge-daily.timer."""
    try:
        res = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                "leadforge-daily.timer",
                "--property=ActiveState,SubState,UnitFileState,NextElapseUSecRealtime,TimersCalendar",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0:
            return {
                "systemd_available": False,
                "timer_active": False,
                "timer_state": "unavailable",
                "next_run": None,
            }
        props: Dict[str, str] = {}
        for line in res.stdout.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        active_state = props.get("ActiveState", "unknown")
        timer_active = (active_state == "active")
        next_run = props.get("NextElapseUSecRealtime")
        if not next_run or next_run in ("n/a", "0", ""):
            next_run = None
        return {
            "systemd_available": True,
            "timer_active": timer_active,
            "timer_state": active_state,
            "next_run": next_run,
        }
    except Exception as e:
        logger.warning(f"Unable to read systemd timer status: {e}")
        return {
            "systemd_available": False,
            "timer_active": False,
            "timer_state": "unavailable",
            "next_run": None,
        }


def apply_systemd_schedule(time_hhmm: str, enabled: bool) -> Dict[str, Any]:
    """Writes unit file and reloads/starts/stops the timer via systemctl --user."""
    try:
        write_systemd_timer_unit(time_hhmm)
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        if enabled:
            subprocess.run(
                ["systemctl", "--user", "enable", "leadforge-daily.timer"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            subprocess.run(
                ["systemctl", "--user", "restart", "leadforge-daily.timer"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        else:
            subprocess.run(
                ["systemctl", "--user", "stop", "leadforge-daily.timer"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            subprocess.run(
                ["systemctl", "--user", "disable", "leadforge-daily.timer"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        status = read_systemd_timer_status()
        status["timer_applied"] = True
        return status
    except Exception as e:
        logger.warning(f"Failed to apply schedule to systemd: {e}")
        return {
            "systemd_available": False,
            "timer_active": False,
            "timer_state": "unavailable",
            "next_run": None,
            "timer_applied": False,
            "error": str(e),
        }


class OutreachScheduleRequest(BaseModel):
    time: str
    enabled: bool = True


def read_wake_alarm() -> Dict[str, Any]:
    """State of the system-level RTC wake alarm, if one is installed.

    A user timer cannot arm the hardware clock, so on a laptop that suspends
    overnight the scheduled run does not happen at its scheduled time - it happens
    whenever someone opens the lid. `leadforge-wake.timer` is an optional system
    unit that wakes the machine shortly beforehand. Report honestly whether it
    exists and whether the configured run time actually falls after it.
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["systemctl", "show", "leadforge-wake.timer",
             "--property=LoadState", "--property=ActiveState", "--property=NextElapseUSecRealtime"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return {"installed": False, "active": False, "wake_time": None, "next_wake": None}

    props = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    installed = props.get("LoadState") == "loaded"
    wake_time = None
    if installed:
        try:
            unit = pathlib.Path("/etc/systemd/system/leadforge-wake.timer").read_text()
            for line in unit.splitlines():
                if line.strip().startswith("OnCalendar="):
                    wake_time = line.split("*-*-*", 1)[-1].strip()[:5]
        except Exception:
            wake_time = None
    return {
        "installed": installed,
        "active": props.get("ActiveState") == "active",
        "wake_time": wake_time,
        "next_wake": props.get("NextElapseUSecRealtime") or None,
    }


def schedule_warning(schedule_time: str, wake: Dict[str, Any]) -> Optional[str]:
    """Plain-language warning when the run time cannot actually be honoured."""
    if not wake.get("installed") or not wake.get("active"):
        return (
            "No RTC wake alarm is installed, so if this machine is asleep at the "
            "scheduled time the run happens when you next wake it, not on time."
        )
    wake_time = wake.get("wake_time")
    if wake_time and schedule_time <= wake_time:
        return (
            f"The wake alarm fires at {wake_time}, which is not before the {schedule_time} "
            "run. Move the run later, or move the alarm earlier, or a sleeping "
            "machine will miss it."
        )
    return None


@app.get("/api/outreach/schedule")
async def get_outreach_schedule():
    """Returns current outreach schedule settings and live systemd timer state."""
    from leadforge.repositories.settings import SQLiteSettingsRepository
    repo = SQLiteSettingsRepository()
    schedule_time = repo.get("outreach.schedule_time") or "08:00"
    enabled_val = repo.get("outreach.schedule_enabled")
    schedule_enabled = (enabled_val.lower() != "false") if enabled_val is not None else True

    systemd_info = read_systemd_timer_status()
    wake = read_wake_alarm()
    return {
        "time": schedule_time,
        "enabled": schedule_enabled,
        "timer_active": systemd_info["timer_active"],
        "timer_state": systemd_info["timer_state"],
        "next_run": systemd_info["next_run"],
        "systemd_available": systemd_info["systemd_available"],
        "timer_applied": systemd_info["systemd_available"],
        "wake_alarm": wake,
        "warning": schedule_warning(schedule_time, wake),
    }


@app.post("/api/outreach/schedule")
async def update_outreach_schedule(req: OutreachScheduleRequest):
    """Validates, persists, and applies the daily outreach schedule to systemd."""
    # SECURITY: strict validation of time format BEFORE any file or subprocess interaction
    if not isinstance(req.time, str) or not SCHEDULE_TIME_REGEX.match(req.time):
        raise HTTPException(
            status_code=422,
            detail="Invalid time format. Expected 24h HH:MM format (00:00 to 23:59).",
        )

    from leadforge.repositories.settings import SQLiteSettingsRepository
    repo = SQLiteSettingsRepository()
    repo.set("outreach.schedule_time", req.time)
    repo.set("outreach.schedule_enabled", "true" if req.enabled else "false")

    apply_result = apply_systemd_schedule(req.time, req.enabled)

    response = {
        "time": req.time,
        "enabled": req.enabled,
        "timer_active": apply_result["timer_active"],
        "timer_state": apply_result["timer_state"],
        "next_run": apply_result["next_run"],
        "systemd_available": apply_result["systemd_available"],
        "timer_applied": apply_result["timer_applied"],
    }
    if not apply_result["timer_applied"]:
        response["message"] = f"Schedule saved to settings, but systemd timer could not be applied: {apply_result.get('error', 'systemd unavailable')}"
    else:
        response["message"] = "Schedule saved and applied to systemd timer successfully."

    return response







