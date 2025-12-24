"""Utilities to ensure required database schema exists for calendar import."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.appdb import DATABASE_URL, engine

logger = logging.getLogger(__name__)

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "002_calendar_import.sql"
SHIFT_ORGANIZER_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "004_shift_organizer.sql"
NOTIFICATIONS_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "005_notifications.sql"
NEXT_FOLLOWUP_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "006_add_next_followup_at.sql"
SHIFT_EMPLOYEE_NULLABLE_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "007_make_shift_employee_nullable.sql"
CONVERSATION_STATE_MACHINE_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "008_conversation_state_machine.sql"
SCHEDULED_MESSAGES_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "009_scheduled_messages.sql"


class SchemaMissingError(RuntimeError):
    """Raised when a required database table is missing."""


def database_label() -> str:
    """Return a safe, credential-free label for the configured database."""

    url = make_url(DATABASE_URL)
    host = url.host or "localhost"
    name = url.database or ""
    return f"{host}/{name}" if name else host


def _ensure_indexes() -> None:
    """Create staging indexes if they are missing.

    Uses IF NOT EXISTS to stay idempotent and safe in production.
    """

    index_statements: Iterable[str] = (
        "CREATE INDEX IF NOT EXISTS idx_staging_events_org_id ON staging_events(org_id);",
        "CREATE INDEX IF NOT EXISTS idx_staging_events_is_valid ON staging_events(org_id, is_valid);",
        "CREATE INDEX IF NOT EXISTS idx_staging_events_org_date_show_time ON staging_events(org_id, date, show_time);",
    )

    with engine.begin() as conn:
        for stmt in index_statements:
            conn.exec_driver_sql(stmt)


def _apply_calendar_migration() -> None:
    """Apply the calendar import migration if the staging table is missing."""

    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    logger.info("Applying calendar import migration from %s", MIGRATION_PATH)
    if engine.dialect.name == "sqlite":
        statements = (
            """
            CREATE TABLE IF NOT EXISTS staging_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                date DATE,
                show_time TIME,
                name TEXT,
                load_in TIME,
                event_series TEXT,
                producer_name TEXT,
                producer_phone TEXT,
                notes TEXT,
                is_valid BOOLEAN NOT NULL DEFAULT FALSE,
                errors_json TEXT,
                warnings_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
    else:
        statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]

    with engine.begin() as conn:
        for stmt in statements:
            conn.exec_driver_sql(stmt)


def _apply_shift_organizer_migration() -> None:
    """Apply the shift organizer migration for unavailability and enhanced shifts."""
    sql = SHIFT_ORGANIZER_MIGRATION_PATH.read_text(encoding="utf-8")
    logger.info("Applying shift organizer migration from %s", SHIFT_ORGANIZER_MIGRATION_PATH)
    
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.exec_driver_sql(stmt)
            except Exception as e:
                # Log but don't fail if column already exists (idempotent)
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"Skipping statement (already applied): {stmt[:50]}...")
                else:
                    raise


def _apply_notifications_migration() -> None:
    """Apply the notifications migration for user notification state."""
    sql = NOTIFICATIONS_MIGRATION_PATH.read_text(encoding="utf-8")
    logger.info("Applying notifications migration from %s", NOTIFICATIONS_MIGRATION_PATH)
    
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.exec_driver_sql(stmt)
            except Exception as e:
                # Log but don't fail if table/column already exists (idempotent)
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"Skipping statement (already applied): {stmt[:50]}...")
                else:
                    raise


def _apply_next_followup_migration() -> None:
    """Apply the next_followup_at migration for follow-up tracking."""
    sql = NEXT_FOLLOWUP_MIGRATION_PATH.read_text(encoding="utf-8")
    logger.info("Applying next_followup_at migration from %s", NEXT_FOLLOWUP_MIGRATION_PATH)
    
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.exec_driver_sql(stmt)
            except Exception as e:
                # Log but don't fail if column already exists (idempotent)
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"Skipping statement (already applied): {stmt[:50]}...")
                else:
                    raise


