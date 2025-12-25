# Scheduler UI Enhancements - Implementation Guide

## Overview
This document describes the remaining UI enhancements needed to complete the scheduler improvements. The backend APIs are fully implemented and tested. The UI needs to be updated to use these APIs.

## Implemented Backend APIs

### 1. Send Now (Fixed)
- **Endpoint**: `POST /api/scheduler/jobs/{job_id}/send-now`
- **Response**: Includes `reason_code` for better error messages
- **Behavior**: Bypasses scheduler settings, weekend rules, and duplicate checks
- **Status**: ✅ Implemented & Tested

### 2. Heartbeat Status
- **Endpoint**: `GET /api/scheduler/heartbeat?org_id=1`
- **Response**: 
  ```json
  {
    "last_run_at": "2025-12-25T18:00:00Z",
    "last_run_status": "ok",
    "connectivity_status": "green",  // green, yellow, red
    "connectivity_message": "Scheduler is running normally",
    "minutes_since_last_run": 5,
    "last_run_due_found": 10,
    "last_run_sent": 8,
    "last_run_failed": 0,
    "last_run_blocked": 2
  }
  ```
- **Status**: ✅ Implemented

### 3. Update Job
- **Endpoint**: `PATCH /api/scheduler/jobs/{job_id}?org_id=1`
- **Body**: 
  ```json
  {
    "send_at": "2025-12-30T10:00:00Z",  // optional
    "status": "scheduled"                // optional
  }
  ```
- **Status**: ✅ Implemented

### 4. Delete All Jobs
- **Endpoint**: `DELETE /api/scheduler/jobs?org_id=1&confirm=true&message_type=INIT`
- **Status**: ✅ Implemented

## UI Enhancements Needed

### A. Add Heartbeat Indicator Badge

**Location**: Top of scheduler UI (above tabs)

**Implementation**:
```javascript
// Add this to the scheduler page
async function loadHeartbeat() {
  try {
    const response = await fetch('/api/scheduler/heartbeat?org_id=1');
    const heartbeat = await response.json();
    
    const badge = document.getElementById('heartbeatBadge');
    const statusClass = heartbeat.connectivity_status === 'green' ? 'bg-success' : 
                        heartbeat.connectivity_status === 'yellow' ? 'bg-warning' : 'bg-danger';
    
    badge.className = `badge ${statusClass}`;
    badge.textContent = `Cron: ${heartbeat.connectivity_message}`;
    badge.title = `Last run: ${heartbeat.minutes_since_last_run} minutes ago`;
  } catch (error) {
    console.error('Error loading heartbeat:', error);
  }
}

// Call every 30 seconds
setInterval(loadHeartbeat, 30000);
loadHeartbeat();  // Initial load
```

**HTML to add**:
```html
<div class="row mb-3">
  <div class="col">
    <span id="heartbeatBadge" class="badge bg-secondary">Loading...</span>
    <small class="text-muted ms-2">GitHub Cron Status</small>
  </div>
</div>
```

### B. Update Send Now Button Handler

**Current Issue**: Shows generic "Message skipped" error

**Fix**:
```javascript
async function sendNow(jobId) {
  if (!confirm('Send this message now?')) return;
  
  try {
    const response = await fetch(
      `/api/scheduler/jobs/${jobId}/send-now?org_id=${ORG_ID}`,
      { method: 'POST' }
    );
    
    const result = await response.json();
    
    if (result.success) {
      alert('Message sent successfully!');
      loadAllJobs();
    } else {
      // Show detailed error based on reason_code
      const errorMessages = {
        'MISSING_RECIPIENT': 'Cannot send: Recipient phone number missing',
        'SEND_FAILED': 'Send failed: Twilio error',
        'ALREADY_SENT': 'Message was already sent',
        'UNKNOWN': 'Unknown error occurred'
      };
      
      const errorMsg = errorMessages[result.reason_code] || result.message;
      alert(`Send failed: ${errorMsg}`);
      
      // Log full error for debugging
      console.error('Send now failed:', result);
    }
  } catch (error) {
    console.error('Error sending job:', error);
    alert('Error: ' + error.message);
  }
}
```

