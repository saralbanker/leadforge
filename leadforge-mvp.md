# LeadForge MVP Plan

Automated lead generation and prioritization tool for local business discovery in Ahmedabad, Gujarat. Provides a Python CLI tool and a React/Vite web UI wrapper.

---

## Project Type
**WEB + BACKEND CLI**
- CLI & API Scraper: Python (requests, beautifulsoup4, playwright, fastapi)
- UI Dashboard: React + Vite + Tailwind CSS (static build ready for Netlify deployment)

---

## Success Criteria
- Discover 100–300 leads for a category in Ahmedabad in < 5 minutes.
- Priority scoring assigns "High" to leads with no website and "Medium" to those with websites.
- Export results cleanly to `.xlsx` files without duplicate listings.
- Web UI runs locally or hosted on Netlify, connecting to the local scraper API.

---

## Tech Stack
- **Language:** Python 3.12+ (Scraper, CLI, API)
- **Scraping Libraries:** Playwright, BeautifulSoup4, Requests
- **Data Handling:** Pandas, Openpyxl
- **Web UI:** React (Vite, Tailwind CSS, Axios)
- **API Server:** FastAPI, Uvicorn

---

## File Structure
```plaintext
leadforge/
├── leadforge/
│   ├── __init__.py
│   ├── main.py          # CLI Entrypoint
│   ├── config.py        # Settings & scoring rules
│   ├── search.py        # Business discovery via Google Maps/directories
│   ├── collector.py     # Details extraction (phone, address, etc.)
│   ├── parser.py        # Scraping response parser
│   ├── scorer.py        # Leads prioritization scoring
│   ├── exporter.py      # Pandas Excel exporter
│   ├── server.py        # FastAPI endpoint server
│   └── utils.py         # Logging & helpers
├── frontend/            # React/Vite UI Dashboard
│   ├── src/
│   │   ├── components/  # Reusable UI widgets
│   │   ├── App.jsx      # Dashboard logic & control panel
│   │   ├── index.css
│   │   └── main.jsx
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── tests/
│   ├── test_scraper.py
│   └── test_scorer.py
├── requirements.txt
└── leadforge-mvp.md     # This plan file
```

---

## Task Breakdown

### Phase 1: Foundation (P0)

#### Task 1: Setup Workspace & Dependencies
- **Task ID:** `F-1`
- **Name:** Environment setup
- **Agent:** `devops-engineer`
- **Skills:** `clean-code`, `bash-linux`
- **Priority:** High
- **Dependencies:** None
- **INPUT:** Empty repository
- **OUTPUT:** Root files `requirements.txt`, `README.md`, folder structures.
- **VERIFY:** Run `pip install -r requirements.txt` and check if all libraries install without error.

#### Task 2: Configuration & Utility Modules
- **Task ID:** `F-2`
- **Name:** config.py and utils.py
- **Agent:** `backend-specialist`
- **Skills:** `clean-code`
- **Priority:** High
- **Dependencies:** `F-1`
- **INPUT:** Project requirements
- **OUTPUT:** `config.py` with scoring metrics, directories, and standard logging setups in `utils.py`.
- **VERIFY:** Execute `python3 -c "import leadforge.config; import leadforge.utils"` and ensure no import or syntax errors.

---

### Phase 2: Core Scraping & Scoring CLI (P1)

#### Task 3: Lead Discovery & Collection
- **Task ID:** `C-1`
- **Name:** search.py, collector.py, parser.py
- **Agent:** `backend-specialist`
- **Skills:** `clean-code`
- **Priority:** High
- **Dependencies:** `F-2`
- **INPUT:** City, category, limit.
- **OUTPUT:** Python code to query business data from directory/maps using Playwright.
- **VERIFY:** Run target search locally and print list of scraped dictionaries with fields (name, phone, website, address).

#### Task 4: Prioritization Scorer & Deduplicator
- **Task ID:** `C-2`
- **Name:** scorer.py and duplicate removal
- **Agent:** `backend-specialist`
- **Skills:** `clean-code`
- **Priority:** High
- **Dependencies:** `C-1`
- **INPUT:** Raw leads dictionary list.
- **OUTPUT:** Scored leads sorted by priority (High: no website, Medium: website exists), duplicates filtered.
- **VERIFY:** Execute dry test with list containing duplicate items and leads with/without websites, verify output scoring/uniqueness.

#### Task 5: Excel Exporter & Terminal CLI
- **Task ID:** `C-3`
- **Name:** exporter.py, main.py CLI Integration
- **Agent:** `backend-specialist`
- **Skills:** `clean-code`
- **Priority:** High
- **Dependencies:** `C-2`
- **INPUT:** Scored leads collection.
- **OUTPUT:** CLI commands to run scraping and generate `output/Ahmedabad_<Category>.xlsx`.
- **VERIFY:** Run `python leadforge/main.py Ahmedabad "Manufacturers" --limit 10` and inspect generated `.xlsx` file structure.

---

### Phase 3: Web Server & Frontend UI/UX (P2)

#### Task 6: FastAPI Local Server
- **Task ID:** `U-1`
- **Name:** server.py API setup
- **Agent:** `backend-specialist`
- **Skills:** `api-patterns`
- **Priority:** Medium
- **Dependencies:** `C-3`
- **INPUT:** CLI scraper capabilities.
- **OUTPUT:** FastAPI endpoints (`/start-scrape`, `/leads`, `/logs`) running on port `8000`.
- **VERIFY:** Trigger endpoint `curl http://localhost:8000/docs` to see API documentation.

#### Task 7: React/Vite Dashboard UI
- **Task ID:** `U-2`
- **Name:** frontend setup & integration
- **Agent:** `frontend-specialist`
- **Skills:** `frontend-design`, `tailwind-patterns`
- **Priority:** Medium
- **Dependencies:** `U-1`
- **INPUT:** FastAPI server endpoints.
- **OUTPUT:** Interactive UI allowing inputting search parameters, watching real-time terminal progress, and downloading the output Excel.
- **VERIFY:** Build React app and access via local browser. Run a scraping task and download the generated Excel.

---

## Phase X: Verification

We will run the following checks before marking the project complete:
1. **CLI Run Verification:**
   - Execute `python3 leadforge/main.py Ahmedabad "Hospitals" --limit 10`
   - Verify `output/Ahmedabad_Hospitals.xlsx` is created and format matches PRD.
2. **API Server & UI Integration:**
   - Start local uvicorn server.
   - Run UI dashboard in dev mode and test a mock execution.
3. **Verify Compliance:**
   - [x] No purple/violet color scheme in UI.
   - [x] All check scripts pass.

## ✅ PHASE X COMPLETE
- Lint: ✅ Pass
- Security: ✅ No critical issues
- Build: ✅ Success
- Date: 2026-07-04
