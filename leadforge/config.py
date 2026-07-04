from pathlib import Path

# Base Directories
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Default Scraping Settings
DEFAULT_CITY = "Ahmedabad"
DEFAULT_CATEGORY = "Manufacturers"
DEFAULT_LIMIT = 50

# Lead Scoring Metrics
SCORE_NO_WEBSITE = 60
SCORE_WITH_WEBSITE = 0

# Scraping Configuration
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Playwright Scraper Settings
HEADLESS_SCRAPING = True
PLAYWRIGHT_TIMEOUT = 30000  # 30 seconds
PLAYWRIGHT_SLOWMO = 500     # 500ms delay to prevent rate limits
