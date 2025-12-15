import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Default to an in-memory SQLite database for tests unless specified otherwise
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
