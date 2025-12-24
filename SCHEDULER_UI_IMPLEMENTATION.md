# Scheduler UI Implementation Summary

## Overview
Added a new "Scheduler" UI page that provides a comprehensive interface for viewing and managing scheduled message delivery across the organization.

## Changes Made

### 1. New API Router (`app/routers/scheduler.py`)
Created a complete REST API for scheduler management with the following endpoints:

#### Endpoints:
- **GET `/api/scheduler/jobs`** - List scheduled messages with enriched data
  - Query params: `org_id`, `message_type`, `hide_sent`
  - Returns jobs with event details, contact info, recipient resolution, and status
  
- **POST `/api/scheduler/jobs/{job_id}/enable`** - Enable/disable individual job
  - Query params: `org_id`, `enabled`
  - Allows pausing/resuming specific scheduled messages
  
- **POST `/api/scheduler/jobs/{job_id}/send-now`** - Send a message immediately
  - Query params: `org_id`
  - Triggers immediate delivery bypassing scheduled time
  
- **GET `/api/scheduler/settings`** - Get scheduler settings for org
  - Returns current configuration including enable flags
  
- **PUT `/api/scheduler/settings`** - Update scheduler settings
  - Allows toggling global and per-message-type enables

#### Features:
- Real-time recipient resolution (same logic as scheduler service)
- Enriched job data with event, producer, technician, and employee info
- Status tracking and error handling
- Integration with existing SchedulerService for send-now functionality

### 2. Scheduler UI Page (`/ui/scheduler`)
Created a comprehensive UI with the following components:

#### Global Settings Panel
- Master toggle for global scheduler enable/disable
- Individual toggles for each message type (INIT, TECH, SHIFT)
- Settings persist in `scheduler_settings` table
- Real-time updates via API

#### Three Tabbed Views
Each tab displays messages for a specific type:

1. **INIT Messages Tab**
   - Initial contact messages sent ~28 days before event
   - Shows event details, producer, technician, and recipient

2. **TECH Reminders Tab**
   - Technical reminder messages sent ~2 days before event
   - Includes opening employee information
   - Shows technician as recipient

3. **SHIFT Reminders Tab**
   - Employee shift reminders sent ~1 day before shift
   - Shows employee name, shift time, and recipient
   - Different column layout optimized for shift data

#### Table Features
Each table includes:
- **Event Summary**: Event name, date, show time, load-in time
- **Producer Info**: Name and phone number
- **Technician Info**: Name and phone number (for non-SHIFT tabs)
- **Employee Info**: Name and shift time (for SHIFT tab only)
- **Recipient Preview**: Shows resolved recipient or "חסר" if missing
- **Send Time**: Scheduled delivery time with live countdown
- **Status Pill**: Color-coded status badge with attempt count
- **Actions**:
  - Enable/Disable toggle (⏸️/▶️)
  - "Send Now" button for immediate delivery

#### Additional Features
- **"Hide sent" checkbox** - Filter out completed messages per tab
- **Live countdowns** - Updates every second showing time until delivery
  - Format: "in Xd Yh" / "in Xh Ym" / "in Xm Ys" / "Overdue"
- **Warning highlights** - Rows with missing recipients highlighted in yellow
- **Status indicators** - Color-coded badges for each status:
  - Scheduled (blue), Sent (green), Failed (red), Blocked (yellow)
  - Retrying (info), Skipped (gray), Paused (gray)
- **Error messages** - Display last error message when available
- **Attempt tracking** - Show retry count for failed messages

### 3. Navigation Update
- Added "Scheduler" button to main navigation bar
- Styled as `btn-outline-primary` to match UI theme
- Accessible from all pages via header

### 4. Main App Integration (`app/main.py`)
- Imported scheduler router
- Registered router with FastAPI app
- Maintains compatibility with existing routes

## Technical Implementation

### Database Tables Used
- `scheduled_messages` - Job queue with status tracking
- `scheduler_settings` - Per-org configuration
- `events` - Event details and contact references
- `contacts` - Producer and technician information
- `employees` - Employee details for shift reminders
- `employee_shifts` - Shift timing and employee assignments

### Recipient Resolution Logic
The UI implements the same recipient resolution logic as the scheduler service:
- **INIT**: Technician (if assigned) → Producer (fallback)
- **TECH_REMINDER**: Technician (required)
- **SHIFT_REMINDER**: Assigned employee (required)

### Status Flow
1. `scheduled` - Job created, waiting for send time
2. `blocked` - Missing recipient, cannot send
3. `retrying` - Failed send, will retry
4. `sent` - Successfully delivered
5. `failed` - Max retries reached
6. `skipped` - Dedupe or disabled type
7. `paused` - Manually disabled

### Frontend Technology
- Vanilla JavaScript (no build process)
- Bootstrap 5 for UI components
- Live data updates via Fetch API
- Client-side countdown calculations

## Usage

### Accessing the UI
1. Navigate to `/ui/scheduler` in your browser
2. View scheduled messages organized by type in tabs
3. Use toggles to enable/disable message types globally
4. Filter sent messages using "Hide sent" checkbox per tab

### Managing Individual Messages
- **Enable/Disable**: Click ⏸️ or ▶️ button to pause/resume
- **Send Now**: Click "📤 Send Now" to deliver immediately
- **Monitor Status**: Watch status pills and countdown timers

### Configuring Scheduler
- Toggle **Global Scheduler** to enable/disable all messages
- Toggle individual message types (INIT, TECH, SHIFT) independently
- Changes are saved immediately and reflected across all jobs

## Testing Recommendations

1. **Verify Page Loads**: Navigate to `/ui/scheduler` and ensure no errors
2. **Check API Endpoints**: Test each API endpoint returns expected data
3. **Test Toggles**: Enable/disable settings and verify persistence
4. **Test Actions**: Try enable/disable and send-now on individual jobs
5. **Verify Countdowns**: Ensure countdown updates every second
6. **Check Filters**: Toggle "Hide sent" and verify filtering works
7. **Test Missing Recipients**: Verify "חסר" appears for blocked jobs

## Screenshots Needed
- [ ] Scheduler page with all three tabs
- [ ] INIT messages tab with sample data
- [ ] TECH reminders tab with sample data  
- [ ] SHIFT reminders tab with sample data
- [ ] Settings toggles in action
- [ ] Status badges and error messages
- [ ] Live countdown display
- [ ] Send now confirmation and result

## Future Enhancements (Not Implemented)
- Bulk operations (enable/disable multiple jobs)
- Advanced filtering (by date range, event, status)
- Message preview before sending
- Delivery history and analytics
- Customizable countdown refresh interval
- Export/download job list
- Real-time updates via WebSocket
