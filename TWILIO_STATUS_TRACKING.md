# Twilio Message Delivery Status Tracking

This document describes the Twilio message delivery status tracking implementation for the HOH Bot project.

## Overview

The HOH Bot now tracks the delivery status of all WhatsApp messages sent via Twilio. When a message is sent, Twilio will send status callbacks to our webhook endpoint as the message progresses through different stages (queued, sent, delivered, failed, etc.).

## Architecture

### End-to-End Flow

1. **Message Sending**: When the app sends a WhatsApp message via Twilio:
   - The message is sent using one of the functions in `twilio_client.py`
   - A `status_callback` URL is included in the API call (if `PUBLIC_BASE_URL` is configured)
   - The message is saved in the `messages` table with `whatsapp_msg_sid`

2. **Twilio Callbacks**: As the message status changes, Twilio sends POST requests to:
   - `https://<YOUR-DOMAIN>/twilio-status`
   - Each request contains: `MessageSid`, `MessageStatus`, `ErrorCode`, `ErrorMessage`, etc.

3. **Status Processing**: Our webhook endpoint (`/twilio-status`):
   - Receives the form-encoded callback from Twilio
   - Looks up the message by `whatsapp_msg_sid`
   - Creates a new row in `message_delivery_log` table
   - Returns 200 OK to Twilio to acknowledge receipt

## Database Schema

### `messages` Table
Already exists. Key columns:
- `message_id` (PK)
- `org_id`
- `whatsapp_msg_sid` - Twilio Message SID for tracking
- `direction` - 'outgoing' or 'incoming'
- `body`
- `sent_at`, `received_at`, `created_at`

### `message_delivery_log` Table
Already exists. Columns:
- `delivery_id` (PK)
- `org_id` - References orgs(org_id)
- `message_id` - References messages(message_id)
- `status` - 'queued', 'sent', 'delivered', 'failed', etc.
- `error_code` - Twilio error code (if any)
- `error_message` - Twilio error message (if any)
- `provider` - 'twilio' (default)
- `provider_payload` - Full JSON payload from Twilio
- `created_at` - Timestamp of the status update

## Code Changes

### 1. `app/twilio_client.py`

Added support for Twilio status callbacks:

```python
# New environment variable
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

# Updated functions to include status_callback:
# - send_text()
# - send_content_message()
# - send_confirmation_message()

# Each function now adds:
if PUBLIC_BASE_URL:
    payload["status_callback"] = f"{PUBLIC_BASE_URL}/twilio-status"
```

### 2. `app/repositories.py`

Added `MessageDeliveryLogRepository` class:

```python
class MessageDeliveryLogRepository:
    def create_delivery_log(
        self,
        org_id: int,
        message_id: int,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        provider: str = "twilio",
        provider_payload: Optional[dict | str] = None,
    ) -> int:
        """Insert a new delivery log entry."""
        
    def get_message_by_whatsapp_sid(self, whatsapp_msg_sid: str):
        """Find a message by its Twilio WhatsApp Message SID."""
```

### 3. `app/routers/webhook.py`

Added `/twilio-status` webhook endpoint:

```python
@router.post("/twilio-status")
async def twilio_status_callback(request: Request):
    """
    Twilio Status Callback webhook for message delivery tracking.
    Handles: queued, sent, delivered, failed, undelivered, etc.
    """
```

## Configuration

### Required Environment Variables

Set these in your Render environment (or `.env` file for local development):

#### Required (Already Exist)
- `TWILIO_ACCOUNT_SID` - Your Twilio Account SID
- `TWILIO_AUTH_TOKEN` - Your Twilio Auth Token
- `TWILIO_MESSAGING_SERVICE_SID` - Your Twilio Messaging Service SID
- `DATABASE_URL` - PostgreSQL connection string

#### New (For Status Tracking)
- `PUBLIC_BASE_URL` - Your app's public URL (e.g., `https://your-app.onrender.com`)
  - **Required** for status callbacks to work
  - If not set, messages will still send but without status tracking

### Render Configuration

1. Go to your Render dashboard
2. Select your service
3. Go to "Environment" tab
4. Add: `PUBLIC_BASE_URL=https://your-app-name.onrender.com`
5. Click "Save Changes"

## Message Status Values

Twilio sends the following status values (from their API):

- `queued` - Message queued by Twilio
- `sent` - Message sent to the carrier
- `delivered` - Message delivered to recipient's device
- `undelivered` - Message failed to deliver
- `failed` - Message failed permanently
- `read` - Message was read (if supported)

See: https://www.twilio.com/docs/sms/api/message-resource#message-status-values

## Testing

### Manual Testing Checklist

1. **Setup**
   - [ ] Deploy the updated code to Render
   - [ ] Set `PUBLIC_BASE_URL` environment variable in Render
   - [ ] Restart the service

2. **Send a Test Message**
   - [ ] Use the UI to send a WhatsApp message to a test number
   - [ ] Check the `messages` table - verify the message has a `whatsapp_msg_sid`
   - [ ] Wait a few seconds for Twilio callbacks

