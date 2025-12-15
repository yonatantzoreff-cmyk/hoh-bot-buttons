"""Service layer for calendar import functionality."""

import json
import logging
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from app.appdb import SessionLocal
from app.repositories import (
    ContactRepository,
    EventRepository,
    ImportJobRepository,
    StagingEventRepository,
)
from app.utils.excel_parser import parse_excel_file

logger = logging.getLogger(__name__)


class CalendarImportService:
    """Service for managing calendar imports from Excel."""

    def __init__(self):
        self.staging_repo = StagingEventRepository()
        self.import_job_repo = ImportJobRepository()
        self.event_repo = EventRepository()
        self.contact_repo = ContactRepository()

    def upload_and_parse(
        self, org_id: int, file_content: bytes, filename: str
    ) -> Dict[str, Any]:
        """
        Upload Excel file, clear existing staging data, parse and validate.
        
        Returns summary with counts and any parse errors.
        """
        # Create import job
        job_id = self.import_job_repo.create_job(
            org_id=org_id,
            job_type="calendar_excel",
            source=filename,
            status="running",
        )

        try:
            # Save file temporarily
            with tempfile.NamedTemporaryFile(
                suffix=".xlsx", delete=False
            ) as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name

            try:
                # Parse Excel file
                parsed_events = parse_excel_file(tmp_path)
            finally:
                # Clean up temp file
                Path(tmp_path).unlink(missing_ok=True)

            # Clear existing staging data
            self.staging_repo.clear_all(org_id)

            # Validate each event
            validated_events = []
            for event in parsed_events:
                errors, warnings = self._validate_event(event)
                event["errors"] = errors
                event["warnings"] = warnings
                event["is_valid"] = len(errors) == 0
                validated_events.append(event)

            # Insert into staging
            if validated_events:
                self.staging_repo.bulk_insert(org_id, validated_events)

            # Check for duplicates against official events
            duplicate_warnings = self._check_duplicates(org_id)

            # Prepare summary
            total_rows = len(validated_events)
            valid_rows = sum(1 for e in validated_events if e["is_valid"])
            invalid_rows = total_rows - valid_rows

            details = {
                "total_rows": total_rows,
                "valid_rows": valid_rows,
                "invalid_rows": invalid_rows,
                "duplicate_warnings": duplicate_warnings,
            }

            # Update job status
            self.import_job_repo.update_job(
                job_id=job_id, status="success", details=details
            )

            return {
                "job_id": job_id,
                "status": "success",
                **details,
            }

        except Exception as e:
            logger.exception("Failed to parse Excel file")
            self.import_job_repo.update_job(
                job_id=job_id, status="failed", error_message=str(e)
            )
            raise ValueError(f"Failed to parse Excel file: {str(e)}")

    def _validate_event(
        self, event: Dict[str, Any]
    ) -> Tuple[List[str], List[str]]:
        """
        Validate a single event and return errors and warnings.
        
        Errors block commit, warnings don't.
        """
        errors = []
        warnings = []

        # Hard errors (block commit)
        if not event.get("date"):
            errors.append("Missing or invalid date")
        elif not isinstance(event.get("date"), date):
            errors.append("Invalid date format")

        if not event.get("show_time"):
            errors.append("Missing or invalid show time")
        elif not isinstance(event.get("show_time"), time):
            errors.append("Invalid show time format (must be 24h)")

        if not event.get("name") or not str(event.get("name")).strip():
            errors.append("Event name is required")

        # Warnings (don't block commit)
        if not event.get("producer_phone"):
            warnings.append("Missing producer phone")

        if not event.get("load_in"):
            warnings.append("Missing load-in time")

        if not event.get("producer_name"):
            warnings.append("Missing producer name")

        return errors, warnings

    def _check_duplicates(self, org_id: int) -> List[Dict[str, Any]]:
        """
        Check staging events against official events for potential duplicates.
        
        A duplicate is defined as: same date + show_time + name
        """
        staging_events = self.staging_repo.list_all(org_id)
        official_events = self.event_repo.list_events_for_org(org_id)

        duplicates = []

        for staging in staging_events:
            if not staging.get("is_valid"):
                continue

            staging_date = staging.get("date")
            staging_time = staging.get("show_time")
            staging_name = staging.get("name", "").strip().lower()

            for official in official_events:
                official_date = official.get("event_date")
                official_time = official.get("show_time")
                official_name = official.get("name", "").strip().lower()

                # Extract time component if it's a timestamp
                if official_time and hasattr(official_time, "time"):
                    official_time = official_time.time()

                if (
                    staging_date == official_date
                    and staging_time == official_time
                    and staging_name == official_name
                ):
                    duplicates.append(
                        {
                            "staging_id": staging.get("id"),
                            "staging_row": staging.get("row_index"),
                            "official_event_id": official.get("event_id"),
                            "name": staging.get("name"),
                            "date": str(staging_date),
                            "show_time": str(staging_time),
                        }
                    )

        return duplicates

    def list_staging_events(self, org_id: int) -> List[Dict[str, Any]]:
        """Get all staging events with parsed errors/warnings."""
        events = self.staging_repo.list_all(org_id)

        # Parse JSON fields
        for event in events:
            if event.get("errors_json"):
                event["errors"] = json.loads(event["errors_json"])
            else:
                event["errors"] = []

            if event.get("warnings_json"):
                event["warnings"] = json.loads(event["warnings_json"])
            else:
                event["warnings"] = []

        return events

    def update_staging_event(
        self, org_id: int, staging_id: int, fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update a staging event and revalidate."""
        # Get existing event
        event = self.staging_repo.get_by_id(org_id, staging_id)
        if not event:
            raise ValueError(f"Staging event {staging_id} not found")

        # Update fields
        updated_event = {**event, **fields}

        # Revalidate
        errors, warnings = self._validate_event(updated_event)
        updated_event["errors"] = errors
        updated_event["warnings"] = warnings
        updated_event["is_valid"] = len(errors) == 0

        # Save to database
        update_fields = {
            **fields,
            "is_valid": updated_event["is_valid"],
            "errors_json": json.dumps(errors, ensure_ascii=False),
            "warnings_json": json.dumps(warnings, ensure_ascii=False),
        }

        self.staging_repo.update(org_id, staging_id, update_fields)

        return updated_event

    def add_staging_event(self, org_id: int) -> Dict[str, Any]:
        """Add a new blank staging event."""
        # Find max row_index
        existing = self.staging_repo.list_all(org_id)
        max_row = max((e.get("row_index", 0) for e in existing), default=0)

        new_event = {
            "row_index": max_row + 1,
            "date": None,
            "show_time": None,
            "name": "",
            "load_in": None,
            "event_series": None,
            "producer_name": "",
            "producer_phone": "",
            "notes": "",
            "is_valid": False,
            "errors": ["Event name is required", "Missing or invalid date", "Missing or invalid show time"],
            "warnings": ["Missing producer phone", "Missing load-in time", "Missing producer name"],
        }

        staging_id = self.staging_repo.create(org_id, new_event)
        new_event["id"] = staging_id

        return new_event

    def delete_staging_event(self, org_id: int, staging_id: int) -> None:
        """Delete a staging event."""
        self.staging_repo.delete(org_id, staging_id)

    def revalidate_all(self, org_id: int) -> Dict[str, Any]:
        """Revalidate all staging events and check for duplicates."""
        events = self.staging_repo.list_all(org_id)

        for event in events:
            errors, warnings = self._validate_event(event)
            self.staging_repo.update(
                org_id,
                event["id"],
                {
                    "is_valid": len(errors) == 0,
                    "errors_json": json.dumps(errors, ensure_ascii=False),
                    "warnings_json": json.dumps(warnings, ensure_ascii=False),
                },
            )

        # Check duplicates
        duplicate_warnings = self._check_duplicates(org_id)

        valid_count = self.staging_repo.count_valid(org_id)
        total_count = self.staging_repo.count_total(org_id)

        return {
            "total_rows": total_count,
            "valid_rows": valid_count,
            "invalid_rows": total_count - valid_count,
            "duplicate_warnings": duplicate_warnings,
        }

    def commit_to_events(
        self, org_id: int, skip_duplicates: bool = False
    ) -> Dict[str, Any]:
        """
        Commit valid staging events to official events table.
        
        Args:
            org_id: Organization ID
            skip_duplicates: If True, skip events that are duplicates
            
        Returns:
            Summary of commit operation
        """
        # Get all valid staging events
        staging_events = [
            e
            for e in self.staging_repo.list_all(org_id)
            if e.get("is_valid")
        ]

        if not staging_events:
            raise ValueError("No valid events to commit")

        # Check for duplicates
        duplicate_warnings = self._check_duplicates(org_id)
        duplicate_ids = {d["staging_id"] for d in duplicate_warnings}

        # Filter out duplicates if requested
        if skip_duplicates:
            staging_events = [
                e for e in staging_events if e.get("id") not in duplicate_ids
            ]

        if not staging_events:
            raise ValueError("No events to commit after removing duplicates")

        # Use a transaction to commit all events
        session = SessionLocal()
        committed_count = 0
        error_count = 0
        errors = []

        try:
            for staging_event in staging_events:
                try:
                    self._commit_single_event(org_id, staging_event, session)
                    committed_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(
                        {
                            "row": staging_event.get("row_index"),
                            "error": str(e),
                        }
                    )
                    logger.error(
                        f"Failed to commit staging event {staging_event.get('id')}: {e}"
                    )

            # Commit transaction
            session.commit()

            # Clear all staging data on success
            self.staging_repo.clear_all(org_id)

            return {
                "status": "success",
                "committed_count": committed_count,
                "error_count": error_count,
                "errors": errors,
                "skipped_duplicates": len(duplicate_ids) if skip_duplicates else 0,
            }

        except Exception as e:
            session.rollback()
            logger.exception("Failed to commit staging events")
            raise ValueError(f"Failed to commit events: {str(e)}")
        finally:
            session.close()

    def _commit_single_event(
        self, org_id: int, staging_event: Dict[str, Any], session: Any
    ) -> None:
        """Commit a single staging event to the official events table."""
        # Get or create contact if phone is provided
        producer_contact_id = None
        if staging_event.get("producer_phone"):
            producer_name = staging_event.get("producer_name") or staging_event.get(
                "producer_phone"
            )
            producer_contact_id = self.contact_repo.get_or_create_by_phone(
                org_id=org_id,
                phone=staging_event["producer_phone"],
                name=producer_name,
                role="producer",
            )

        # Combine date + time into timestamptz for show_time and load_in
        event_date = staging_event["date"]
        show_time = staging_event.get("show_time")
        load_in = staging_event.get("load_in")

        show_time_tz = None
        if show_time:
            show_time_tz = datetime.combine(event_date, show_time)

        load_in_tz = None
        if load_in:
            load_in_tz = datetime.combine(event_date, load_in)

        # Get default hall for the org
        hall_query = text("""
            SELECT hall_id FROM halls 
            WHERE org_id = :org_id 
            ORDER BY hall_id 
            LIMIT 1
        """)
        hall_result = session.execute(hall_query, {"org_id": org_id}).scalar_one_or_none()
        
        if not hall_result:
            raise ValueError(f"No hall found for org_id {org_id}. Please create at least one hall before importing events.")
        
        hall_id = hall_result

        # Insert event
        query = text(
            """
            INSERT INTO events (
                org_id, hall_id, name, event_date,
                show_time, load_in_time,
                event_type, status,
                producer_contact_id,
                notes,
                created_at, updated_at
            )
            VALUES (
                :org_id, :hall_id, :name, :event_date,
                :show_time, :load_in_time,
                :event_type, :status,
                :producer_contact_id,
                :notes,
                :now, :now
            )
            """
        )

        now = datetime.utcnow()

        session.execute(
            query,
            {
                "org_id": org_id,
                "hall_id": hall_id,
                "name": staging_event["name"],
                "event_date": event_date,
                "show_time": show_time_tz,
                "load_in_time": load_in_tz,
                "event_type": "show",
                "status": "draft",
                "producer_contact_id": producer_contact_id,
                "notes": staging_event.get("notes"),
                "now": now,
            },
        )

    def clear_all_staging(self, org_id: int) -> None:
        """Clear all staging events."""
        self.staging_repo.clear_all(org_id)