### C. Add Edit Send Date/Time Per Row

**UI Addition**: Add edit button next to each job

**HTML per row**:
```html
<td>
  <div id="send-at-display-${jobId}">${sendAtFormatted}</div>
  <div id="send-at-edit-${jobId}" class="d-none">
    <input type="datetime-local" 
           class="form-control form-control-sm" 
           id="send-at-input-${jobId}" 
           value="${sendAtLocal}">
    <div class="mt-1">
      <button class="btn btn-sm btn-success" 
              onclick="saveSendAt('${jobId}')">Save</button>
      <button class="btn btn-sm btn-secondary" 
              onclick="cancelEditSendAt('${jobId}')">Cancel</button>
    </div>
  </div>
  <button class="btn btn-sm btn-outline-secondary" 
          onclick="editSendAt('${jobId}')">📅 Edit</button>
</td>
```

**JavaScript**:
```javascript
function editSendAt(jobId) {
  document.getElementById(`send-at-display-${jobId}`).classList.add('d-none');
  document.getElementById(`send-at-edit-${jobId}`).classList.remove('d-none');
}

function cancelEditSendAt(jobId) {
  document.getElementById(`send-at-display-${jobId}`).classList.remove('d-none');
  document.getElementById(`send-at-edit-${jobId}`).classList.add('d-none');
}

async function saveSendAt(jobId) {
  const input = document.getElementById(`send-at-input-${jobId}`);
  const newSendAt = new Date(input.value).toISOString();
  
  try {
    const response = await fetch(
      `/api/scheduler/jobs/${jobId}?org_id=${ORG_ID}`,
      {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ send_at: newSendAt })
      }
    );
    
    if (response.ok) {
      alert('Send time updated successfully!');
      loadAllJobs();  // Reload to show updated time
    } else {
      const error = await response.json();
      alert('Failed to update: ' + error.detail);
    }
  } catch (error) {
    console.error('Error updating send time:', error);
    alert('Error: ' + error.message);
  }
}
```

### D. Add Edit Status Per Row

**UI Addition**: Add status dropdown next to each status badge

**HTML per row**:
```html
<td>
  <div id="status-display-${jobId}">
    <span class="badge bg-${badgeClass}">${status}</span>
  </div>
  <div id="status-edit-${jobId}" class="d-none">
    <select class="form-select form-select-sm" id="status-input-${jobId}">
      <option value="scheduled">Scheduled</option>
      <option value="paused">Paused</option>
      <option value="blocked">Blocked</option>
      <option value="sent">Sent</option>
      <option value="failed">Failed</option>
      <option value="skipped">Skipped</option>
    </select>
    <div class="mt-1">
      <button class="btn btn-sm btn-success" 
              onclick="saveStatus('${jobId}')">Save</button>
      <button class="btn btn-sm btn-secondary" 
              onclick="cancelEditStatus('${jobId}')">Cancel</button>
    </div>
  </div>
  <button class="btn btn-sm btn-outline-secondary" 
          onclick="editStatus('${jobId}')">✏️ Edit</button>
</td>
```

**JavaScript**: (Similar pattern to editSendAt above)

### E. Add Global Delete All Button

**Location**: Top of scheduler UI, next to "Fetch Future Events"

**HTML**:
```html
<button id="deleteAllBtn" class="btn btn-danger ms-2">
  🗑️ Delete All Jobs
</button>

<!-- Optional: Add per-tab delete buttons -->
<button class="btn btn-sm btn-outline-danger ms-2" 
        onclick="deleteAllOfType('INIT')">
  🗑️ Delete All INIT
</button>
```

