# Shift Organizer - מארגן משמרות

## Overview / סקירה כללית

The Shift Organizer is a comprehensive shift scheduling system for the HOH Bot platform. It automatically assigns technicians to event shifts while respecting work rules, rest requirements, and employee availability.

מערכת ניהול משמרות מתקדמת המשבצת טכנאים לאירועים תוך שמירה על חוקי עבודה, מנוחה וזמינות עובדים.

## Features / תכונות

### 1. Automatic Shift Generation / שיבוץ אוטומטי

- **Smart Slot Creation**: Automatically splits events longer than 12 hours into multiple slots
- **Hard Constraints Enforcement**:
  - Maximum 12-hour shifts
  - Minimum 10-hour rest between shifts
  - Night-to-morning rule: No morning shift (06:00-12:00) after working a night shift (22:00-06:00)
  - Employee availability conflicts
  
- **Fair Distribution**:
  - Prioritizes employees who didn't work the previous day
  - Balances weekend shift assignments (Friday 15:00 - Saturday 23:59)
  - Distributes total shift load evenly

### 2. Manual Override / שליטה ידנית

- View and edit all generated shift suggestions before saving
- Add or remove shift slots manually
- Lock shifts to prevent overwriting by future auto-generation
- Assign specific employees to specific slots

### 3. Availability Management / ניהול זמינות

- Employees can mark unavailability periods with reasons
- Monthly view of unavailability blocks
- API endpoints for creating/deleting unavailability

### 4. Transparency & Explainability / שקיפות והסברים

- Red highlighting for unfilled slots
- Tooltip/reason display for why employees were rejected
- Employee statistics showing total and weekend shift counts

## Database Schema / מבנה נתונים

### New Table: `employee_unavailability`

Tracks periods when employees are unavailable for shifts.

```sql
CREATE TABLE employee_unavailability (
    unavailability_id BIGSERIAL PRIMARY KEY,
    org_id            BIGINT NOT NULL,
    employee_id       BIGINT NOT NULL,
    start_at          TIMESTAMPTZ NOT NULL,
    end_at            TIMESTAMPTZ NOT NULL,
    note              TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Enhanced Table: `employee_shifts`

Added columns to support shift scheduling:

- `start_at`: Shift start time (for scheduling calculations)
- `end_at`: Shift end time (for rest period calculations)
- `is_locked`: When true, prevents auto-generation from overwriting
- `shift_type`: Optional categorization (setup/show/teardown)

## API Endpoints / נקודות קצה

### Shift Organizer

#### `GET /shift-organizer/month`

Get all events, shifts, and employees for a specific month.

**Query Parameters:**
- `org_id` (int): Organization ID
- `year` (int): Year (e.g., 2025)
- `month` (int): Month (1-12)

**Response:**
```json
{
  "events": [...],
  "shifts": [...],
  "employees": [...],
  "employee_stats": [...]
}
```

#### `POST /shift-organizer/generate`

Generate shift suggestions without saving to database.

**Request Body:**
```json
{
  "org_id": 1,
  "year": 2025,
  "month": 1
}
```

**Response:**
```json
{
  "slots": [
    {
      "event_id": 123,
      "start_at": "2025-01-15T18:00:00+02:00",
      "end_at": "2025-01-16T02:00:00+02:00",
      "suggested_employee_id": 5,
      "suggested_employee_name": "John Doe"
    }
  ],
  "explainability": {...},
  "employee_stats": {...}
}
```

#### `POST /shift-organizer/save`

Save shift assignments to database.

**Request Body:**
```json
{
  "org_id": 1,
  "year": 2025,
  "month": 1,
  "slots": [
    {
      "event_id": 123,
      "employee_id": 5,
      "start_at": "2025-01-15T18:00:00+02:00",
      "end_at": "2025-01-16T02:00:00+02:00",
      "is_locked": false,
      "shift_type": "show"
    }
  ]
}
```

### Availability

#### `GET /availability/month`

Get all unavailability blocks for a month.

**Query Parameters:**
- `org_id` (int)
- `year` (int)
- `month` (int)

#### `POST /availability`

Create an unavailability block.

**Request Body:**
```json
{
  "org_id": 1,
  "employee_id": 5,
  "start_at": "2025-01-15T10:00:00+02:00",
  "end_at": "2025-01-15T18:00:00+02:00",
  "note": "Doctor appointment"
}
```

#### `DELETE /availability/{unavailability_id}`

Delete an unavailability block.

**Query Parameters:**
- `org_id` (int)

## UI Usage / שימוש בממשק

### Accessing the Shift Organizer

1. Navigate to `/ui/shift-organizer` or click "Shift Organizer" in the navigation bar
2. The current month is displayed by default
3. Use "Previous Month" / "Next Month" buttons to navigate

### Generating Shifts

1. Click "Generate Shifts" button
2. The system will:
   - Create optimal shift slots for all events in the month
   - Suggest the best employee for each slot based on heuristics
   - Highlight any unfilled slots in red
3. Review the suggestions (nothing is saved yet!)

### Editing Shifts

- Change employee assignments using the dropdown menus
- Remove slots using the ✕ button
- View employee statistics at the top to ensure fair distribution

### Saving to Database

1. After reviewing and editing, click "Save to Database"
2. All shifts will be created/updated in the database
3. The main events view will reflect these assignments

## Work Rules / חוקי עבודה

### Hard Constraints (קשיח - אסור לפי חוק)

1. **Maximum Shift Duration**: 12 hours
   - Events longer than 12 hours are automatically split into multiple slots
   
2. **Minimum Rest Period**: 10 hours between shifts
   - An employee cannot be assigned to a shift that starts less than 10 hours after their previous shift ended
   
3. **Night-to-Morning Rule**: 
   - Night hours: 22:00 - 06:00
   - Morning hours: 06:00 - 12:00
   - If an employee worked any shift that touched night hours, they cannot work a morning shift the next day

### Soft Preferences (העדפה - משפיע על השיבוץ)

1. **Average Shift Length**: 8 hours (preferred)
   - The system tries to create 8-hour slots when possible
   - Shorter slots (e.g., 4 hours) are only created when necessary

2. **Weekend Fairness**: Weekend = Friday 15:00 → Saturday 23:59
   - The system tracks weekend shifts per employee per month
   - Prefers assigning employees with fewer weekend shifts

3. **Daily Rest**: 
   - Prefers not assigning employees who worked the previous day
   - Not a hard constraint, but improves work-life balance

## Configuration / הגדרות

Default settings are defined in `app/services/shift_generator.py`:

```python
DEFAULT_SHIFT_HOURS = 8
MAX_SHIFT_HOURS = 12
MIN_REST_HOURS = 10
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6
MORNING_START_HOUR = 6
MORNING_END_HOUR = 12
EVENT_BUFFER_HOURS = 5  # Hours after show_time
```

These can be made configurable via a settings UI in the future.

## Testing / בדיקות

Run the unit tests:

```bash
pytest tests/test_shift_generator.py -v
```

Tests cover:
- Event splitting for long events (>12h)
- Weekend shift detection
- Night shift detection
- Morning shift detection
- Night-to-morning rule enforcement
- 10-hour rest rule
- Availability conflict detection
- Yesterday work detection
- Weekend shift counting

## Technical Architecture / ארכיטקטורה טכנית

### Components

1. **Frontend**: JavaScript-based UI in `/ui/shift-organizer`
   - Fetches data from API endpoints
   - Renders events and slots dynamically
   - Handles generate and save operations

2. **API Layer**: FastAPI routers
   - `shift_organizer.py`: Main shift organizer endpoints
   - `availability.py`: Employee availability management

3. **Business Logic**: Shift generation engine
   - `services/shift_generator.py`: Core algorithm implementation
   - Constraint checking functions
   - Employee ranking heuristics

4. **Data Layer**: Repository pattern
   - `repositories.py`: Extended with new methods for:
     - `EmployeeUnavailabilityRepository`
     - Enhanced `EmployeeShiftRepository`

### Data Flow

```
UI (JS) → API Router → Service Layer → Repository → Database
         ←           ←                ←            ←
