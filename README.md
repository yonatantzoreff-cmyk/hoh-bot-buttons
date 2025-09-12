# HOH BOT — Buttons MVP (Twilio + Google Sheets)

> שלוש הוכחות יכולת: (1) שליפת נתונים מהשיטס, (2) שליחה למספר וואטסאפ, (3) קבלת המידע והכנסה לשדה המתאים — עם **כפתורי WhatsApp** (Quick Reply + List Picker).

## ארכיטקטורה קצרה
- **FastAPI** Webhook שמדבר עם Twilio.
- **Twilio Content Templates** לכפתורי Quick Reply ו-List Picker.
- **Google Sheets (gspread)** לעבודה עם הקבצים `HOH_Events_template` ו-`HOH_Messages_template`.
- **State מינימלי** דרך *ButtonPayload* (JSON קטן עד 200 תווים) שמחזיר טוויליו בוובהוק.

---

## התקנה מקומית
1. צרו וירטואלי והתקינו תלויות:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. העתיקו `.env.example` ל-`.env` ומלאו פרטי Twilio + Google.
   - `TWILIO_MESSAGING_SERVICE_SID` (מומלץ) **או** `TWILIO_WHATSAPP_FROM` בפורמט `whatsapp:+1...`
   - `CONTENT_SID_*` שתקבלו אחרי יצירת/אישור טמפלייטים בקונסול.

3. הריצו לוקאלית:
   ```bash
   make run
   ```
   הוובהוק יהיה ב-`http://localhost:8000/whatsapp-webhook`

4. לפיתוח מול טוויליו — חשפו את השרת ל-URL ציבורי (ngrok/Cloudflared) ושימו את ה-URL בקונפיגורציה של ה-Sender.

---

## חיבור ל-Google Sheets
- ודאו שיש Service Account עם גישה לעריכת ה-Spreadsheet.
- אפשר `GOOGLE_CREDENTIALS_FILE=credentials.json` **או** `GOOGLE_CREDENTIALS_B64=...`.
- השמות: `SHEET_EVENTS_NAME=HOH_Events_template`, `SHEET_MESSAGES_NAME=HOH_Messages_template`.
- דרישות מינימום לכותרות (שורה ראשונה):
  - **Events**: `event_id`, `event_name`, `event_date`, `supplier_name`, `supplier_phone`, `load_in_time`, `status`, `follow_up_due_at`
  - **Messages**: `timestamp`, `direction`, `event_id`, `to`, `from`, `body`, `button_text`, `button_payload`, `raw`

> הקוד מנסה לאתר עמודות לפי שמות קרובים; אם חסר — עדכנו את כותרות הדפים.

---

## טמפלייטים בטוויליו (Content Templates)

נשתמש בשני סוגים:
- **Quick Reply** — ל*הודעת פתיחה* ול*אישור סופי* (ניתן גם לשלוח בתוך חלון 24ש׳ ללא אישור).
- **List Picker** — רק *בתוך חלון 24ש׳* לצמצום לטווחי זמן/בחירה מבין עד 10 משבצות.

