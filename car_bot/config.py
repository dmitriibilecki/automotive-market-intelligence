from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROJECT_DATA_DIR = BASE_DIR.parent / "data"
SETTINGS_DIR = BASE_DIR.parent / "settings"
DB_PATH = DATA_DIR / "baza_ogloszen.sqlite"
CSV_PATH = DATA_DIR / "eksport_ogloszen.csv"
CAR_MARKET_DB_PATH = PROJECT_DATA_DIR / "rynek_samochodow.sqlite"
REPORTS_PATH = PROJECT_DATA_DIR / "raport_rynku_samochodow.xlsx"
RUN_STATS_PATH = PROJECT_DATA_DIR / "statystyka_uruchomien.jsonl"
OLX_LIMITS_SETTINGS_PATH = SETTINGS_DIR / "olx_limits.txt"
LEGACY_DB_PATH = DATA_DIR / "cars.sqlite"
LEGACY_CSV_PATH = DATA_DIR / "export.csv"
LEGACY_CAR_MARKET_DB_PATH = PROJECT_DATA_DIR / "car_market.sqlite"
LEGACY_REPORTS_PATH = PROJECT_DATA_DIR / "reports.xlsx"

SOURCE = "olx"
DEFAULT_SEARCH_URL = "https://www.olx.pl/motoryzacja/samochody/"
WARSAW_SEARCH_URL = "https://www.olx.pl/motoryzacja/samochody/warszawa/"
WARSAW_EXCEL_PATH = PROJECT_DATA_DIR / "ogloszenia_warszawa.xlsx"
LEGACY_WARSAW_EXCEL_PATH = PROJECT_DATA_DIR / "olx_warsaw_listings.xlsx"

MAX_LISTINGS = 30
OLX_LISTINGS_MAX_PAGES = 2
OLX_LISTINGS_MAX_LISTINGS = 50
MIN_PHOTOS_FOR_SCORE = 5
WARSAW_MAX_PAGES = 10
WARSAW_MAX_LISTINGS = 300
MIN_DELAY_SECONDS = 5
MAX_DELAY_SECONDS = 15
PAGE_TIMEOUT_MS = 60_000

HEADLESS = False
LOCALE = "pl-PL"
VIEWPORT = {"width": 1366, "height": 768}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BLOCK_STATUSES = {403, 429}
BLOCK_TEXT_MARKERS = (
    "captcha",
    "access denied",
    "too many requests",
    "request blocked",
    "forbidden",
    "unusual traffic",
    "verify you are human",
    "are you a robot",
    "czy jesteś robotem",
    "zweryfikuj",
)

FIELDS = (
    "source",
    "external_id",
    "url",
    "title",
    "brand",
    "model",
    "year",
    "price",
    "mileage",
    "fuel",
    "gearbox",
    "body_type",
    "engine_cm3",
    "power_hp",
    "location",
    "scraped_at",
)
