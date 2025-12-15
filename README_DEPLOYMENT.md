# 🚀 Twilio Status Tracking - Deployment Guide

## Quick Start (5 Minutes)

### Step 1: Set Environment Variable
In **Render Dashboard**:
1. Go to your service
2. Click "Environment" tab
3. Add this variable:
   ```
   PUBLIC_BASE_URL=https://your-app-name.onrender.com
   ```
4. Click "Save Changes"

### Step 1.5: Run the calendar import migration (one-time)
In Render shell or via `psql` locally, apply the calendar import schema:

```
psql $DATABASE_URL < db/migrations/002_calendar_import.sql
```

If the table is missing at runtime the app now fails fast with a clear error
message that includes the DB host/name, but running the command above ensures
deployments start cleanly.

### Step 2: Deploy
The code is already pushed to GitHub. Render will auto-deploy.

### Step 3: Test
1. Send a test WhatsApp message using the HOH Bot UI
2. Wait 10 seconds
3. Query the database:
   ```sql
   SELECT * FROM message_delivery_log 
   ORDER BY created_at DESC 
   LIMIT 5;
   ```
4. You should see rows with status: 'queued', 'sent', 'delivered'

## ✅ You're Done!

---

## 📋 What Changed

### 3 Files Modified
1. **app/twilio_client.py** - Added status_callback to all send functions
2. **app/repositories.py** - Added MessageDeliveryLogRepository class
3. **app/routers/webhook.py** - Added POST /twilio-status endpoint

### No Breaking Changes
- Existing functionality unchanged
- Messages still send if PUBLIC_BASE_URL is not set
- No schema migrations needed
- No Twilio Console configuration required

---

## 📖 Full Documentation

For complete details, see:
- **FINAL_SUMMARY.md** - Executive summary
- **TWILIO_STATUS_TRACKING.md** - Complete documentation
- **IMPLEMENTATION_SUMMARY.md** - Technical details

---

## 🔍 Verify It's Working

### Check 1: Endpoint Exists
Visit: `https://your-app.onrender.com/health`  
Expected: `{"ok": true}`

### Check 2: Message Sent
After sending a message, check `messages` table:
```sql
SELECT message_id, whatsapp_msg_sid, body, sent_at
FROM messages
WHERE direction = 'outgoing'
ORDER BY sent_at DESC
LIMIT 1;
```
Expected: Row with populated `whatsapp_msg_sid`

### Check 3: Status Logged
Check `message_delivery_log` table:
```sql
SELECT delivery_id, message_id, status, created_at
FROM message_delivery_log
ORDER BY created_at DESC
LIMIT 3;
```
Expected: Rows with status progression (queued → sent → delivered)

### Check 4: Logs
In Render logs, look for:
```
"Twilio status callback received"
"Delivery status logged successfully"
```

---

## ❓ Troubleshooting

### No rows in message_delivery_log?
- Verify PUBLIC_BASE_URL is set correctly (no trailing slash)
- Check Render logs for errors
- Visit /health endpoint to verify app is running

### "Message not found" warnings?
- This is normal for old messages or messages from other systems
- Only affects tracking, not message delivery

### Need help?
See **TWILIO_STATUS_TRACKING.md** for detailed troubleshooting guide.

---

## 📊 Useful Queries

### Latest status per message
```sql
SELECT DISTINCT ON (message_id) 
  message_id, status, created_at
FROM message_delivery_log
ORDER BY message_id, created_at DESC;
```

### Failed messages
```sql
SELECT m.body, mdl.error_code, mdl.error_message
FROM messages m
JOIN message_delivery_log mdl ON m.message_id = mdl.message_id
WHERE mdl.status = 'failed';
```

### Delivery rate (last 24 hours)
```sql
SELECT 
  status,
  COUNT(*) as count
FROM message_delivery_log
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY status;
```

---

**Status:** ✅ Ready for Production  
**Time to Deploy:** ~5 minutes  
**Risk:** Zero (no breaking changes)
