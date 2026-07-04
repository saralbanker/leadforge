import pandas as pd
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
    """List all previously generated Excel exports."""
    files = []
    if not OUTPUT_DIR.exists():
        return []

    for filepath in OUTPUT_DIR.glob("*.xlsx"):
        stat = filepath.stat()
        files.append({
            "filename": filepath.name,
            "size_bytes": stat.st_size,
            "created_at": stat.st_mtime
        })

    # Sort by created time descending
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return files

@app.get("/api/leads/{filename}")
async def get_leads(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    try:
        df = pd.read_excel(file_path)
        # Convert NaN to empty string
        df = df.fillna("")

        # Mapping nice column names back to code-friendly keys
        key_mapping = {
            "Business Name": "name",
            "Business Category": "category",
            "Phone Number": "phone",
            "Website": "website",
            "Address": "address",
            "Area": "area",
            "Priority": "priority",
            "Notes": "notes",
            "Discovery Date": "discovery_date"
        }

        records = df.to_dict(orient="records")
        mapped_records = []
        for row in records:
            mapped_row = {}
            for col_name, val in row.items():
                key = key_mapping.get(col_name, col_name.lower())
                mapped_row[key] = val
            mapped_records.append(mapped_row)

        return mapped_records
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading Excel: {str(e)}")

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
