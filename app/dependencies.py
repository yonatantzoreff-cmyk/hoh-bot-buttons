"""Common FastAPI dependency providers."""

from app.appdb import get_session
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


def get_db_session():
    """Yield a database session for request-scoped work."""

    with get_session() as session:
        yield session
