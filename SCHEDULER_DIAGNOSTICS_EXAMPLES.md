# Scheduler Diagnostics - Usage Examples

## Example 1: Basic API Call

```bash
# Set your token
export SCHEDULER_RUN_TOKEN="your-secret-token-here"

# Call diagnostics endpoint
curl -H "Authorization: Bearer $SCHEDULER_RUN_TOKEN" \
     "https://your-app.onrender.com/internal/diagnostics/scheduler?org_id=1" \
     | jq .
```

## Example 2: CLI Usage (Local Development)

```bash
# With DATABASE_URL configured
export DATABASE_URL="postgresql://user:pass@localhost/hohbot"

# Run diagnostics
python -m app.diagnostics.scheduler --org-id 1

# Or without org_id for global view
python -m app.diagnostics.scheduler
```

## Example 3: Interpreting Results

### Scenario: Empty scheduled_messages table

**Response snippet:**
```json
{
  "summary": {
    "suspected_root_cause": "No scheduled jobs have been created (fetch button not used)",
    "confidence": 90,
    "key_evidence": [
      "scheduled_messages table is empty (0 rows)",
      "Future events available for fetch: 3"
    ]
  },
  "recommendations": [
    {
      "priority": "P1",
      "title": "Create scheduled jobs using fetch button",
      "description": "No scheduled jobs exist. Click 'Fetch future events' button in the scheduler UI.",
      "commands": ["POST /api/scheduler/fetch with org_id=1"]
    }
  ]
}
```

**Action:** Click the "Fetch future events" button in the UI, or call:
```bash
curl -X POST "https://your-app.onrender.com/api/scheduler/fetch?org_id=1"
```

### Scenario: All jobs are in the past

**Response snippet:**
```json
{
  "summary": {
    "suspected_root_cause": "All scheduled jobs are in the past (show_past=false filters them out)",
    "confidence": 85,
    "key_evidence": [
      "5 jobs exist but 0 are future",
      "Status distribution: {'sent': 3, 'scheduled': 2}"
    ]
  },
  "recommendations": [
    {
      "priority": "P2",
      "title": "Show past jobs in UI",
      "description": "Jobs exist but are hidden because they're in the past. Use show_past=true filter.",
      "commands": ["GET /api/scheduler/jobs?show_past=true"]
    }
  ]
}
```

**Action:** Add `?show_past=true` to the UI URL, or modify the UI filter.

### Scenario: Org ID mismatch

**Response snippet:**
```json
{
  "summary": {
    "suspected_root_cause": "Org ID mismatch (events exist but jobs don't)",
    "confidence": 75,
    "key_evidence": [
      "org_id 1 has 10 events but 0 scheduled messages",
      "org_id distribution in scheduled_messages: {2: 5, 3: 8}"
    ]
  },
  "recommendations": [
    {
      "priority": "P1",
      "title": "Check org_id scoping",
      "description": "org_id 1 has events but no scheduled messages",
      "commands": [
        "Run fetch for org_id=1",
        "Check if scheduler_job_builder filters by org_id correctly"
      ]
    }
  ]
}
```

**Action:** Verify the org_id used in the UI matches the org_id of your events, or run fetch for the correct org.

### Scenario: Database mismatch

**Response snippet:**
```json
{
  "checks": [
    {
      "name": "DB_FINGERPRINT",
      "status": "pass",
      "details": {
        "current_database": "production_db",
        "current_schema": "public",
        "server_addr": "db-prod.us-east-1.amazonaws.com",
        "db_timezone": "UTC"
      }
    }
  ]
}
```

**Action:** Compare these values with your DBeaver connection settings. If they differ, the app is connected to a different database than you're viewing in DBeaver.

## Example 4: Automating Diagnostics in CI/CD

```bash
#!/bin/bash
# health-check.sh

# Run diagnostics
response=$(curl -s -H "Authorization: Bearer $SCHEDULER_RUN_TOKEN" \
     "https://your-app.onrender.com/internal/diagnostics/scheduler?org_id=1")

# Extract confidence score
confidence=$(echo "$response" | jq -r '.summary.confidence')

# Alert if confidence is high (problem detected)
if [ "$confidence" -gt 75 ]; then
    root_cause=$(echo "$response" | jq -r '.summary.suspected_root_cause')
    echo "⚠️ Scheduler issue detected: $root_cause"
    echo "$response" | jq '.recommendations'
    exit 1
fi

echo "✅ Scheduler health check passed"
```

## Example 5: Debugging with jq

```bash
# Get just the summary
curl -H "Authorization: Bearer $TOKEN" "$URL/internal/diagnostics/scheduler" | jq .summary

# Get only failed checks
curl -H "Authorization: Bearer $TOKEN" "$URL/internal/diagnostics/scheduler" \
  | jq '.checks[] | select(.status == "fail")'

# Get P0 recommendations
curl -H "Authorization: Bearer $TOKEN" "$URL/internal/diagnostics/scheduler" \
  | jq '.recommendations[] | select(.priority == "P0")'

# Get data visibility details
curl -H "Authorization: Bearer $TOKEN" "$URL/internal/diagnostics/scheduler" \
  | jq '.checks[] | select(.name == "SCHEDULED_MESSAGES_DATA") | .details'
```

## Troubleshooting Common Errors

### Error: 401 Unauthorized
**Cause:** Token is invalid or missing  
**Fix:** Check that `SCHEDULER_RUN_TOKEN` environment variable matches the token you're using

### Error: 500 Internal Server Error (token not configured)
**Cause:** `SCHEDULER_RUN_TOKEN` is not set in the environment  
**Fix:** Set the environment variable in your deployment configuration

### Error: Connection refused (CLI)
**Cause:** `DATABASE_URL` is not set or database is not accessible  
**Fix:** Set `DATABASE_URL` and verify database connectivity

### CLI import error
**Cause:** Missing dependencies  
**Fix:** `pip install -r requirements.txt`
