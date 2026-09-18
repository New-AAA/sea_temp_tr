from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
DB = DATA / "seatemp.db"

TARGET_URL = "https://pirireis.mgm.gov.tr/deniz-suyu-sicakliklari"
TIMEMAP_URL = "https://web.archive.org/web/timemap/link/" + TARGET_URL
# `id_` serves the originally-archived bytes, without Wayback's injected banner/JS.
SNAPSHOT_URL = "https://web.archive.org/web/{ts}id_/" + TARGET_URL

USER_AGENT = (
    "seatemp-archive/0.1 (research; sea-water temperature time series; "
    "contact via repository owner)"
)
REQUEST_TIMEOUT = 90
POLITE_DELAY = 1.5   # seconds between Wayback requests
MAX_RETRIES = 4
