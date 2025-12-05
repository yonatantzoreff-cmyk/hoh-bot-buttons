"""Common FastAPI dependency providers."""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from app.hoh_service import HOHService

_hoh_service: "HOHService | None" = None


def _create_hoh_service() -> "HOHService":
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL is required to initialize HOHService; set it before using this dependency."
        )

    # Imported lazily so modules that don't need the DB can still be imported
    from app.hoh_service import HOHService

    return HOHService()


def get_hoh_service() -> "HOHService":
    """Return a singleton-like instance of :class:`HOHService`.

    The service is initialized once per process and reused for subsequent
    dependency injections.
    """

    global _hoh_service
    if _hoh_service is None:
        _hoh_service = _create_hoh_service()
    return _hoh_service
