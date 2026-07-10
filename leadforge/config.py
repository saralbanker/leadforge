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

# Phone Normalisation
# Change this for non-Indian deployments (e.g. "+1" for USA/Canada).
DEFAULT_PHONE_COUNTRY_CODE = "+91"

# City → postal-code (PIN) prefix mapping used for deterministic city validation.
# Keys are lowercased city names; values are accepted 3-digit PIN prefixes.
# Override at runtime with the CITY_PIN_PREFIXES setting (JSON object, same shape).
DEFAULT_CITY_PIN_PREFIXES = {
    "ahmedabad": ["380", "382"],
    "gandhinagar": ["382"],
    "surat": ["394", "395"],
    "vadodara": ["390", "391"],
    "baroda": ["390", "391"],
    "rajkot": ["360"],
    "mumbai": ["400"],
    "pune": ["411", "412"],
    "delhi": ["110"],
    "new delhi": ["110"],
    "bengaluru": ["560"],
    "bangalore": ["560"],
    "chennai": ["600"],
    "hyderabad": ["500"],
    "kolkata": ["700"],
    "jaipur": ["302"],
}

# Playwright Scraper Settings
HEADLESS_SCRAPING = True
PLAYWRIGHT_TIMEOUT = 30000  # 30 seconds
PLAYWRIGHT_SLOWMO = 0  # Disabled: smart waits replace artificial delays
