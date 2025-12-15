-- HOH Bot - DB Schema v1
-- Created: 2025-12-04

-- ===========================
--  ORGS & USERS
-- ===========================

CREATE TABLE orgs (
    org_id        BIGSERIAL PRIMARY KEY,
    name          TEXT        NOT NULL,
    slug          TEXT        UNIQUE,
    timezone      TEXT        NOT NULL DEFAULT 'Asia/Jerusalem',
    default_locale TEXT       NOT NULL DEFAULT 'he-IL',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    user_id     BIGSERIAL PRIMARY KEY,
    org_id      BIGINT     NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    name        TEXT       NOT NULL,
    email       TEXT       NOT NULL,
    role        TEXT       NOT NULL, -- admin / tech_manager / viewer
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE INDEX idx_users_org_id ON users(org_id);


CREATE TABLE audit_log (
    audit_id     BIGSERIAL PRIMARY KEY,
    org_id       BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    user_id      BIGINT REFERENCES users(user_id),
    entity_type  TEXT   NOT NULL, -- 'event', 'contact', 'conversation', ...
    entity_id    BIGINT NOT NULL,
    action       TEXT   NOT NULL, -- 'create', 'update', 'delete'
    before_data  JSONB,
    after_data   JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_org_created ON audit_log(org_id, created_at DESC);

-- ===========================
--  HALLS & EVENT SERIES
-- ===========================

CREATE TABLE halls (
    hall_id    BIGSERIAL PRIMARY KEY,
    org_id     BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    name       TEXT   NOT NULL,
    location   TEXT,
    notes      TEXT
);

CREATE INDEX idx_halls_org_id ON halls(org_id);

CREATE TABLE event_series (
    series_id   BIGSERIAL PRIMARY KEY,
    org_id      BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    name        TEXT   NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_series_org_id ON event_series(org_id);

-- ===========================
--  CONTACTS
-- ===========================

CREATE TABLE contacts (
    contact_id  BIGSERIAL PRIMARY KEY,
    org_id      BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    name        TEXT   NOT NULL,
    phone       TEXT   NOT NULL,
    role        TEXT,        -- מפיק / טכני / אחר
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- אותו טלפון לא יופיע פעמיים באותו ארגון
CREATE UNIQUE INDEX uq_contacts_org_phone ON contacts(org_id, phone);
CREATE INDEX idx_contacts_org_name ON contacts(org_id, name);

-- ===========================
--  EVENTS
-- ===========================

CREATE TABLE events (
    event_id              BIGSERIAL PRIMARY KEY,
    org_id                BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    series_id             BIGINT REFERENCES event_series(series_id),
    hall_id               BIGINT NOT NULL REFERENCES halls(hall_id),
    name                  TEXT   NOT NULL,
    event_date            DATE   NOT NULL,
    show_time             TIMESTAMPTZ,  -- תחילת מופע
    load_in_time          TIMESTAMPTZ,  -- כניסה להקמות
    event_type            TEXT   NOT NULL DEFAULT 'show', 
    status                TEXT   NOT NULL DEFAULT 'draft', 
    producer_contact_id   BIGINT REFERENCES contacts(contact_id),
    technical_contact_id  BIGINT REFERENCES contacts(contact_id),
    notes                 TEXT,
    is_data_complete      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- נסמן שהסטטוס והטייפ הם ENUM לוגי (ת enforcement בקוד או ע"י CHECK אם תרצה, אפשר להוסיף אח"כ)
-- לדוגמה:
-- ALTER TABLE events ADD CONSTRAINT chk_events_status
--   CHECK (status IN ('draft','pending_contact','waiting_for_reply','confirmed','cancelled'));

CREATE INDEX idx_events_org_date ON events(org_id, event_date);
CREATE INDEX idx_events_org_status ON events(org_id, status);

-- ===========================
--  CONVERSATIONS & MESSAGES
-- ===========================

CREATE TABLE conversations (
    conversation_id BIGSERIAL PRIMARY KEY,
    org_id          BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    event_id        BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    contact_id      BIGINT NOT NULL REFERENCES contacts(contact_id),
    channel         TEXT   NOT NULL DEFAULT 'whatsapp',
    status          TEXT   NOT NULL DEFAULT 'open', 
    pending_data_fields JSONB, -- אילו שדות עדיין חסרים לאירוע (אם אתה רוצה)
    last_message_id BIGINT,    -- FK למטה, כדי להימנע מסייקל נשים בלי FK קשיח
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversations_org_status ON conversations(org_id, status);
CREATE INDEX idx_conversations_event_contact ON conversations(event_id, contact_id);

CREATE TABLE messages (
    message_id       BIGSERIAL PRIMARY KEY,
    org_id           BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    conversation_id  BIGINT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    event_id         BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    contact_id       BIGINT NOT NULL REFERENCES contacts(contact_id),
    direction        TEXT   NOT NULL, -- 'outgoing' / 'incoming'
    template_id      BIGINT,          -- FK ל-message_templates, ניצור אחרי הטבלה ההיא
    body             TEXT   NOT NULL,
    raw_payload      JSONB,
    whatsapp_msg_sid TEXT,
    sent_at          TIMESTAMPTZ,
    received_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_org_conv ON messages(org_id, conversation_id);
CREATE INDEX idx_messages_event ON messages(event_id);
CREATE INDEX idx_messages_contact ON messages(contact_id);


-- עכשיו אפשר לחבר את last_message_id ב-conversations ל-messages אם תרצה FK:
-- ALTER TABLE conversations
--   ADD CONSTRAINT fk_conversations_last_msg
--   FOREIGN KEY (last_message_id) REFERENCES messages(message_id);

-- ===========================
--  MESSAGE DELIVERY LOG
-- ===========================

CREATE TABLE message_delivery_log (
    delivery_id     BIGSERIAL PRIMARY KEY,
    org_id          BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    message_id      BIGINT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    status          TEXT   NOT NULL, -- 'queued','sent','delivered','failed'
    error_code      TEXT,
    error_message   TEXT,
    provider        TEXT   NOT NULL DEFAULT 'twilio',
    provider_payload JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_delivery_message ON message_delivery_log(message_id);
CREATE INDEX idx_delivery_org_status ON message_delivery_log(org_id, status);

-- ===========================
--  MESSAGE TEMPLATES & FOLLOWUPS
-- ===========================

CREATE TABLE message_templates (
    template_id    BIGSERIAL PRIMARY KEY,
    org_id         BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    name           TEXT   NOT NULL, -- "פינג ראשון", "תזכורת יום לפני"
    usage_type     TEXT   NOT NULL, -- 'initial_ping','reminder','other'
    channel        TEXT   NOT NULL DEFAULT 'whatsapp',
    locale         TEXT   NOT NULL, -- 'he-IL', 'en-US'
    body_template  TEXT   NOT NULL, -- כולל placeholders
    description    TEXT,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_templates_org_usage ON message_templates(org_id, usage_type);
CREATE INDEX idx_templates_org_locale ON message_templates(org_id, locale);


ALTER TABLE messages
  ADD CONSTRAINT fk_messages_template
  FOREIGN KEY (template_id) REFERENCES message_templates(template_id);


CREATE TABLE followup_rules (
    rule_id          BIGSERIAL PRIMARY KEY,
    org_id           BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    from_template_id BIGINT NOT NULL REFERENCES message_templates(template_id) ON DELETE CASCADE,
    trigger          TEXT   NOT NULL, -- 'no_reply'
    delay_minutes    INTEGER NOT NULL,
    next_template_id BIGINT NOT NULL REFERENCES message_templates(template_id) ON DELETE CASCADE,
    max_attempts     INTEGER NOT NULL DEFAULT 1,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_followup_org_from_template ON followup_rules(org_id, from_template_id);

-- ===========================
--  IMPORT / SYNC JOBS
-- ===========================

CREATE TABLE import_jobs (
    job_id       BIGSERIAL PRIMARY KEY,
    org_id       BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    job_type     TEXT   NOT NULL, -- 'csv_events','csv_contacts', ...
    source       TEXT,            -- קובץ, API וכו'
    status       TEXT   NOT NULL DEFAULT 'running', -- 'running','success','failed'
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    details      JSONB,           -- כמה רשומות, summary
    error_message TEXT
);

CREATE INDEX idx_import_jobs_org_status ON import_jobs(org_id, status, started_at DESC);

-- ===========================
--  EMPLOYEES
-- ===========================

CREATE TABLE employees (
    employee_id  BIGSERIAL PRIMARY KEY,
    org_id       BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    name         TEXT   NOT NULL,
    phone        TEXT   NOT NULL,
    role         TEXT,        -- סדרן / טכנאי / קופאי / מנהל משמרת וכו'
    notes        TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- אותו טלפון לא יופיע פעמיים באותו ארגון (כמו ב-contacts)
CREATE UNIQUE INDEX uq_employees_org_phone ON employees(org_id, phone);

CREATE INDEX idx_employees_org_name ON employees(org_id, name);
CREATE INDEX idx_employees_org_active ON employees(org_id, is_active);

-- ===========================
--  EMPLOYEE SHIFTS (משמרות עובדים)
-- ===========================

CREATE TABLE employee_shifts (
    shift_id      BIGSERIAL PRIMARY KEY,
    org_id        BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    event_id      BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    employee_id   BIGINT NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,

    shift_role    TEXT,           -- תפקיד במשמרת (סדרן ראשי / טכנאי תאורה / כרטיסן וכו')
    call_time     TIMESTAMPTZ NOT NULL,  -- שעת כניסה למשמרת עבור העובד
    notes         TEXT,           -- הערות ספציפיות לאירוע הזה

    reminder_24h_sent_at TIMESTAMPTZ,    -- מתי נשלחה תזכורת 24 שעות (null = עוד לא נשלח)

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (event_id, employee_id)
);

CREATE INDEX idx_employee_shifts_org_call_time
    ON employee_shifts (org_id, call_time);

CREATE INDEX idx_employee_shifts_event
    ON employee_shifts (event_id);

CREATE INDEX idx_employee_shifts_employee
    ON employee_shifts (employee_id);

