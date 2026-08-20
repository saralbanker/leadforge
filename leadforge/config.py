from pathlib import Path

# Base Directories
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = BASE_DIR / "leadforge.db"

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

# ============================================================================
# Centralized Configuration Layer (Outreach Extension)
# ============================================================================
import os

# Auto-load .env file if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Ollama API Configuration
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434").strip()
DEFAULT_LLM_MODEL = "llama3.1:8b"
DEFAULT_LLM_MAX_TOKENS = 150
DEFAULT_LLM_TEMPERATURE = 0.2


def get_smtp_config(settings_cache=None) -> dict:
    """Resolves SMTP configuration using unified priority chain:
    1. Process Environment Variables (if SMTP_HOST is explicitly defined in env)
    2. SQLite settings table via SettingsCache
    3. Default empty strings / disabled state
    """
    env_host = os.getenv("SMTP_HOST")
    if env_host and env_host.strip():
        host = env_host.strip()
        port_raw = os.getenv("SMTP_PORT", "587")
        user = os.getenv("SMTP_USERNAME", "")
        pwd = os.getenv("SMTP_PASSWORD", "")
        from_email = os.getenv("SMTP_FROM_EMAIL", "")
        from_name = os.getenv("SMTP_FROM_NAME", "Orvion")
        use_tls = os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")
        reply_to = os.getenv("SMTP_REPLY_TO", "")
        try:
            timeout = int(os.getenv("SMTP_TIMEOUT", "30"))
        except ValueError:
            timeout = 30
    else:
        if settings_cache is None:
            try:
                from leadforge.repositories.settings import SettingsCache
                settings_cache = SettingsCache()
            except Exception:
                settings_cache = None

        if settings_cache:
            host = settings_cache.get_str("smtp.host", "").strip()
            port_raw = str(settings_cache.get_int("smtp.port", 587))
            user = settings_cache.get_str("smtp.username", "").strip()
            pwd = settings_cache.get_str("smtp.password", "").strip()
            from_email = settings_cache.get_str("smtp.from_email", "").strip()
            from_name = settings_cache.get_str("smtp.from_name", "Orvion").strip()
            use_tls_val = settings_cache.get_str("smtp.use_tls", "true")
            use_tls = str(use_tls_val).lower() in ("true", "1", "yes")
            reply_to = settings_cache.get_str("smtp.reply_to", "").strip()
            timeout = settings_cache.get_int("smtp.timeout", 30)
        else:
            host = port_raw = user = pwd = from_email = reply_to = ""
            from_name = "Orvion"
            use_tls = True
            timeout = 30

    configured = bool(host and user and from_email)
    try:
        port = int(port_raw) if port_raw else 587
    except ValueError:
        port = 587

    return {
        "host": host,
        "port": port,
        "username": user,
        "password": pwd,
        "from_email": from_email,
        "from_name": from_name,
        "use_tls": use_tls,
        "reply_to": reply_to,
        "timeout": timeout,
        "is_configured": configured,
    }


# Backwards compatibility module exports
_init_cfg = get_smtp_config()
SMTP_HOST = _init_cfg["host"]
SMTP_PORT = _init_cfg["port"]
SMTP_USERNAME = _init_cfg["username"]
SMTP_PASSWORD = _init_cfg["password"]
SMTP_FROM_NAME = _init_cfg["from_name"]
SMTP_FROM_EMAIL = _init_cfg["from_email"]
SMTP_USE_TLS = _init_cfg["use_tls"]
SMTP_REPLY_TO = _init_cfg["reply_to"]
SMTP_TIMEOUT = _init_cfg["timeout"]
SMTP_CONFIGURED = _init_cfg["is_configured"]


