from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any
from leadforge.config import OUTPUT_DIR, LOGS_DIR
from leadforge.main import run_pipeline
from leadforge.utils import get_logger

logger = get_logger()
app = FastAPI(title="LeadForge API", version="1.0")

# Enable CORS for frontend clients (including Netlify hosted sites)
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

# Global in-memory task status
class ScrapeRequest(BaseModel):
    city: str
    category: str
    limit: int = 50

task_status = {
    "is_running": False,
    "current_task": None,
    "last_result": None,
    "error": None
}

async def run_scraper_task(city: str, category: str, limit: int):
    global task_status
    try:
        task_status["is_running"] = True
        task_status["error"] = None
        task_status["current_task"] = f"Searching for {category} in {city}..."

        result = await run_pipeline(city, category, limit)

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
    global task_status
    if task_status["is_running"]:
        raise HTTPException(status_code=400, detail="Scraper is already running.")

    background_tasks.add_task(run_scraper_task, req.city, req.category, req.limit)
    return {"message": "Scrape task started.", "status": "running"}

@app.get("/api/status")
async def get_status():
    return task_status

@app.get("/api/logs")
async def get_logs(lines: int = 50):
    log_file = LOGS_DIR / "run.log"
    if not log_file.exists():
        return {"logs": []}

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            # Return last N lines
            recent_logs = [line.strip() for line in all_lines[-lines:]]
            return {"logs": recent_logs}
    except Exception as e:
        return {"error": f"Could not read logs: {str(e)}", "logs": []}

@app.get("/api/history")
async def get_history() -> List[Dict[str, Any]]:
    """List all previously generated search runs from SQLite."""
    from leadforge.repositories.search import SQLiteSearchHistoryRepository
    repo = SQLiteSearchHistoryRepository()
    try:
        return repo.list_all()
    except Exception as e:
        logger.error(f"Error querying history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/leads/{filename}")
async def get_leads(filename: str):
    """Retrieve leads for a campaign/search run from SQLite database."""
    from leadforge.repositories.lead import SQLiteLeadRepository
    repo = SQLiteLeadRepository()
    try:
        leads = repo.get_leads_by_campaign(filename)
        if not leads:
            # Fallback bootstrap if database is empty but spreadsheet exists
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

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )
