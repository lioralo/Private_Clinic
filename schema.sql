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
    intake_assessment TEXT,
    intake_questionnaire TEXT,
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
    updated_at TIMESTAMP,
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
    otp_secret TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

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
