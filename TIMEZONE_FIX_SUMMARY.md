# Timezone Fix Implementation Summary

## Problem Statement

The HOH Bot system had a critical timezone bug where event times would "lose 2 hours" after each save/edit operation. For example:
- User creates event with time 21:00
- Event displays as 19:00 after saving
- Each subsequent edit shifted the time by another 2 hours

## Root Causes

1. **Manual timezone offset**: `LOCAL_TZ = timezone(timedelta(hours=2))` didn't handle Daylight Saving Time (DST)
2. **Improper timezone stripping**: `_strip_timezone()` removed timezone info without proper conversion
3. **Naive datetimes**: Inconsistent use of timezone-aware vs naive datetimes
4. **Mixed approaches**: Some code used `pytz`, some used manual offsets, some used `zoneinfo`

## Solution

Implemented a **centralized timezone approach** with the following components:

### 1. Centralized Time Utilities (`app/time_utils.py`)

Created a single source of truth for all timezone operations:

- `parse_local_time_to_utc(date, "HH:MM")` - Convert Israel local time to UTC for DB storage
- `utc_to_local_time_str(datetime)` - Convert UTC from DB to Israel time string for display
- `parse_datetime_local_input(str)` - Parse HTML datetime-local inputs properly
- `utc_to_local_datetime(datetime)` - Convert UTC to Israel local datetime
- `now_utc()` - Get current time as timezone-aware UTC datetime
- `ensure_aware(datetime)` - Safety function to ensure timezone awareness

### 2. Core Fixes

**hoh_service.py**:
- Removed `LOCAL_TZ = timezone(timedelta(hours=2))`
- Updated `_combine_time()` to use `parse_local_time_to_utc()`
- Updated `_format_time_israel()` to use `utc_to_local_time_str()`
- Replaced all `datetime.utcnow()` with `now_utc()`

**routers/ui.py**:
- Replaced `_strip_timezone()` with `utc_to_local_time_str()`
- Fixed `edit_event_form()` to properly convert DB times for display
- Updated shift handlers to use `parse_datetime_local_input()`

**repositories.py**:
- Replaced all 19 instances of `datetime.utcnow()` with `now_utc()`

**calendar_import_service.py**:
- Updated time parsing to use `parse_local_time_to_utc()`

**flows/slots.py**:
- Replaced `pytz` with `zoneinfo` for timezone handling

### 3. Comprehensive Testing

Added 17 new timezone tests (`tests/test_timezone_fixes.py`):
- Round-trip UI→DB→UI preservation
- Edit operations don't shift times
- DST handling for both summer (UTC+3) and winter (UTC+2)
- Multiple edits don't cause drift
- Twilio message formatting shows correct local times
- Edge cases and error handling

**All 35 tests pass** (17 new + 18 existing).

### 4. Documentation

Updated README.md with:
- Timezone handling standards
- Key principles
- Before/after examples
- Code examples
- Testing instructions

## Standards and Principles

### Database Storage
- All timestamps stored as **UTC** in `TIMESTAMPTZ` columns
- Never store local times directly in the database

### UI Display
- All times displayed in **Israel local time (Asia/Jerusalem)**
- Use `utc_to_local_time_str()` for conversion

### User Input
- UI accepts times in **Israel local time**
- Use `parse_local_time_to_utc()` or `parse_datetime_local_input()` for conversion

### Twilio Messages
- All times in WhatsApp messages shown in **Israel local time**
- Format times using `utc_to_local_time_str()` before sending

### DST Handling
- **Never add/subtract hours manually** (+2, -2, etc.)
- Let `zoneinfo` library handle DST transitions automatically
- Works correctly for both summer (UTC+3) and winter (UTC+2) in Israel

### Code Guidelines
1. Always use timezone-aware datetimes (`datetime.now(timezone.utc)` not `datetime.utcnow()`)
2. Use `app/time_utils.py` for all timezone conversions
3. Never use `.replace(tzinfo=None)` or similar timezone stripping
4. Use `zoneinfo` (standard library), not `pytz`
5. Test with both summer and winter dates to verify DST handling

## Verification

### Manual Testing Checklist
- [ ] Create event with time 21:00 → Displays as 21:00
- [ ] Edit event without changing time → Still displays as 21:00
- [ ] Edit event multiple times → Time never drifts
- [ ] Test in summer months (July-August) → Correct UTC+3 offset
- [ ] Test in winter months (December-February) → Correct UTC+2 offset
- [ ] WhatsApp messages show correct local times

