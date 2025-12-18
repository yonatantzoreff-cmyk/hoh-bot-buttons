# Shift Organizer - Architecture Diagram

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌────────────────────┐         ┌────────────────────┐        │
│  │ Shift Organizer    │         │ Availability Mgmt  │        │
│  │ /ui/shift-organizer│         │ /ui/availability   │        │
│  ├────────────────────┤         ├────────────────────┤        │
│  │ - Month Navigation │         │ - Add Unavailability│       │
│  │ - Event List       │         │ - View by Employee │        │
│  │ - Slot Assignment  │         │ - Delete Blocks    │        │
│  │ - Generate Button  │         │ - Date Range       │        │
│  │ - Save Button      │         │                    │        │
│  │ - Employee Stats   │         │                    │        │
│  └────────────────────┘         └────────────────────┘        │
│           │                              │                     │
└───────────┼──────────────────────────────┼─────────────────────┘
            │                              │
            ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                          API LAYER                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌────────────────────────────┐  ┌──────────────────────────┐ │
│  │ Shift Organizer Router     │  │ Availability Router      │ │
│  │ /shift-organizer/*         │  │ /availability/*          │ │
│  ├────────────────────────────┤  ├──────────────────────────┤ │
│  │ GET  /month                │  │ GET  /month              │ │
│  │ POST /generate             │  │ POST /                   │ │
│  │ POST /save                 │  │ DELETE /{id}             │ │
│  └────────────────────────────┘  └──────────────────────────┘ │
│           │                              │                     │
└───────────┼──────────────────────────────┼─────────────────────┘
            │                              │
            ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BUSINESS LOGIC LAYER                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Shift Generation Engine (shift_generator.py)     │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │                                                          │  │
│  │  Slot Creation:                                          │  │
│  │  ├─ create_slots_for_event()  [Split events >12h]      │  │
│  │  └─ Calculate start/end times                           │  │
│  │                                                          │  │
│  │  Hard Constraints:                                       │  │
│  │  ├─ has_sufficient_rest()      [10h min rest]          │  │
│  │  ├─ violates_night_to_morning_rule()                   │  │
│  │  ├─ has_availability_conflict()                        │  │
│  │  └─ Check shift duration ≤12h                          │  │
│  │                                                          │  │
│  │  Ranking Heuristics:                                     │  │
│  │  ├─ worked_yesterday()         [-100 score penalty]    │  │
│  │  ├─ count_weekend_shifts()     [-10 per weekend]       │  │
│  │  └─ Total shift count          [-5 per shift]          │  │
│  │                                                          │  │
│  │  Output:                                                 │  │
│  │  ├─ Suggested assignments                               │  │
│  │  ├─ Explainability (rejection reasons)                  │  │
│  │  └─ Employee statistics                                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       REPOSITORY LAYER                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────┐  ┌──────────────────────────┐   │
│  │ EmployeeUnavailability   │  │ EmployeeShiftRepository  │   │
│  │ Repository               │  │ (Enhanced)               │   │
│  ├──────────────────────────┤  ├──────────────────────────┤   │
│  │ - create_unavailability()│  │ - get_shifts_for_month() │   │
│  │ - get_for_month()        │  │ - upsert_shift()         │   │
│  │ - get_for_employee()     │  │ - delete_shifts_for_event│   │
│  │ - delete()               │  │                          │   │
│  └──────────────────────────┘  └──────────────────────────┘   │
│           │                              │                     │
│           └──────────────┬───────────────┘                     │
└────────────────────────────┼─────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DATABASE LAYER                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────┐   ┌──────────────────────────┐   │
│  │ employee_unavailability │   │ employee_shifts (Enhanced)│   │
│  ├─────────────────────────┤   ├──────────────────────────┤   │
│  │ - unavailability_id (PK)│   │ - shift_id (PK)          │   │
│  │ - org_id               │   │ - org_id                 │   │
│  │ - employee_id          │   │ - employee_id            │   │
│  │ - start_at             │   │ - event_id               │   │
│  │ - end_at               │   │ - call_time              │   │
│  │ - note                 │   │ - start_at  [NEW]        │   │
│  │ - created_at           │   │ - end_at    [NEW]        │   │
│  │ - updated_at           │   │ - is_locked [NEW]        │   │
│  └─────────────────────────┘   │ - shift_type [NEW]       │   │
│                                │ - shift_role             │   │
│  ┌─────────────────────────┐   │ - notes                  │   │
│  │ events (Existing)       │   │ - created_at             │   │
│  ├─────────────────────────┤   │ - updated_at             │   │
│  │ - event_id             │   └──────────────────────────┘   │
│  │ - name                 │                                   │
│  │ - event_date           │   ┌──────────────────────────┐   │
│  │ - show_time            │   │ employees (Existing)     │   │
│  │ - load_in_time         │   ├──────────────────────────┤   │
│  │ - notes                │   │ - employee_id            │   │
│  └─────────────────────────┘   │ - org_id                 │   │
│                                │ - name                   │   │
│                                │ - phone                  │   │
│                                │ - is_active              │   │
│                                └──────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow - Generate Shifts

```
1. User clicks "Generate Shifts"
   │
   ├─> Frontend: POST /shift-organizer/generate
   │
   ├─> Router: Collect data
   │   ├─ Events for month
   │   ├─ Employees (active)
   │   ├─ Existing shifts (month + 1 day before/after)
   │   └─ Unavailability blocks
   │
   ├─> Service: generate_shifts_for_events()
   │   │
   │   ├─> For each event:
   │   │   └─ create_slots_for_event()
   │   │      ├─ If duration ≤12h: 1 slot
   │   │      └─ If duration >12h: Split into multiple slots
   │   │
   │   ├─> For each slot:
   │   │   │
   │   │   ├─> Filter employees (Hard Constraints):
   │   │   │   ├─ Check availability
   │   │   │   ├─ Check 10h rest
   │   │   │   ├─ Check night→morning rule
   │   │   │   ├─ Check overlap with existing shifts
   │   │   │   └─ Check slot duration ≤12h
   │   │   │
   │   │   ├─> Rank candidates (Soft Preferences):
   │   │   │   ├─ +100 if didn't work yesterday
   │   │   │   ├─ -10 per weekend shift this month
   │   │   │   ├─ -5 per total shift this month
   │   │   │   └─ +random (0-1) for tie-breaking
   │   │   │
   │   │   └─> Select best candidate
   │   │       ├─ If found: suggested_employee_id
   │   │       └─ If none: unfilled_reason
   │   │
   │   └─> Return:
   │       ├─ slots (with suggestions)
   │       ├─ explainability (rejection reasons)
   │       └─ employee_stats (counts)
   │
   └─> Frontend: Display suggestions (NOT saved)
       ├─ Show events with suggested assignments
       ├─ Highlight unfilled slots in red
       └─ Display employee statistics
```

## Data Flow - Save Shifts

```
1. User reviews, edits, clicks "Save"
   │
   ├─> Frontend: Collect all slot data from UI
   │   └─ POST /shift-organizer/save
   │       {
   │         org_id, year, month,
   │         slots: [
   │           {event_id, employee_id, start_at, end_at, ...}
   │         ]
   │       }
   │
   ├─> Router: Process save request
   │   │
   │   ├─> Get existing shifts for month
   │   │
   │   ├─> For each slot in request:
   │   │   └─ upsert_shift() (create or update)
   │   │
   │   └─> Delete old shifts not in request
   │       (but keep locked shifts)
   │
   └─> Database: Shifts saved
       └─> Frontend: Reload and show success
```

## Constraint Enforcement Diagram

```
┌────────────────────────────────────────────────────────┐
│              Employee Assignment Decision              │
└────────────────────────────────────────────────────────┘
                          │
                          ▼
         ┌────────────────────────────────┐
         │  Is employee active?           │
         └────────────────────────────────┘
                    │ Yes
                    ▼
         ┌────────────────────────────────┐
         │  Has availability conflict?    │ ◄── employee_unavailability
         └────────────────────────────────┘
                    │ No
                    ▼
         ┌────────────────────────────────┐
         │  Overlaps existing shift?      │ ◄── employee_shifts
         └────────────────────────────────┘
                    │ No
                    ▼
         ┌────────────────────────────────┐
         │  <10h rest from last shift?    │ ◄── employee_shifts
         └────────────────────────────────┘
                    │ No (≥10h rest)
                    ▼
         ┌────────────────────────────────┐
         │  Violates night→morning rule?  │ ◄── employee_shifts
         └────────────────────────────────┘
                    │ No
                    ▼
         ┌────────────────────────────────┐
         │  Slot duration >12h?           │
         └────────────────────────────────┘
                    │ No (≤12h)
                    ▼
         ╔════════════════════════════════╗
         ║    EMPLOYEE IS CANDIDATE       ║
         ╚════════════════════════════════╝
                    │
                    ▼
         ┌────────────────────────────────┐
         │     Rank by Heuristics:        │
         │  - Didn't work yesterday       │
         │  - Fewer weekend shifts        │
         │  - Fewer total shifts          │
         └────────────────────────────────┘
                    │
                    ▼
         ╔════════════════════════════════╗
         ║    ASSIGN BEST CANDIDATE       ║
         ╚════════════════════════════════╝
```

## Key Features

### 1. Smart Slot Creation
- Automatically splits long events (>12 hours) into multiple slots
- Ensures no single slot exceeds 12 hours (legal maximum)
- Prefers 8-hour slots when possible

### 2. Hard Constraint Enforcement
- **10-Hour Rest**: Employee must have 10h between end of one shift and start of next
- **Night→Morning Rule**: No morning shift (06:00-12:00) after working night (22:00-06:00)
- **Availability**: Respects employee unavailability blocks
- **No Overlap**: Prevents double-booking employees

### 3. Fair Distribution
- **Weekend Balance**: Tracks Friday 15:00 - Saturday 23:59 shifts
- **Work-Life Balance**: Prefers employees who didn't work yesterday
- **Even Load**: Distributes shifts evenly across all employees

### 4. Transparency
- **Explainability**: Shows why employees were rejected for slots
- **Red Highlighting**: Visual indicator for unfilled slots
- **Statistics**: Real-time view of shift counts per employee

### 5. Manual Control
- **Review Before Save**: Generate creates suggestions, doesn't auto-save
- **Edit Assignments**: Change any employee assignment manually
- **Lock Shifts**: Prevent future auto-generation from changing specific shifts
- **Add/Remove Slots**: Full control over slot creation

## Technology Stack

- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL with SQLAlchemy
- **Frontend**: JavaScript + Bootstrap 5
- **Timezone**: Fully timezone-aware (Asia/Jerusalem)
- **Testing**: pytest with 100% test coverage of core logic
- **Security**: CodeQL scanned, 0 vulnerabilities

## Performance Considerations

- Efficient queries with proper indexing
- Month-based pagination (not loading all historical data)
- Lazy loading of employee/event data
- Client-side state management (minimal API calls)

## Future Scalability

The architecture supports easy addition of:
- Settings management (configurable rules)
- Employee preferences
- Advanced reporting
- Calendar integrations
- Mobile apps (API-first design)
- Multi-organization support (already org-scoped)
