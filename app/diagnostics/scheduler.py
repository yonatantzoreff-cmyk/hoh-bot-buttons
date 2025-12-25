"""
Scheduler Diagnostics Module

Comprehensive diagnostics for debugging why scheduled messages don't appear in the UI/API.
Checks database connection, schema, data visibility, org scoping, endpoint queries, and fetch logic.
"""

import logging
import json
from typing import Optional, Dict, List, Any

from sqlalchemy import text, inspect

from app.appdb import get_session, engine, DATABASE_URL
from app.time_utils import now_utc, utc_to_local_datetime
from app.repositories import EventRepository

logger = logging.getLogger(__name__)

# Constants
SAMPLE_EVENTS_LIMIT = 5


def run_scheduler_diagnostics(org_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Run comprehensive scheduler diagnostics and return structured report.
    
    Args:
        org_id: Optional organization ID to focus diagnostics on (e.g., for org scoping check)
    
    Returns:
        Dictionary with keys: summary, checks, recommendations
    """
    checks = []
    
    # Run all diagnostic checks - don't stop on errors, collect all results
    try:
        db_fingerprint = check_database_fingerprint()
        checks.append(db_fingerprint)
    except Exception as e:
        logger.error(f"DB fingerprint check failed: {e}", exc_info=True)
        checks.append({
            "name": "DB_FINGERPRINT",
            "status": "fail",
            "details": {"error": str(e)},
            "why_it_matters": "Cannot determine which database the app is connected to",
            "likely_root_cause": "Database connection issue",
            "next_actions": ["Check DATABASE_URL environment variable", "Verify database is accessible"]
        })
    
    try:
        schema_check = check_schema_existence()
        checks.append(schema_check)
    except Exception as e:
        logger.error(f"Schema check failed: {e}", exc_info=True)
        checks.append({
            "name": "SCHEMA_CHECK",
            "status": "fail",
            "details": {"error": str(e)},
            "why_it_matters": "Cannot verify table structure",
            "likely_root_cause": "Missing migrations or schema access issue",
            "next_actions": ["Run database migrations", "Check database permissions"]
        })
    
    try:
        data_check = check_scheduled_messages_data(org_id)
        checks.append(data_check)
    except Exception as e:
        logger.error(f"Data visibility check failed: {e}", exc_info=True)
        checks.append({
            "name": "SCHEDULED_MESSAGES_DATA",
            "status": "fail",
            "details": {"error": str(e)},
            "why_it_matters": "Cannot inspect scheduled_messages data",
            "likely_root_cause": "Table missing or query error",
            "next_actions": ["Verify scheduled_messages table exists", "Check for SQL errors"]
        })
    
    try:
        org_check = check_org_scoping(org_id)
        checks.append(org_check)
    except Exception as e:
        logger.error(f"Org scoping check failed: {e}", exc_info=True)
        checks.append({
            "name": "ORG_ID_MISMATCH",
            "status": "fail",
            "details": {"error": str(e)},
            "why_it_matters": "Cannot determine if org_id filtering is causing issues",
            "likely_root_cause": "Query error",
            "next_actions": ["Check query parameters"]
        })
    
    try:
        endpoint_sim = simulate_endpoint_queries(org_id or 1)
        checks.append(endpoint_sim)
    except Exception as e:
        logger.error(f"Endpoint simulation failed: {e}", exc_info=True)
        checks.append({
            "name": "ENDPOINT_SIMULATION",
            "status": "fail",
            "details": {"error": str(e)},
            "why_it_matters": "Cannot simulate API endpoint behavior",
            "likely_root_cause": "Query error or missing data",
            "next_actions": ["Check endpoint query logic", "Verify test data exists"]
        })
    
    try:
        fetch_diag = check_fetch_diagnostics(org_id or 1)
        checks.append(fetch_diag)
    except Exception as e:
        logger.error(f"Fetch diagnostics failed: {e}", exc_info=True)
        checks.append({
            "name": "FETCH_DIAGNOSTICS",
            "status": "fail",
            "details": {"error": str(e)},
            "why_it_matters": "Cannot diagnose why fetch button doesn't import events",
            "likely_root_cause": "Fetch query error or no future events",
            "next_actions": ["Check events table", "Verify date filtering logic"]
        })
    
    try:
        timezone_check = check_timezone_sanity()
        checks.append(timezone_check)
    except Exception as e:
        logger.error(f"Timezone check failed: {e}", exc_info=True)
        checks.append({
            "name": "TIMEZONE_CHECK",
            "status": "fail",
            "details": {"error": str(e)},
            "why_it_matters": "Cannot verify timezone configuration",
            "likely_root_cause": "Database timezone query error",
            "next_actions": ["Check database timezone settings"]
        })
    
    # Compute summary based on all checks
    summary = compute_summary(checks)
    recommendations = generate_recommendations(checks)
    
    return {
        "summary": summary,
        "checks": checks,
        "recommendations": recommendations,
    }


def check_database_fingerprint() -> Dict[str, Any]:
    """
    A) Database fingerprint - prove what DB the app is connected to.
    """
    details = {}
    
    with get_session() as session:
        # current_database()
        result = session.execute(text("SELECT current_database()"))
        details["current_database"] = result.scalar()
        
        # current_schema()
        result = session.execute(text("SELECT current_schema()"))
        details["current_schema"] = result.scalar()
        
        # inet_server_addr() and inet_server_port()
        try:
            result = session.execute(text("SELECT inet_server_addr()"))
            addr = result.scalar()
            details["server_addr"] = str(addr) if addr else "unix_socket"
        except Exception:
            details["server_addr"] = "unable_to_determine"
        
        try:
            result = session.execute(text("SELECT inet_server_port()"))
            details["server_port"] = result.scalar()
        except Exception:
            details["server_port"] = "unable_to_determine"
        
        # version()
        result = session.execute(text("SELECT version()"))
        details["version"] = result.scalar()
        
        # now() and SHOW TIMEZONE
        result = session.execute(text("SELECT now()"))
        details["db_now"] = str(result.scalar())
        
        result = session.execute(text("SHOW TIMEZONE"))
        details["db_timezone"] = result.scalar()
    
    # Mask credentials in DATABASE_URL for security
    safe_url = DATABASE_URL
    if "@" in safe_url:
        # Remove password from URL
        parts = safe_url.split("@")
        if len(parts) == 2:
            user_pass = parts[0].split("://")[-1]
            if ":" in user_pass:
                user = user_pass.split(":")[0]
                safe_url = safe_url.replace(user_pass, user + ":***")
    
    details["database_url_configured"] = safe_url
    
    return {
        "name": "DB_FINGERPRINT",
        "status": "pass",
        "details": details,
        "why_it_matters": "Confirms which database the application is connected to",
        "likely_root_cause": None,
        "next_actions": ["Compare with DBeaver connection settings to ensure they match"]
    }


def check_schema_existence() -> Dict[str, Any]:
    """
    B) Existence + shape of tables.
    """
    details = {}
    inspector = inspect(engine)
    
    # Check table existence
    tables = inspector.get_table_names()
    details["all_tables"] = tables
    details["scheduled_messages_exists"] = "scheduled_messages" in tables
    details["scheduler_settings_exists"] = "scheduler_settings" in tables
    details["events_exists"] = "events" in tables
    details["employee_shifts_exists"] = "employee_shifts" in tables
    
    issues = []
    
    if not details["scheduled_messages_exists"]:
        issues.append("scheduled_messages table is MISSING")
    else:
        # Get scheduled_messages schema details
        columns = inspector.get_columns("scheduled_messages")
        details["scheduled_messages_columns"] = [
            {
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": col["nullable"],
                "default": str(col["default"]) if col["default"] is not None else None
            }
            for col in columns
        ]
        
        # Check for primary key
        pk = inspector.get_pk_constraint("scheduled_messages")
        details["scheduled_messages_primary_key"] = pk.get("constrained_columns", [])
        
        # Check for enums (message_type, status)
        with get_session() as session:
            # Get enum values if they exist
            try:
                result = session.execute(text("""
                    SELECT column_name, data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_name = 'scheduled_messages'
                      AND (column_name = 'message_type' OR column_name = 'status')
                """))
                enum_info = [dict(row._mapping) for row in result]
                details["enum_columns"] = enum_info
            except Exception as e:
                details["enum_columns_error"] = str(e)
    
    if not details["scheduler_settings_exists"]:
        issues.append("scheduler_settings table is MISSING")
    
    if not details["events_exists"]:
        issues.append("events table is MISSING (required for fetch)")
    
    if not details["employee_shifts_exists"]:
        issues.append("employee_shifts table is MISSING (required for shift reminders)")
    
    status = "fail" if issues else "pass"
    likely_root_cause = "Missing migrations" if issues else None
    
    return {
        "name": "SCHEMA_CHECK",
        "status": status,
        "details": details,
        "why_it_matters": "Verifies that all required tables exist with correct structure",
        "likely_root_cause": likely_root_cause,
        "next_actions": ["Run database migrations: db/migrations/011_scheduled_messages_job_key.sql"] if issues else ["Schema looks good"]
    }


def check_scheduled_messages_data(org_id: Optional[int]) -> Dict[str, Any]:
    """
    C) Data visibility checks.
    """
    details = {}
    now = now_utc()
    
    with get_session() as session:
        # Total row count
        result = session.execute(text("SELECT COUNT(*) FROM scheduled_messages"))
        details["total_rows"] = result.scalar()
        
        # Future vs past
        result = session.execute(text("""
            SELECT COUNT(*) FROM scheduled_messages WHERE send_at > :now
        """), {"now": now})
        details["future_rows"] = result.scalar()
        
        result = session.execute(text("""
            SELECT COUNT(*) FROM scheduled_messages WHERE send_at <= :now
        """), {"now": now})
        details["past_rows"] = result.scalar()
        
        # Count by message_type
        result = session.execute(text("""
            SELECT message_type, COUNT(*) as count
            FROM scheduled_messages
            GROUP BY message_type
            ORDER BY message_type
        """))
        details["by_message_type"] = {row[0]: row[1] for row in result}
        
        # Count by status
        result = session.execute(text("""
            SELECT status, COUNT(*) as count
            FROM scheduled_messages
            GROUP BY status
            ORDER BY status
        """))
        details["by_status"] = {row[0]: row[1] for row in result}
        
        # Last 10 rows
        result = session.execute(text("""
            SELECT job_id, org_id, message_type, status, send_at, 
                   event_id, shift_id, created_at
            FROM scheduled_messages
            ORDER BY created_at DESC
            LIMIT 10
        """))
        details["last_10_rows"] = [
            {
                "job_id": row[0],
                "org_id": row[1],
                "message_type": row[2],
                "status": row[3],
                "send_at": str(row[4]),
                "event_id": row[5],
                "shift_id": row[6],
                "created_at": str(row[7])
            }
            for row in result
        ]
        
        # Detect rows missing event_id/shift_id
        result = session.execute(text("""
            SELECT COUNT(*) FROM scheduled_messages 
            WHERE event_id IS NULL AND shift_id IS NULL
        """))
        orphan_count = result.scalar()
        details["rows_missing_both_event_and_shift"] = orphan_count
        
        if orphan_count > 0:
            details["warning"] = f"{orphan_count} rows have no event_id or shift_id - endpoints with JOIN will hide these"
    
    # Determine status
    issues = []
    if details["total_rows"] == 0:
        issues.append("No rows in scheduled_messages at all")
        status = "warn"
    elif details["future_rows"] == 0:
        issues.append("No future scheduled messages (send_at > now)")
        status = "warn"
    else:
        status = "pass"
    
    likely_root_cause = None
    if details["total_rows"] == 0:
        likely_root_cause = "No jobs have been created yet (fetch button not clicked?)"
    elif details["future_rows"] == 0:
        likely_root_cause = "All jobs are in the past or completed"
    
    return {
        "name": "SCHEDULED_MESSAGES_DATA",
        "status": status,
        "details": details,
        "why_it_matters": "Shows whether scheduled_messages table has data and whether it's visible",
        "likely_root_cause": likely_root_cause,
        "next_actions": [
            "Click 'Fetch future events' button to create jobs",
            "Check if jobs were filtered out by show_past=false"
        ] if issues else ["Data looks good"]
    }


def check_org_scoping(org_id: Optional[int]) -> Dict[str, Any]:
    """
    D) Org scoping check.
    """
    details = {}
    
    with get_session() as session:
        # Get org_id distribution in scheduled_messages
        result = session.execute(text("""
            SELECT org_id, COUNT(*) as count
            FROM scheduled_messages
            GROUP BY org_id
            ORDER BY org_id
        """))
        details["org_id_distribution"] = {row[0]: row[1] for row in result}
        
        # Get org_id distribution in events
        result = session.execute(text("""
            SELECT org_id, COUNT(*) as count
            FROM events
            GROUP BY org_id
            ORDER BY org_id
        """))
        details["events_org_id_distribution"] = {row[0]: row[1] for row in result}
    
    if org_id:
        details["requested_org_id"] = org_id
        scheduled_count = details["org_id_distribution"].get(org_id, 0)
        events_count = details["events_org_id_distribution"].get(org_id, 0)
        
        details["scheduled_messages_for_org"] = scheduled_count
        details["events_for_org"] = events_count
        
        if scheduled_count == 0 and events_count > 0:
            status = "warn"
            likely_root_cause = f"org_id {org_id} has {events_count} events but 0 scheduled messages"
            next_actions = [
                f"Run fetch for org_id={org_id}",
                "Check if scheduler_job_builder filters by org_id correctly"
            ]
        elif scheduled_count == 0 and events_count == 0:
            status = "warn"
            likely_root_cause = f"org_id {org_id} has no events and no scheduled messages"
            next_actions = ["Create events for this org first"]
        else:
            status = "pass"
            likely_root_cause = None
            next_actions = [f"org_id {org_id} scoping looks correct"]
    else:
        details["note"] = "No org_id specified - showing global distribution"
        status = "pass"
        likely_root_cause = None
        next_actions = ["Specify ?org_id= query parameter to check specific org scoping"]
    
    return {
        "name": "ORG_SCOPING_CHECK",
        "status": status,
        "details": details,
        "why_it_matters": "Verifies that org_id filtering isn't hiding rows from the UI",
        "likely_root_cause": likely_root_cause,
        "next_actions": next_actions
    }


def simulate_endpoint_queries(org_id: int) -> Dict[str, Any]:
    """
    E) Endpoint query simulation - reproduce API queries.
    """
    details = {}
    now = now_utc()
    
    # Simulate GET /api/scheduler/jobs with different filters
    simulations = []
    
    # 1. Default: hide_sent=false, show_past=false
    with get_session() as session:
        query = text("""
            SELECT COUNT(*)
            FROM scheduled_messages sm
            LEFT JOIN events e ON sm.event_id = e.event_id
            LEFT JOIN employee_shifts es ON sm.shift_id = es.shift_id
            WHERE sm.org_id = :org_id
              AND (sm.send_at >= :now OR sm.status NOT IN ('sent', 'failed', 'skipped'))
        """)
        result = session.execute(query, {"org_id": org_id, "now": now})
        count_default = result.scalar()
    
    simulations.append({
        "description": "Default filters (hide_sent=false, show_past=false)",
        "filters": {"hide_sent": False, "show_past": False},
        "rows_returned": count_default,
        "notes": "Hides past completed jobs (send_at < now AND status in sent/failed/skipped)"
    })
    
    # 2. Show all: show_past=true, hide_sent=false
    with get_session() as session:
        query = text("""
            SELECT COUNT(*)
            FROM scheduled_messages sm
            LEFT JOIN events e ON sm.event_id = e.event_id
            LEFT JOIN employee_shifts es ON sm.shift_id = es.shift_id
            WHERE sm.org_id = :org_id
        """)
        result = session.execute(query, {"org_id": org_id})
        count_all = result.scalar()
    
    simulations.append({
        "description": "Show all (show_past=true, hide_sent=false)",
        "filters": {"hide_sent": False, "show_past": True},
        "rows_returned": count_all,
        "notes": "Shows all jobs regardless of send_at or status"
    })
    
    # 3. Check INNER JOIN impact
    with get_session() as session:
        # Count rows with NULL event_id
        query = text("""
            SELECT COUNT(*)
            FROM scheduled_messages
            WHERE org_id = :org_id AND event_id IS NULL AND message_type != 'SHIFT_REMINDER'
        """)
        result = session.execute(query, {"org_id": org_id})
        null_event_count = result.scalar()
        
        # Count rows with NULL shift_id for SHIFT_REMINDER
        query = text("""
            SELECT COUNT(*)
            FROM scheduled_messages
            WHERE org_id = :org_id AND shift_id IS NULL AND message_type = 'SHIFT_REMINDER'
        """)
        result = session.execute(query, {"org_id": org_id})
        null_shift_count = result.scalar()
    
    details["simulations"] = simulations
    details["join_impact"] = {
        "rows_with_null_event_id": null_event_count,
        "rows_with_null_shift_id": null_shift_count,
        "warning": "LEFT JOIN is used, so NULL foreign keys should not hide rows" if null_event_count + null_shift_count > 0 else None
    }
    
    # Determine status
    status = "pass" if count_default >= 0 else "warn"
    likely_root_cause = None
    if count_default == 0 and count_all > 0:
        likely_root_cause = "All rows are filtered out by show_past=false (they're in the past)"
    
    return {
        "name": "ENDPOINT_SIMULATION",
        "status": status,
        "details": details,
        "why_it_matters": "Shows how many rows API endpoints would return with different filter combinations",
        "likely_root_cause": likely_root_cause,
        "next_actions": [
            "Use show_past=true in UI to see all jobs",
            "Check if jobs are in the past (send_at < now)"
        ] if count_default == 0 and count_all > 0 else ["Endpoint filtering looks correct"]
    }


def check_fetch_diagnostics(org_id: int) -> Dict[str, Any]:
    """
    F) Fetch button diagnostics - why fetch doesn't import events.
    """
    details = {}
    
    try:
        # Use EventRepository to get future events (same as fetch button)
        events_repo = EventRepository()
        future_events = events_repo.list_future_events_for_org(org_id)
        
        details["future_events_found"] = len(future_events)
        
        if len(future_events) == 0:
            # Debug: get last 10 events with date info
            with get_session() as session:
                query = text("""
                    SELECT event_id, name, event_date, 
                           event_date >= CURRENT_DATE as is_future
                    FROM events
                    WHERE org_id = :org_id
                    ORDER BY event_date DESC
                    LIMIT 10
                """)
                result = session.execute(query, {"org_id": org_id})
                details["last_10_events"] = [
                    {
                        "event_id": row[0],
                        "name": row[1],
                        "event_date": str(row[2]),
                        "is_future": row[3]
                    }
                    for row in result
                ]
                
                # Also get total event count
                query = text("SELECT COUNT(*) FROM events WHERE org_id = :org_id")
                result = session.execute(query, {"org_id": org_id})
                details["total_events_in_db"] = result.scalar()
        else:
            # Show sample future events
            details["sample_future_events"] = [
                {
                    "event_id": e["event_id"],
                    "name": e["name"],
                    "event_date": str(e["event_date"])
                }
                for e in future_events[:SAMPLE_EVENTS_LIMIT]
            ]
        
        # Check timezone logic
        now = now_utc()
        israel_now = utc_to_local_datetime(now)
        today_israel = israel_now.date()
        
        details["timezone_context"] = {
            "now_utc": str(now),
            "now_israel": str(israel_now),
            "today_israel": str(today_israel),
            "note": "Fetch uses event_date >= today in Israel time"
        }
        
        status = "warn" if len(future_events) == 0 else "pass"
        likely_root_cause = None
        next_actions = []
        
        if len(future_events) == 0:
            if details.get("total_events_in_db", 0) == 0:
                likely_root_cause = "No events exist in database at all"
                next_actions = ["Create some events first"]
            else:
                likely_root_cause = "All events are in the past (event_date < today in Israel time)"
                next_actions = [
                    "Create events with future dates",
                    "Verify date comparison logic (event_date >= today in Israel time)"
                ]
        else:
            likely_root_cause = None
            next_actions = [f"Fetch would process {len(future_events)} future events"]
        
    except Exception as e:
        logger.error(f"Fetch diagnostics error: {e}", exc_info=True)
        status = "fail"
        details["error"] = str(e)
        likely_root_cause = "Query error in list_future_events_for_org"
        next_actions = ["Check EventRepository.list_future_events_for_org implementation"]
    
    return {
        "name": "FETCH_DIAGNOSTICS",
        "status": status,
        "details": details,
        "why_it_matters": "Explains why fetch button doesn't create scheduled jobs",
        "likely_root_cause": likely_root_cause,
        "next_actions": next_actions
    }


def check_timezone_sanity() -> Dict[str, Any]:
    """
    G) Timezone sanity check.
    """
    details = {}
    
    with get_session() as session:
        # DB timezone
        result = session.execute(text("SHOW TIMEZONE"))
        details["db_timezone"] = result.scalar()
        
        # DB now()
        result = session.execute(text("SELECT now()"))
        db_now = result.scalar()
        details["db_now"] = str(db_now)
        
        # App now (UTC)
        app_now_utc = now_utc()
        app_now_israel = utc_to_local_datetime(app_now_utc)
        
        details["app_now_utc"] = str(app_now_utc)
        details["app_now_israel"] = str(app_now_israel)
        
        # Compare sample send_at timestamps
        result = session.execute(text("""
            SELECT send_at, send_at AT TIME ZONE 'UTC' as send_at_utc,
                   send_at AT TIME ZONE 'Asia/Jerusalem' as send_at_israel
            FROM scheduled_messages
            ORDER BY created_at DESC
            LIMIT 5
        """))
        details["sample_send_at_values"] = [
            {
                "send_at": str(row[0]),
                "send_at_utc": str(row[1]),
                "send_at_israel": str(row[2])
            }
            for row in result
        ]
    
    # Check for potential issues
    issues = []
    if details["db_timezone"].lower() not in ["utc", "asia/jerusalem"]:
        issues.append(f"DB timezone is {details['db_timezone']}, expected UTC or Asia/Jerusalem")
    
    status = "warn" if issues else "pass"
    likely_root_cause = "Timezone mismatch between DB and app" if issues else None
    
    return {
        "name": "TIMEZONE_CHECK",
        "status": status,
        "details": details,
        "why_it_matters": "Ensures timezone handling is consistent between DB and app",
        "likely_root_cause": likely_root_cause,
        "next_actions": ["Verify TIMESTAMPTZ columns store UTC", "Check app uses Asia/Jerusalem for display"] if issues else ["Timezone configuration looks good"]
    }


def compute_summary(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute summary with suspected root cause, confidence, and key evidence.
    """
    # Count check statuses
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    
    # Collect key evidence
    key_evidence = []
    
    # Analyze checks to determine root cause
    suspected_root_cause = "Unknown"
    confidence = 0
    
    # Check for missing tables (highest priority)
    schema_check = next((c for c in checks if c["name"] == "SCHEMA_CHECK"), None)
    if schema_check and schema_check["status"] == "fail":
        suspected_root_cause = "Missing database tables or schema"
        confidence = 95
        key_evidence.append("scheduled_messages or related tables are missing")
    
    # Check for no data at all
    data_check = next((c for c in checks if c["name"] == "SCHEDULED_MESSAGES_DATA"), None)
    if data_check and data_check["details"].get("total_rows", 0) == 0:
        suspected_root_cause = "No scheduled jobs have been created (fetch button not used)"
        confidence = 90
        key_evidence.append("scheduled_messages table is empty (0 rows)")
    
    # Check for no future rows
    if data_check and data_check["details"].get("total_rows", 0) > 0 and data_check["details"].get("future_rows", 0) == 0:
        suspected_root_cause = "All scheduled jobs are in the past (show_past=false filters them out)"
        confidence = 85
        key_evidence.append(f"{data_check['details']['total_rows']} jobs exist but 0 are future")
    
    # Check for fetch issues
    fetch_check = next((c for c in checks if c["name"] == "FETCH_DIAGNOSTICS"), None)
    if fetch_check and fetch_check["details"].get("future_events_found", 0) == 0:
        if data_check and data_check["details"].get("total_rows", 0) == 0:
            suspected_root_cause = "No future events exist (fetch has nothing to import)"
            confidence = 85
            key_evidence.append("0 future events found in database")
    
    # Check for org scoping issues
    org_check = next((c for c in checks if c["name"] == "ORG_SCOPING_CHECK"), None)
    if org_check and org_check["status"] == "warn":
        if "has" in org_check.get("likely_root_cause", ""):
            suspected_root_cause = "Org ID mismatch (events exist but jobs don't)"
            confidence = 75
            key_evidence.append(org_check["likely_root_cause"])
    
    # Check for DB connection issues
    db_check = next((c for c in checks if c["name"] == "DB_FINGERPRINT"), None)
    if db_check and db_check["status"] == "fail":
        suspected_root_cause = "Database connection issue"
        confidence = 95
        key_evidence.append("Cannot connect to database or query basic info")
    
    # Add more evidence
    if data_check:
        by_status = data_check["details"].get("by_status", {})
        if by_status:
            key_evidence.append(f"Status distribution: {by_status}")
    
    if fetch_check:
        future_count = fetch_check["details"].get("future_events_found", 0)
        key_evidence.append(f"Future events available for fetch: {future_count}")
    
    # Limit evidence to 6 items
    key_evidence = key_evidence[:6]
    
    return {
        "suspected_root_cause": suspected_root_cause,
        "confidence": confidence,
        "key_evidence": key_evidence,
        "checks_summary": {
            "total": len(checks),
            "passed": pass_count,
            "warnings": warn_count,
            "failed": fail_count
        }
    }


