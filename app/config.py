import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE loader for a git-ignored .env file; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():  # -sig: tolerate Notepad's BOM
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")
DATA_DIR = Path(os.getenv("GAS_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "gas.db"
MODEL_PATH = DATA_DIR / "restock_model.joblib"
METRICS_PATH = DATA_DIR / "model_metrics.json"
OUTBOX_DIR = DATA_DIR / "outbox"

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Commercial Gas Agency")
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
HTTPS_ONLY = os.getenv("HTTPS_ONLY", "0") == "1"

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@gasagency.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin12345")

# Reminder emails go out when the predicted restock date is within this many days.
REMINDER_DAYS = int(os.getenv("REMINDER_DAYS", "3"))
AUTO_REMINDERS = os.getenv("AUTO_REMINDERS", "1") == "1"
REMINDER_CHECK_HOURS = float(os.getenv("REMINDER_CHECK_HOURS", "6"))
BOOKING_LINK_DAYS = 14

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "noreply@gasagency.local")
# Send every email to this address instead of the real recipient (safe demo/testing).
TEST_EMAIL_REDIRECT = os.getenv("TEST_EMAIL_REDIRECT", "")
