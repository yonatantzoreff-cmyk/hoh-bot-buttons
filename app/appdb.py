# appdb.py
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# לוקחים את ה-URL מה-Environment של Render
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment variables")

# יוצרים engine אחד לכל האפליקציה
engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,   # מוודא שחיבורים מתים מנוקים
)

# מחולל sessions – כל פעולה על הדיבי עובדת בתוך session
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


@contextmanager
def get_session():
    """קונטקסט מנג'ר נוח לשימוש:
    with get_session() as session:
        session.execute(...)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
