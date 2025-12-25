import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Default to an in-memory SQLite database for tests unless specified otherwise
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

# Set required Twilio env vars for tests
os.environ.setdefault("TWILIO_ACCOUNT_SID", "test_sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_token")
os.environ.setdefault("CONTENT_SID_INIT", "test")
os.environ.setdefault("CONTENT_SID_RANGES", "test")
os.environ.setdefault("CONTENT_SID_HALVES", "test")
os.environ.setdefault("CONTENT_SID_CONFIRM", "test")
os.environ.setdefault("CONTENT_SID_NOT_SURE", "test")
os.environ.setdefault("CONTENT_SID_CONTACT", "test")
os.environ.setdefault("CONTENT_SID_SHIFT_REMINDER", "test")
os.environ.setdefault("CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT", "test")
