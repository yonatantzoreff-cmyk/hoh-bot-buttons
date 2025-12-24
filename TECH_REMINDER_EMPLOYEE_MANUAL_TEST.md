# Technical Reminder with Opening Employee - Manual Testing Guide

## Overview
This feature allows sending a WhatsApp reminder to the technical contact of an event, including:
- Load-in time
- Show time
- Opening employee details (earliest arriving employee)

## Prerequisites

### 1. Set Environment Variable
You must set the Twilio Content SID for the new template:

```bash
CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Get the SID from Twilio:**
1. Log into Twilio Console
2. Navigate to: Messaging > Content Editor
3. Find template: `hoh_tech_reminder_employee_text_he_v1`
4. Copy the Content SID (starts with `HX`)

### 2. Database Setup
Ensure your database has:
- An event with `technical_contact_id` and valid technical phone
- At least one employee shift assigned to the event with `call_time` set

## Manual Test Steps

### Step 1: Create Test Data (if needed)

```sql
-- Example: Verify event has technical contact and shifts
SELECT 
    e.event_id,
    e.name,
    e.technical_contact_id,
    c.name as tech_name,
    c.phone as tech_phone,
    e.load_in_time,
    e.show_time,
    COUNT(s.shift_id) as shift_count
FROM events e
LEFT JOIN contacts c ON c.contact_id = e.technical_contact_id
LEFT JOIN employee_shifts s ON s.event_id = e.event_id
WHERE e.event_id = <YOUR_EVENT_ID>
GROUP BY e.event_id, c.name, c.phone;

-- Verify shifts have call_time
SELECT 
    s.shift_id,
    emp.name as employee_name,
    emp.phone as employee_phone,
    s.call_time
FROM employee_shifts s
JOIN employees emp ON emp.employee_id = s.employee_id
WHERE s.event_id = <YOUR_EVENT_ID>
ORDER BY s.call_time;
```

### Step 2: Navigate to Events Page
1. Start the application:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
2. Open browser: `http://localhost:8000/ui/events`
3. Find an event that has:
   - ✅ Technical contact with phone number
   - ✅ At least one employee shift with call_time

### Step 3: Send Reminder
1. Locate the "שלח תזכורת" (Send Reminder) button next to the technical contact
   - The button only appears if technical_contact_id exists
2. Click the button
3. Confirm in the popup dialog
4. Should redirect back to events page

### Step 4: Verify WhatsApp Message
Check the technical contact's WhatsApp for a message like:

```
היי David 👋
תזכורת: מחר "Concert Name" בתאריך 25/12/2025.
כניסה להקמות: 10:00 | תחילת מופע: 20:00.
העובד/ת שפותח/ת איתך: Sarah (+972509876543).
אם יש שינוי/בעיה — תעדכן כאן.
```

### Step 5: Verify Logs
Check application logs for:
```
INFO Sending tech reminder for event <ID> to whatsapp:+972..., opening employee: <NAME>
INFO Tech reminder sent successfully for event <ID>, SID: SM...
```

## Error Cases to Test

### Test 1: Missing Environment Variable
1. Unset `CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT`
2. Try to send reminder
3. **Expected**: Error page with message about missing env var

### Test 2: Event Without Technical Contact
1. Find an event with no technical_contact_id
2. **Expected**: Button should not appear in UI

### Test 3: Event Without Shifts
1. Find an event with technical contact but no employee shifts
2. Click "שלח תזכורת"
3. **Expected**: Error page: "No employees assigned to this event"

### Test 4: Event Without Call Times
1. Find an event with shifts but all shifts have `call_time = NULL`
2. Click "שלח תזכורת"
3. **Expected**: Error page: "Cannot determine opening employee"

## Expected Behavior

### Success Scenario
- ✅ Confirmation dialog appears
- ✅ Redirects to `/ui/events`
- ✅ WhatsApp message delivered to technical contact
- ✅ Message includes correct event details
- ✅ Opening employee is the one with earliest call_time
- ✅ Only first names used (David, not David Cohen)
- ✅ Employee phone in E.164 format (+972...)

### Error Scenarios
- ✅ Clear Hebrew/English error messages
- ✅ "Back to events" button in error pages
- ✅ Logs contain helpful debugging information

## Template Variables Mapping

The template uses 7 variables:

| Variable | Description | Example | Format |
|----------|-------------|---------|--------|
| `{{1}}` | Technical contact first name | David | First word only |
| `{{2}}` | Event name | Concert 2025 | Full name |
| `{{3}}` | Event date | 25/12/2025 | DD/MM/YYYY |
| `{{4}}` | Load-in time | 10:00 | HH:MM (Israel time) |
| `{{5}}` | Show time | 20:00 | HH:MM (Israel time) |
| `{{6}}` | Opening employee first name | Sarah | First word only |
| `{{7}}` | Opening employee phone | +972509876543 | E.164 format |

## Troubleshooting

### Issue: Button doesn't appear
**Solution**: Event must have `technical_contact_id` set. Add a technical contact to the event.

### Issue: "Cannot determine opening employee"
**Solution**: At least one shift must have a valid `call_time`. Set call_time on shifts.

### Issue: "Invalid phone number"
**Solution**: Technical contact phone must be valid Israeli format (050..., 052..., etc.)

### Issue: Message not received
**Checks**:
1. Verify Twilio Content SID is correct
2. Check technical contact phone is in E.164 format in DB
3. Verify Twilio account has credits
4. Check Twilio logs for delivery status

## Code Review Checklist

- [x] Template JSON file created with correct structure
- [x] Credentials updated with new env var
- [x] Twilio client guard prevents list/tuple variables
- [x] Backend logic finds earliest employee correctly
- [x] Phone normalization to E.164 and whatsapp: prefix
- [x] First names extracted correctly
- [x] UI button only shows when technical contact exists
- [x] Error handling covers all edge cases
- [x] Tests pass for all scenarios
- [x] No backward compatibility issues

## Security Notes

- ✅ No hardcoded SIDs - uses environment variables
- ✅ Phone numbers normalized before sending
- ✅ Input validation on all parameters
- ✅ Clear error messages without exposing sensitive data
- ✅ Event ID validation to prevent unauthorized sends
