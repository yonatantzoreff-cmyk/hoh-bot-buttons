"""Environment helpers for internal services."""

import os
from typing import Optional


def get_scheduler_token() -> Optional[str]:
    """
    Get the scheduler run token from environment.
    
    Returns:
        The token value or None if not set.
    """
    return os.getenv("SCHEDULER_RUN_TOKEN")


def is_scheduler_token_configured() -> bool:
    """
    Check if the scheduler token is configured.
    
    Returns:
        True if SCHEDULER_RUN_TOKEN is set, False otherwise.
    """
    token = get_scheduler_token()
    return token is not None and len(token.strip()) > 0