### 1) הודעת פתיחה עם כפתורים (Quick Reply)
**שם מומלץ:** `hoh_init_qr_he`  
**שפה:** Hebrew  
**Content type:** `twilio/quick-reply`  
**Body:**  
```
היי {{1}}, תגיע בשעה כך וכך בתאריך {{2}} למופע {{3}}.
בחר/י אחת מהאפשרויות:
```
**Buttons (QUICK_REPLY)** — עד 3:
- title: `בחירת שעה` ; id: `{"action":"choose_time_range","event_id":"{{4}}","range":"noon"}`
- title: `אני עוד לא יודע` ; id: `{"action":"not_sure","event_id":"{{4}}"}`
- title: `אני לא איש הקשר` ; id: `{"action":"not_contact","event_id":"{{4}}"}'

> שולחים עם `CONTENT_SID_INIT_QR` והמשתנים:  
> `{"1": "<שם>", "2": "<תאריך>", "3": "<שם המופע>", "4": "<event_id>"}`

### 2) בחירת משבצת זמן (List Picker)
**שם:** `hoh_slot_list_he`  
**סוג:** `twilio/list-picker` (**לשימוש רק לאחר שהלקוח ענה — בתוך חלון 24ש׳**)  
**Body:** `בחר/י משבצת של חצי שעה`  
**Button:** `בחר/י`  
**Items (עד 10):** הקוד שולח כמשתנה `items` אובייקטים בפורמט:
```json
{"item":"14:00","description":"בחירת 14:00","id":"{"action":"pick_slot","event_id":"{{1}}","slot":"14:00"}"}
```
> נשלח עם `CONTENT_SID_SLOT_LIST` והמשנים:  
> `{"1": "<event_id>", "items": [ ... עד 10 פריטים ... ]}`

### 3) טמפלייט אישור זמן (Quick Reply)
**שם:** `hoh_confirm_qr_he`  
**סוג:** `twilio/quick-reply`  
**Body:** `לאשר את {{1}}?`  
**Buttons:**
- title: `כן` ; id: `{"action":"confirm_slot","event_id":"{{2}}","slot":"{{1}}"}`
- title: `לא, חזור` ; id: `{"action":"choose_time_range","event_id":"{{2}}","range":"noon"}`

### 4) "אני עוד לא יודע" (Quick Reply)
**שם:** `hoh_not_sure_qr_he`  
**סוג:** `twilio/quick-reply`  
**Body:** `הכל טוב! אצור קשר שוב תוך 72 שעות.`  
**Buttons:**
- title: `אשר` ; id: `{"action":"not_sure","event_id":"{{1}}"}'

### 5) "אני לא איש הקשר" (Quick Reply)
**שם:** `hoh_contact_qr_he`  
**סוג:** `twilio/quick-reply`  
**Body:** `למי נכון לפנות בבקשה? שלחו שם ומספר טלפון (לדוגמה +9725...) או שתפו איש קשר.`  
**Buttons:** *(לא חובה)*

> טוויליו מחזירה בוובהוק את `ButtonText` ו-`ButtonPayload` (ה-id) עבור Quick Reply, ואת הטקסט הנבחר עבור List Picker. ר' מסמכים למטה.

---

## שלב-אחר-שלב — חיבור הכל
1. **Twilio**: ודאו שיש Sender מאושר ל-WhatsApp (או Sandbox לבדיקה). קנפגו Webhook ל-`POST https://<domain>/whatsapp-webhook`.
2. **Twilio Content Templates**: צרו את 1,3,4,5 בקונסול (חלקם דורשים אישור). את 2 (`list-picker`) אין צורך לאשר — רק לשימוש בתוך חלון 24ש׳.
3. שייכו את ה-Content SIDs ל-`.env`.
4. **Google Sheets**: תנו גישה ל-Service Account ועדכנו שמות הטאבים ב-`.env`.
5. פריסה (Render/Heroku/EC2). ודאו שהפורט וה-Procfile תקינים. בדיקות `GET /health`.
6. שלחו הודעת פתיחה ללקוח דרך API (או ישירות מהקונסול) עם `CONTENT_SID_INIT_QR` והמשתנים (שם/תאריך/מופע/event_id).
7. עקבו אחר הוובהוק: בחירת טווח -> קבלת List Picker -> בחירת משבצת -> אישור -> כתיבה לשיטס.

---

## אבטחה
- מומלץ לאמת חתימות וובהוק (`X-Twilio-Signature`) — ניתן להוסיף בהמשך.
- אל תשמרו סודות בקוד. השתמשו ב-ENV.

---

## מקורות
- Using WhatsApp Buttons + Webhook fields (`ButtonText`, `ButtonPayload`): טוויליו דוקס.  
- Quick Reply / List Picker ב-Content API: טוויליו דוקס.

```

---

## פולו-אפ אוטומטי 72 שעות
- השרת כולל endpoint: `POST /run_followups` שמסרק את ה-Events ומחזיר הודעת פתיחה למי שסומן `follow_up_due_at` שעבר.
- הפעילו Cron (Render/Heroku Scheduler/GitHub Actions) פעם בשעה:
```bash
curl -X POST https://<domain>/run_followups
```
