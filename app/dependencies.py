"""Common FastAPI dependency providers."""

from typing import Iterator

from sqlalchemy.orm import Session

from app.appdb import SessionLocal
from app.hoh_service import HOHService

_hoh_service: HOHService | None = None


def get_hoh_service() -> HOHService:
    """Return a singleton-like instance of :class:`HOHService`.

    The service is initialized once per process and reused for subsequent
    dependency injections.
    """

    global _hoh_service
    if _hoh_service is None:
        _hoh_service = HOHService()
    return _hoh_service


def get_db_session() -> Iterator[Session]:
    """Yield a SQLAlchemy session for FastAPI dependencies."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
