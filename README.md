# LeadForge MVP

LeadForge is an automated local business discovery and lead prioritization tool for cold calling, designed to help sales teams identify high-priority prospects (businesses without websites) in Ahmedabad, Gujarat.

---

## Features
- **Local Discovery:** Search businesses by city and category.
- **Digital Presence Scoring:** Assigns "High Priority" (+60 points) to businesses with no website.
- **Excel Export:** Exports deduplicated, prioritized lead lists to a clean `.xlsx` spreadsheet.
- **Local API Server:** FastAPI backend exposing the CLI core endpoints.
- **Web Dashboard:** Clean React/Vite UI wrapper (deployable to Netlify) that connects to the local API.

---

## Project Structure
```plaintext
├── leadforge/           # Backend Scraper CLI & API
│   ├── main.py          # CLI entry point
│   ├── server.py        # FastAPI server
│   ├── config.py        # Configuration & scoring rules
│   ├── search.py        # Discovery logic (Google Maps/Directories)
│   ├── collector.py     # Data extraction (phone, address, website)
│   ├── parser.py        # Parser & clean up
│   ├── scorer.py        # Leads scoring (High/Medium/Low priority)
│   ├── exporter.py      # Pandas Excel writer
│   └── utils.py         # Logging & common helpers
├── frontend/            # React/Vite Dashboard
├── requirements.txt     # Python requirements
└── leadforge-plan.md    # Action plan
```

---

## Installation & Setup

### 1. Backend & CLI
Make sure you have Python 3.12+ installed.

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for scraping)
playwright install chromium
```

#### Run CLI (Terminal)
```bash
python leadforge/main.py "Ahmedabad" "Manufacturers" --limit 50
```

#### Start local FastAPI Server
```bash
uvicorn leadforge.server:app --reload --port 8000
```

### 2. Frontend UI (Vite + React)
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.
