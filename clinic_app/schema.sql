CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    birth_date DATE,
    id_number TEXT,
    status TEXT NOT NULL, -- 'ongoing', 'archived', 'candidate'
    is_deleted BOOLEAN DEFAULT 0,
    deleted_at TIMESTAMP,
    can_self_schedule BOOLEAN DEFAULT 0,
    patient_type TEXT DEFAULT 'private',
    has_intake_tab BOOLEAN DEFAULT 0,
    has_questionnaire_tab BOOLEAN DEFAULT 0,
    intake_assessment TEXT,
    intake_questionnaire TEXT,
    profile_image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    session_number INTEGER,
    patient_appearance TEXT,
    key_topics TEXT,
    content TEXT NOT NULL,
    content_hebrew TEXT,
    behavior_checklist TEXT,
    mood_summary TEXT,
    behavior_notes TEXT,
    is_missed_meeting BOOLEAN DEFAULT 0,
    missed_reason TEXT,
    link_url TEXT,
    updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS patient_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    encounter_date DATE,
    title TEXT,
    content TEXT NOT NULL,
    link_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    note_id INTEGER,
    filename TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id),
    FOREIGN KEY (note_id) REFERENCES notes (id)
);

CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'patient')),
    totp_secret TEXT,
    totp_enabled BOOLEAN DEFAULT 0,
    force_password_change BOOLEAN DEFAULT 0,
    email TEXT,
    phone TEXT,
    id_number TEXT,
    birth_date DATE,
    patient_id INTEGER,
    is_active BOOLEAN DEFAULT 1,
    session_version INTEGER DEFAULT 0,
    otp_secret TEXT,
    totp_recovery_codes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    requested_ip TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    appointment_date DATE NOT NULL,
    appointment_time TIME NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled', -- 'scheduled', 'completed', 'cancelled'
    cost REAL DEFAULT 0,
    duration_minutes INTEGER DEFAULT 60,
    is_recurring BOOLEAN DEFAULT 0,
    recurrence_interval INTEGER,
    recurrence_days TEXT,
    recurrence_end_date DATE,
    recurrence_count INTEGER,
    meeting_type TEXT DEFAULT 'in-person',
    meeting_link TEXT,
    meeting_platform TEXT,
    meeting_title TEXT,
    recurrence_group_id TEXT,
    missed_reason TEXT,
    save_to_google BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', -- 'open', 'booked'
    patient_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT 0,
    FOREIGN KEY (sender_id) REFERENCES users (id),
    FOREIGN KEY (recipient_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL, -- 0=Monday, 6=Sunday (or whatever convention Python/DB uses, usually 0-6)
    appointment_time TIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    url TEXT,
    is_public BOOLEAN DEFAULT 0,
    allow_patient_view BOOLEAN DEFAULT 1,
    allow_patient_download BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS patient_resources (
    patient_id INTEGER NOT NULL,
    resource_id INTEGER NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (patient_id, resource_id),
    FOREIGN KEY (patient_id) REFERENCES patients (id),
    FOREIGN KEY (resource_id) REFERENCES resources (id)
);

CREATE TABLE IF NOT EXISTS site_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT
);

CREATE TABLE IF NOT EXISTS google_oauth_pending_states (
    state TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    redirect_uri TEXT NOT NULL,
    code_verifier TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS idx_google_oauth_pending_created_at ON google_oauth_pending_states(created_at);

CREATE TABLE IF NOT EXISTS gdocs_sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trigger_source TEXT,
    status TEXT,
    interval_key TEXT,
    targets_total INTEGER DEFAULT 0,
    targets_processed INTEGER DEFAULT 0,
    synced_total INTEGER DEFAULT 0,
    synced_patients INTEGER DEFAULT 0,
    synced_groups INTEGER DEFAULT 0,
    pushed_groups INTEGER DEFAULT 0,
    errors_json TEXT,
    details_json TEXT
);