3. **Verify Status Tracking**
   - [ ] Query `message_delivery_log` table:
     ```sql
     SELECT 
       mdl.delivery_id,
       mdl.message_id,
       mdl.status,
       mdl.error_code,
       mdl.error_message,
       mdl.created_at,
       m.whatsapp_msg_sid,
       m.body
     FROM message_delivery_log mdl
     JOIN messages m ON mdl.message_id = m.message_id
     ORDER BY mdl.created_at DESC
     LIMIT 10;
     ```
   - [ ] You should see rows with status like 'queued', 'sent', 'delivered'
   - [ ] Check that `provider_payload` contains the full Twilio callback data

4. **Check Logs**
   - [ ] View Render logs for lines like:
     - `"Twilio status callback received"`
     - `"Delivery status logged successfully"`
   - [ ] Verify no errors in the logs

5. **Test Error Cases**
   - [ ] Send a message to an invalid number (e.g., +1234567890)
   - [ ] Check `message_delivery_log` for status='failed' with error_code and error_message

### Local Testing

For local development, you can use ngrok to expose your local server:

```bash
# Terminal 1: Start your app
uvicorn app.main:app --reload --port 8000

# Terminal 2: Start ngrok
ngrok http 8000

# Set PUBLIC_BASE_URL to your ngrok URL
export PUBLIC_BASE_URL=https://abc123.ngrok.io

# Restart your app with the new env var
```

## Troubleshooting

### No status updates in `message_delivery_log`

**Possible causes:**
1. `PUBLIC_BASE_URL` not set or incorrect
   - Check: `echo $PUBLIC_BASE_URL` in Render logs
   - Fix: Set in Render Environment settings

2. Webhook endpoint not accessible
   - Check: Visit `https://your-app.onrender.com/health` - should return `{"ok": true}`
   - Check: Render logs for any startup errors

3. Messages missing `whatsapp_msg_sid`
   - Check: Query `messages` table, verify `whatsapp_msg_sid` column is populated
   - Fix: Ensure Twilio API calls are successful and storing the SID

### Duplicate status entries

This is **expected behavior**. Twilio may send multiple callbacks for the same message as its status progresses:
- First: `queued`
- Then: `sent`
- Finally: `delivered`

Each callback creates a new row in `message_delivery_log`, providing a complete status history.

### Error: "Message not found for MessageSid"

This is logged when Twilio sends a callback for a message we don't have in our database. Possible reasons:
- The message was sent before this feature was deployed
- The message was sent from a different system using the same Twilio account
- The `whatsapp_msg_sid` wasn't saved correctly

**Action**: This is informational only; the endpoint returns 200 OK to Twilio.

## Querying Delivery Status

### Get latest status for a message
```sql
SELECT *
FROM message_delivery_log
WHERE message_id = :message_id
ORDER BY created_at DESC
LIMIT 1;
```

### Get all messages with their latest status
```sql
WITH latest_status AS (
  SELECT DISTINCT ON (message_id) 
    message_id, status, created_at
  FROM message_delivery_log
  ORDER BY message_id, created_at DESC
)
SELECT 
  m.message_id,
  m.body,
  m.whatsapp_msg_sid,
  m.sent_at,
  ls.status as delivery_status,
  ls.created_at as status_updated_at
FROM messages m
LEFT JOIN latest_status ls ON m.message_id = ls.message_id
WHERE m.direction = 'outgoing'
ORDER BY m.sent_at DESC;
```

### Get failed messages
```sql
SELECT 
  m.message_id,
  m.body,
  m.sent_at,
  mdl.error_code,
  mdl.error_message,
  mdl.provider_payload
FROM messages m
JOIN message_delivery_log mdl ON m.message_id = mdl.message_id
WHERE mdl.status = 'failed'
ORDER BY mdl.created_at DESC;
```

## Future Enhancements (Optional)

The current implementation provides complete status tracking. Optional improvements:

1. **Add `delivery_status` column to `messages` table**
   - Store the latest status directly on the message row
   - Update it when new callbacks arrive
   - Easier to query current status

2. **Dashboard/UI for delivery status**
   - Show delivery status next to each sent message
   - Filter messages by status
   - Alert on failed messages

3. **Retry logic for failed messages**
   - Automatically retry messages that fail
   - Configurable retry limits and delays

4. **Analytics and reporting**
   - Delivery rate metrics
   - Average delivery time
   - Error rate tracking

## Security Considerations

- The `/twilio-status` endpoint is **public** (no authentication)
- This is standard for webhooks - Twilio needs to POST to it
- The endpoint validates required fields and returns appropriate status codes
- Consider adding Twilio signature validation in production (optional)

## Support

If you encounter issues:
1. Check Render logs for error messages
2. Verify environment variables are set correctly
3. Test the `/health` endpoint to ensure the app is running
4. Review this document's troubleshooting section
5. Check Twilio's webhook logs in the Twilio Console

---

**Last Updated**: 2025-12-14  
**Version**: 1.0
