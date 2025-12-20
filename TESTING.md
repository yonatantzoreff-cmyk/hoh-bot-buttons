# JacksonBot Fixes - Test Documentation

## Running Tests

### Prerequisites

Install test dependencies:
```bash
pip install pytest pytest-asyncio httpx
pip install -r requirements.txt
```

### Running All Tests

To run the complete test suite:

```bash
TWILIO_ACCOUNT_SID=test_sid \
TWILIO_AUTH_TOKEN=test_token \
CONTENT_SID_INIT=test_init \
CONTENT_SID_RANGES=test_ranges \
CONTENT_SID_HALVES=test_halves \
CONTENT_SID_CONFIRM=test_confirm \
CONTENT_SID_NOT_SURE=test_not_sure \
CONTENT_SID_CONTACT=test_contact \
CONTENT_SID_SHIFT_REMINDER=test_reminder \
python -m pytest tests/ -v
```

### Running Specific Test Files

#### JacksonBot Fixes Tests (PHASES 1-6)
```bash
TWILIO_ACCOUNT_SID=test_sid \
TWILIO_AUTH_TOKEN=test_token \
CONTENT_SID_INIT=test_init \
CONTENT_SID_RANGES=test_ranges \
CONTENT_SID_HALVES=test_halves \
CONTENT_SID_CONFIRM=test_confirm \
CONTENT_SID_NOT_SURE=test_not_sure \
CONTENT_SID_CONTACT=test_contact \
CONTENT_SID_SHIFT_REMINDER=test_reminder \
python -m pytest tests/test_jacksonbot_fixes.py -v
```

#### Other Test Files
```bash
# Timezone tests
python -m pytest tests/test_timezone_fixes.py -v

# Excel parser tests
python -m pytest tests/test_excel_parser.py -v

# Shift generator tests
python -m pytest tests/test_shift_generator.py -v
```

## Test Coverage

### PHASE 1: Follow-up Flow Tests
- `test_follow_up_updates_event_status` - Verifies event status changes to 'follow_up'
- `test_follow_up_sends_acknowledgment` - Verifies acknowledgment message is sent

### PHASE 2: Shift Creation Tests
- `test_shift_creation_nullable_employee_id` - Tests creating shifts without assigned employees
- `test_shift_creation_with_employee_id` - Tests creating shifts with assigned employees

### PHASE 3: Contacts Endpoint Tests
- `test_contacts_by_role_includes_phone` - Verifies phone numbers are included in contacts
- `test_contacts_data_structure` - Validates contact data structure for dropdowns

### PHASE 4: Message Routing Tests
- `test_message_routing_prefers_technical` - Verifies messages sent to technical first
- `test_message_routing_fallback_to_producer` - Verifies fallback to producer when no technical

## Test Results Summary

As of the latest run:
- **Total Tests**: 64
- **Passed**: 63
- **Failed**: 1 (pre-existing, unrelated to changes)

### Passing Tests Breakdown:
- API Timezone: 5 tests ✓
- Calendar Import: 2 tests ✓
- Events API: 5 tests ✓ (1 pre-existing failure unrelated to our changes)
- Excel Parser: 7 tests ✓
- HOH Service Helpers: 7 tests ✓
- **JacksonBot Fixes: 8 tests ✓** (NEW)
- Shift Generator: 10 tests ✓
- Staging Schema: 1 test ✓
- Timezone Fixes: 17 tests ✓
- Twilio Client: 1 test ✓

## Known Issues

### test_events_api_endpoints_exist
This test fails because it expects `/events` but the actual endpoint is `/api/events`. This is a pre-existing issue not related to the JacksonBot fixes and does not affect functionality.

## Database Migrations

The test suite uses an in-memory SQLite database by default. For production testing, ensure the following migrations have been applied:

1. `002_calendar_import.sql` - Calendar import feature
2. `004_shift_organizer.sql` - Shift organizer enhancements
3. `005_notifications.sql` - Notification system
4. `006_add_next_followup_at.sql` - Follow-up tracking
5. `007_make_shift_employee_nullable.sql` - **NEW**: Makes employee_id nullable in shifts

## CI/CD Integration

For CI/CD pipelines, use the following command:

```bash
export TWILIO_ACCOUNT_SID=test_sid
export TWILIO_AUTH_TOKEN=test_token
export CONTENT_SID_INIT=test_init
export CONTENT_SID_RANGES=test_ranges
export CONTENT_SID_HALVES=test_halves
export CONTENT_SID_CONFIRM=test_confirm
export CONTENT_SID_NOT_SURE=test_not_sure
export CONTENT_SID_CONTACT=test_contact
export CONTENT_SID_SHIFT_REMINDER=test_reminder

python -m pytest tests/ -v --tb=short
```