def _apply_shift_employee_nullable_migration() -> None:
    """Apply migration to make employee_id nullable in employee_shifts (PHASE 2)."""
    sql = SHIFT_EMPLOYEE_NULLABLE_MIGRATION_PATH.read_text(encoding="utf-8")
    logger.info("Applying shift employee nullable migration from %s", SHIFT_EMPLOYEE_NULLABLE_MIGRATION_PATH)
    
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.exec_driver_sql(stmt)
            except Exception as e:
                # Log but don't fail if already applied (idempotent)
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower() or "does not exist" in str(e).lower():
                    logger.info(f"Skipping statement (already applied or N/A): {stmt[:50]}...")
                else:
                    raise


def _apply_conversation_state_machine_migration() -> None:
    """Apply migration to add conversation state machine fields."""
    sql = CONVERSATION_STATE_MACHINE_MIGRATION_PATH.read_text(encoding="utf-8")
    logger.info("Applying conversation state machine migration from %s", CONVERSATION_STATE_MACHINE_MIGRATION_PATH)
    
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.exec_driver_sql(stmt)
            except Exception as e:
                # Log but don't fail if already applied (idempotent)
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"Skipping statement (already applied or N/A): {stmt[:50]}...")
                else:
                    raise


def _apply_scheduled_messages_migration() -> None:
    """Apply migration to add scheduled_messages and scheduler_settings tables."""
    sql = SCHEDULED_MESSAGES_MIGRATION_PATH.read_text(encoding="utf-8")
    logger.info("Applying scheduled messages migration from %s", SCHEDULED_MESSAGES_MIGRATION_PATH)
    
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.exec_driver_sql(stmt)
            except Exception as e:
                # Log but don't fail if already applied (idempotent)
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"Skipping statement (already applied or N/A): {stmt[:50]}...")
                else:
                    raise


def ensure_calendar_schema() -> None:
    """Ensure the staging_events table exists and indexes are present.

    If the table is missing, attempt to apply the migration. If it is still
    missing afterwards, raise :class:`SchemaMissingError` so the app fails early
    with a clear message.
    """

    inspector = inspect(engine)
    has_table = "staging_events" in inspector.get_table_names()

    if not has_table:
        _apply_calendar_migration()
        inspector = inspect(engine)
        has_table = "staging_events" in inspector.get_table_names()

    if not has_table:
        raise SchemaMissingError(
            f"DB schema missing staging_events; run migrations for {database_label()}"
        )

    try:
        _ensure_indexes()
    except SQLAlchemyError:
        logger.exception("Failed to ensure staging_events indexes exist")
        # Don't block startup solely on an index creation failure
    
    # Apply shift organizer migration
    try:
        _apply_shift_organizer_migration()
    except Exception as e:
        logger.warning(f"Shift organizer migration issue (may already be applied): {e}")
        # Don't block startup if migration already applied
    
    # Apply notifications migration
    try:
        _apply_notifications_migration()
    except Exception as e:
        logger.warning(f"Notifications migration issue (may already be applied): {e}")
        # Don't block startup if migration already applied
    
    # Apply next_followup_at migration (PHASE 1)
    try:
        _apply_next_followup_migration()
    except Exception as e:
        logger.warning(f"Next followup migration issue (may already be applied): {e}")
        # Don't block startup if migration already applied
    
    # Apply shift employee nullable migration (PHASE 2)
    try:
        _apply_shift_employee_nullable_migration()
    except Exception as e:
        logger.warning(f"Shift employee nullable migration issue (may already be applied): {e}")
        # Don't block startup if migration already applied
    
    # Apply conversation state machine migration
    try:
        _apply_conversation_state_machine_migration()
    except Exception as e:
        logger.warning(f"Conversation state machine migration issue (may already be applied): {e}")
        # Don't block startup if migration already applied
    
    # Apply scheduled messages migration
    try:
        _apply_scheduled_messages_migration()
    except Exception as e:
        logger.warning(f"Scheduled messages migration issue (may already be applied): {e}")
        # Don't block startup if migration already applied


def require_staging_table() -> None:
    """Raise a helpful error if the staging table is absent."""

    inspector = inspect(engine)
    if "staging_events" not in inspector.get_table_names():
        raise SchemaMissingError(
            f"DB schema missing staging_events; run migrations for {database_label()}"
        )