```

1. User clicks "Generate Shifts"
2. Frontend calls POST `/shift-organizer/generate`
3. Router gathers events, employees, existing shifts, unavailability
4. Service layer runs generation algorithm
5. Results returned to frontend (NOT saved to DB)
6. User reviews and edits
7. User clicks "Save"
8. Frontend calls POST `/shift-organizer/save`
9. Repository performs upserts/deletes
10. Database updated with final assignments

## Future Enhancements / שיפורים עתידיים

1. **Settings UI**: 
   - Configurable night/morning hours
   - Adjustable rest period requirements
   - Custom weekend definitions

2. **Employee Preferences**:
   - Preferred shift times
   - Maximum shifts per month
   - Preferred/blocked co-workers

3. **Conflict Resolution UI**:
   - Better visualization of why slots are unfilled
   - Suggestions for resolving conflicts
   - "Force assign" option with warnings

4. **Reporting**:
   - Monthly shift distribution reports
   - Overtime tracking
   - Fairness metrics visualization

5. **Notifications**:
   - Automatic notification to employees when assigned
   - Reminders for upcoming shifts
   - Availability reminder for next month

## Troubleshooting / פתרון בעיות

### Slots showing as unfilled (red background)

Check the tooltip for the reason:
- "No available employee meets requirements" - All employees are blocked by constraints
- "Less than 10h rest from previous shift" - All employees worked recently
- "Night→morning rule violation" - Trying to assign morning after night shift
- "Unavailable during this time" - Employee marked unavailable

**Solutions:**
- Adjust event timing
- Add more employees
- Override constraints by manually assigning (use caution)
- Remove unavailability blocks if entered in error

### Generate not suggesting any employees

- Ensure employees exist and are marked as active
- Check that events have valid `load_in_time` and `show_time`
- Verify date ranges are correct
- Check for excessive unavailability blocks

### Save failing

- Ensure all selected employees have valid IDs
- Check for database connection issues
- Verify `start_at` and `end_at` times are set for all slots

## Support / תמיכה

For issues or questions:
- Check the logs in the backend for detailed error messages
- Review constraint violations in the explainability data
- Contact the development team for feature requests
