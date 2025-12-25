"""
Konfigurationsindstillinger for WTB Market Monitor
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Indlæs miljøvariabler fra .env fil
load_dotenv()

# Basis mapper
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# MySQL Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "wtb_scraper")

# Legacy SQLite path (kept for reference)
DATABASE_PATH = DATA_DIR / "sneakers.db"

# WTB Market List indstillinger
WTB_BASE_URL = "https://www.wtbmarketlist.eu"
WTB_ADONIO_URL = f"{WTB_BASE_URL}/store/adonio"

# Din butiks indstillinger
MY_STORE_URL = os.getenv("MY_STORE_URL", "")
MY_STORE_TYPE = os.getenv("MY_STORE_TYPE", "shopify")

# Nordic Sneakers API
NORDIC_SNEAKERS_API_URL = "https://nordicsneakers.dk/seller/api/v2/products"
NORDIC_SNEAKERS_COOKIE = os.getenv("NORDIC_SNEAKERS_COOKIE", "")

# Scraping indstillinger
REQUEST_DELAY = 2  # Sekunder mellem requests for at undgå rate limiting

# Server indstillinger
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Applikationsindstillinger
APP_ENV = os.getenv("APP_ENV", "production")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Logging konfiguration
def setup_logging(name: str = "wtb_monitor") -> logging.Logger:
    """Opsæt logging med fil og konsol output."""
    logger = logging.getLogger(name)

    # Undgå duplikerede handlers
    if logger.handlers:
        return logger

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logger.setLevel(level)

    # Format
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Konsol handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Fil handler (kun i produktion)
    if APP_ENV == "production":
        file_handler = logging.FileHandler(
            LOGS_DIR / "app.log",
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

# Opret global logger
logger = setup_logging()
