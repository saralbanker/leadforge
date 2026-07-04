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
    allow_origins=["*"],
    allow_credentials=True,
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

async def run_scraper_task(city: str, category: str, limit: int, no_website_only: bool = False):
    global task_status
    try:
        task_status["is_running"] = True
        task_status["error"] = None
        task_status["current_task"] = f"Searching for {category} in {city}..."
        result = await run_pipeline(city, category, limit, no_website_only=no_website_only)
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
    background_tasks.add_task(run_scraper_task, req.city, req.category, req.limit, req.no_website_only)
    return {"message": "Scrape task started.", "status": "running"}

@app.get("/api/status")
async def get_status():
    return task_status


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
            row["priority"] = "HIGH" if score >= 60 else ("MEDIUM" if score >= 28 else "LOW")
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
        opp["priority"] = "HIGH" if score >= 60 else ("MEDIUM" if score >= 28 else "LOW")
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
    mode: str = "all"           # all | high_priority | campaign | filtered
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
        raise HTTPException(status_code=400, detail=f"mode must be one of {valid_modes}")

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
            raise HTTPException(status_code=404, detail="No data matched the export filter.")

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