**JavaScript**:
```javascript
async function deleteAllJobs(messageType = null) {
  const typeText = messageType ? ` ${messageType}` : '';
  
  if (!confirm(`⚠️ WARNING: This will delete ALL${typeText} scheduled jobs!\n\nThis action cannot be undone.\n\nAre you sure?`)) {
    return;
  }
  
  // Double confirmation for safety
  if (!confirm('Really delete? Type DELETE in the prompt to confirm.')) {
    return;
  }
  
  const deleteBtn = document.getElementById('deleteAllBtn');
  deleteBtn.disabled = true;
  deleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deleting...';
  
  try {
    const url = messageType 
      ? `/api/scheduler/jobs?org_id=${ORG_ID}&message_type=${messageType}&confirm=true`
      : `/api/scheduler/jobs?org_id=${ORG_ID}&confirm=true`;
    
    const response = await fetch(url, { method: 'DELETE' });
    
    if (!response.ok) {
      throw new Error('Delete failed');
    }
    
    const result = await response.json();
    
    alert(`✅ Deleted ${result.deleted_count} jobs successfully!`);
    loadAllJobs();  // Reload to show empty state
    
  } catch (error) {
    console.error('Error deleting jobs:', error);
    alert('❌ Error deleting jobs: ' + error.message);
  } finally {
    deleteBtn.disabled = false;
    deleteBtn.innerHTML = '🗑️ Delete All Jobs';
  }
}

document.getElementById('deleteAllBtn').addEventListener('click', () => deleteAllJobs());
```

## Testing Checklist

### Manual Testing Steps

1. **Test Send Now**:
   - [ ] Click "Send Now" on a scheduled job
   - [ ] Verify message is sent (check Twilio)
   - [ ] Verify status updates to "sent"
   - [ ] Try on Friday (should send immediately, not postpone)
   - [ ] Try when recipient missing (should show clear error)

2. **Test Heartbeat**:
   - [ ] Check badge shows green when scheduler recently ran
   - [ ] Wait 20+ minutes without scheduler run (badge should turn yellow/red)
   - [ ] Hover over badge to see last run details

3. **Test Edit Send Date**:
   - [ ] Click edit button on send date
   - [ ] Change to future date
   - [ ] Save and verify update
   - [ ] Try setting past date (should reject)

4. **Test Edit Status**:
   - [ ] Click edit button on status
   - [ ] Change from "scheduled" to "paused"
   - [ ] Save and verify update
   - [ ] Verify status badge color updates

5. **Test Delete All**:
   - [ ] Click "Delete All Jobs" button
   - [ ] Verify double confirmation
   - [ ] Confirm deletion
   - [ ] Verify all jobs removed
   - [ ] Verify empty state shows

6. **Test INIT Filtering**:
   - [ ] Create event with load_in_time
   - [ ] Click "Fetch Future Events"
   - [ ] Verify INIT tab shows NO job for that event
   - [ ] Verify TECH tab shows job for that event

## Database Migration

**IMPORTANT**: Run the migration before deploying:

```bash
# Run the heartbeat table migration
psql $DATABASE_URL < db/migrations/012_scheduler_heartbeat.sql
```

## Configuration

No environment variables need to be changed. All features work with existing configuration.

## Rollback Plan

If issues arise:
1. Revert to previous commit: `git revert 9d03724`
2. Old "Send Now" will work but without improvements
3. Heartbeat table can be dropped if needed: `DROP TABLE scheduler_heartbeat;`

## Summary

**Completed (Backend)**:
- ✅ Send now fix with detailed errors
- ✅ INIT filtering with load_in_time
- ✅ Heartbeat tracking
- ✅ Edit send_at and status APIs
- ✅ Delete all jobs API
- ✅ Comprehensive test coverage (8 tests)

**Remaining (Frontend)**:
- ⏳ Heartbeat badge UI
- ⏳ Enhanced send now error messages
- ⏳ Edit send date UI per row
- ⏳ Edit status UI per row
- ⏳ Delete all button with confirmation

**Estimated Time**: 2-3 hours to complete all UI enhancements with manual testing.