### Automated Tests
```bash
# Run all tests
pytest tests/ -v

# Run only timezone tests
pytest tests/test_timezone_fixes.py -v
```

## Security Review

Passed CodeQL security analysis with **0 alerts**.

## Examples

### Creating an Event
```python
from app.time_utils import parse_local_time_to_utc
from datetime import date

# User enters date and time in UI
event_date = date(2024, 7, 15)  # July (summer)
show_time_str = "21:00"  # Israel local time

# Convert to UTC for storage
show_time_utc = parse_local_time_to_utc(event_date, show_time_str)
# Result: 2024-07-15 18:00:00+00:00 (21:00 - 3 hours DST)

# Store in database...
events.create_event(org_id=1, show_time=show_time_utc, ...)
```

### Displaying an Event
```python
from app.time_utils import utc_to_local_time_str

# Retrieve from database (returns UTC datetime)
event = events.get_event_by_id(org_id=1, event_id=123)
show_time_utc = event['show_time']  # 2024-07-15 18:00:00+00:00

# Convert to local time string for display
display_time = utc_to_local_time_str(show_time_utc)
# Result: "21:00"
```

### Editing an Event
```python
# Load event for editing
event = get_event_with_contacts(org_id=1, event_id=123)
show_time_utc = event['show_time']

# Display in edit form
show_time_str = utc_to_local_time_str(show_time_utc)  # "21:00"

# User saves without changes (still "21:00")
# Convert back to UTC
show_time_utc_new = parse_local_time_to_utc(event['event_date'], show_time_str)

# Result: EXACTLY the same as original (no drift!)
assert show_time_utc == show_time_utc_new
```

## Migration Notes

### For Existing Data
If you have existing events in the database with incorrect times:

1. **Identify affected events**: Look for events where the displayed time doesn't match what users expect
2. **Determine the correct local time**: Ask the event owner what time they intended
3. **Recalculate UTC time**: Use `parse_local_time_to_utc()` with the correct local time
4. **Update the database**: Run an UPDATE query with the corrected UTC times

Example repair script:
```python
from app.time_utils import parse_local_time_to_utc
from datetime import date

# Fix a specific event
event_date = date(2024, 7, 15)
correct_local_time = "21:00"  # What it should be
correct_utc = parse_local_time_to_utc(event_date, correct_local_time)

# Update database
events.update_event_fields(
    org_id=1, 
    event_id=123, 
    show_time=correct_utc
)
```

### Deployment
No special migration needed. The fix is backward compatible:
- Correctly stored times will continue to work
- Incorrectly stored times may need manual correction (see above)
- All new events will be stored correctly

## Files Changed

- **app/time_utils.py** (NEW) - Centralized timezone utilities
- **app/hoh_service.py** - Updated time conversions, removed manual offset
- **app/routers/ui.py** - Fixed display and input handling
- **app/repositories.py** - Updated to use timezone-aware datetimes
- **app/services/calendar_import_service.py** - Fixed calendar import times
- **app/flows/slots.py** - Replaced pytz with zoneinfo
- **tests/test_timezone_fixes.py** (NEW) - Comprehensive test suite
- **README.md** - Added timezone handling documentation

## Commit History

1. **Replace manual timezone offsets with centralized utilities** - Core implementation
2. **Add comprehensive timezone tests** - Test coverage
3. **Address code review feedback** - Refinements and improvements

## Future Maintenance

To maintain correct timezone handling:

1. **Always use `app/time_utils.py`** for any time conversions
2. **Never add manual hour offsets** (+2, -2, etc.)
3. **Test with summer AND winter dates** when making changes
4. **Run timezone tests** before merging changes
5. **Review the "Timezone Handling" section in README** for reference

## Success Metrics

✅ All 35 tests pass  
✅ No CodeQL security alerts  
✅ Code review issues addressed  
✅ Documentation updated  
✅ Round-trip conversions preserve exact times  
✅ Edit operations don't cause time drift  
✅ DST transitions handled automatically  
✅ WhatsApp messages show correct local times  

## Questions or Issues?

Refer to:
- `app/time_utils.py` - Implementation details
- `tests/test_timezone_fixes.py` - Usage examples and edge cases
- README.md - High-level overview and standards
- This document - Complete context and migration guide