def generate_recommendations(checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generate prioritized recommendations based on check results.
    """
    recommendations = []
    
    # P0 recommendations (critical issues)
    schema_check = next((c for c in checks if c["name"] == "SCHEMA_CHECK"), None)
    if schema_check and schema_check["status"] == "fail":
        recommendations.append({
            "priority": "P0",
            "title": "Run database migrations",
            "description": "Required tables are missing. Run migration: db/migrations/011_scheduled_messages_job_key.sql",
            "commands": ["psql $DATABASE_URL < db/migrations/011_scheduled_messages_job_key.sql"]
        })
    
    db_check = next((c for c in checks if c["name"] == "DB_FINGERPRINT"), None)
    if db_check and db_check["status"] == "fail":
        recommendations.append({
            "priority": "P0",
            "title": "Fix database connection",
            "description": "Cannot connect to database. Check DATABASE_URL environment variable.",
            "commands": ["echo $DATABASE_URL", "Check database is running and accessible"]
        })
    
    # P1 recommendations (major issues)
    data_check = next((c for c in checks if c["name"] == "SCHEDULED_MESSAGES_DATA"), None)
    if data_check and data_check["details"].get("total_rows", 0) == 0:
        recommendations.append({
            "priority": "P1",
            "title": "Create scheduled jobs using fetch button",
            "description": "No scheduled jobs exist. Click 'Fetch future events' button in the scheduler UI.",
            "commands": ["POST /api/scheduler/fetch with org_id=1"]
        })
    
    fetch_check = next((c for c in checks if c["name"] == "FETCH_DIAGNOSTICS"), None)
    if fetch_check and fetch_check["details"].get("future_events_found", 0) == 0:
        if fetch_check["details"].get("total_events_in_db", 0) == 0:
            recommendations.append({
                "priority": "P1",
                "title": "Create events",
                "description": "No events exist in database. Create some events with future dates first.",
                "commands": ["Use UI to create events, or import from calendar"]
            })
        else:
            recommendations.append({
                "priority": "P1",
                "title": "Create events with future dates",
                "description": "All events are in the past. Create events with event_date >= today (in Asia/Jerusalem time).",
                "commands": ["Check event_date values", "Create new events or update existing ones"]
            })
    
    # P2 recommendations (minor issues/suggestions)
    if data_check and data_check["details"].get("future_rows", 0) == 0 and data_check["details"].get("total_rows", 0) > 0:
        recommendations.append({
            "priority": "P2",
            "title": "Show past jobs in UI",
            "description": "Jobs exist but are hidden because they're in the past. Use show_past=true filter.",
            "commands": ["GET /api/scheduler/jobs?show_past=true"]
        })
    
    org_check = next((c for c in checks if c["name"] == "ORG_SCOPING_CHECK"), None)
    if org_check and org_check["status"] == "warn":
        recommendations.append({
            "priority": "P2",
            "title": "Check org_id scoping",
            "description": org_check.get("likely_root_cause", "Verify org_id filtering"),
            "commands": org_check.get("next_actions", [])
        })
    
    # If no recommendations, add a success message
    if not recommendations:
        recommendations.append({
            "priority": "INFO",
            "title": "All checks passed",
            "description": "Scheduler diagnostics found no issues. System appears healthy.",
            "commands": []
        })
    
    return recommendations


# CLI entrypoint
if __name__ == "__main__":
    """
    CLI entrypoint for running diagnostics locally.
    
    Usage:
        python -m app.diagnostics.scheduler
        python -m app.diagnostics.scheduler --org-id 1
    """
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Run scheduler diagnostics")
    parser.add_argument("--org-id", type=int, help="Organization ID to focus on")
    args = parser.parse_args()
    
    try:
        report = run_scheduler_diagnostics(org_id=args.org_id)
        print(json.dumps(report, indent=2))
        sys.exit(0)
    except Exception as e:
        logger.error(f"Diagnostics failed: {e}", exc_info=True)
        print(json.dumps({
            "error": str(e),
            "message": "Diagnostics execution failed"
        }, indent=2))
        sys.exit(1)
