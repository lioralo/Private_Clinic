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
    appointment_id INTEGER,
    session_number TEXT,
    note_date DATE,
    needs_review BOOLEAN DEFAULT 0,
    content TEXT NOT NULL,
    content_hebrew TEXT,
    patient_appearance TEXT,
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
    treatment_id INTEGER,
    filename TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
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

CREATE TABLE IF NOT EXISTS blocked_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blocked_date DATE NOT NULL,
    blocked_time TIME NOT NULL,
    duration_minutes INTEGER DEFAULT 60,
    title TEXT,
    is_private BOOLEAN DEFAULT 0,
    block_type TEXT DEFAULT 'blocked',
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    url TEXT,
    is_public BOOLEAN DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS slots_override (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_date DATE NOT NULL,
    slot_time TIME NOT NULL,
    status TEXT NOT NULL,
    duration_minutes INTEGER DEFAULT 60,
    share_token TEXT,
    booked_by_name TEXT,
    booked_by_phone TEXT,
    booked_notes TEXT,
    booked_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vacancy_recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),
    slot_time TEXT NOT NULL,
    duration_minutes INTEGER DEFAULT 60,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS slots_recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6), -- 0=Sunday, 6=Saturday
    time TEXT NOT NULL -- HH:MM format
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    group_type TEXT DEFAULT 'support',
    description TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    left_at TIMESTAMP,
    role TEXT DEFAULT 'member',
    PRIMARY KEY (group_id, patient_id),
    FOREIGN KEY (group_id) REFERENCES groups (id),
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS group_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    session_date DATE NOT NULL,
    session_time TIME NOT NULL,
    duration_minutes INTEGER DEFAULT 60,
    title TEXT,
    facilitator TEXT,
    meeting_type TEXT DEFAULT 'in-person',
    meeting_link TEXT,
    supervision_id INTEGER,
    series_id INTEGER,
    occurrence_index INTEGER,
    session_summary TEXT,
    status TEXT DEFAULT 'scheduled',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES groups (id)
);

CREATE TABLE IF NOT EXISTS group_member_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    left_at TIMESTAMP,
    role TEXT DEFAULT 'member',
    FOREIGN KEY (group_id) REFERENCES groups (id),
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS group_session_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    start_date DATE NOT NULL,
    start_time TIME NOT NULL,
    duration_minutes INTEGER DEFAULT 60,
    recurrence_interval_weeks INTEGER DEFAULT 1,
    recurrence_end_date DATE,
    recurrence_count INTEGER,
    title TEXT,
    facilitator TEXT,
    meeting_type TEXT DEFAULT 'in-person',
    meeting_link TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES groups (id)
);

CREATE TABLE IF NOT EXISTS group_session_attendance (
    session_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    attendance_status TEXT NOT NULL DEFAULT 'pending',
    absence_reason TEXT,
    notified_on_time BOOLEAN DEFAULT 0,
    attendance_note TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, patient_id),
    FOREIGN KEY (session_id) REFERENCES group_sessions (id),
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE INDEX IF NOT EXISTS idx_patients_status_deleted ON patients(status, is_deleted);
CREATE INDEX IF NOT EXISTS idx_patients_type_deleted ON patients(patient_type, is_deleted);
CREATE INDEX IF NOT EXISTS idx_users_patient_id ON users(patient_id);

CREATE INDEX IF NOT EXISTS idx_appointments_patient_date_time ON appointments(patient_id, appointment_date, appointment_time);
CREATE INDEX IF NOT EXISTS idx_appointments_patient_status_date ON appointments(patient_id, status, appointment_date);
CREATE INDEX IF NOT EXISTS idx_appointments_date_time_status ON appointments(appointment_date, appointment_time, status);

CREATE INDEX IF NOT EXISTS idx_notes_patient_created ON notes(patient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_receipts_patient_created ON receipts(patient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_files_patient_created ON files(patient_id, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_recipient_read_time ON messages(recipient_id, is_read, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_sender_recipient_time ON messages(sender_id, recipient_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_slots_override_date_time_status ON slots_override(slot_date, slot_time, status);
CREATE INDEX IF NOT EXISTS idx_blocked_slots_date_time ON blocked_slots(blocked_date, blocked_time);
CREATE INDEX IF NOT EXISTS idx_vacancy_recurring_weekday_active_time ON vacancy_recurring(weekday, is_active, slot_time);

CREATE INDEX IF NOT EXISTS idx_group_members_patient_left ON group_members(patient_id, left_at);
CREATE INDEX IF NOT EXISTS idx_group_sessions_date_time_status ON group_sessions(session_date, session_time, status);
CREATE INDEX IF NOT EXISTS idx_group_member_history_group_patient ON group_member_history(group_id, patient_id, joined_at);
CREATE INDEX IF NOT EXISTS idx_group_series_group_start ON group_session_series(group_id, start_date);
CREATE INDEX IF NOT EXISTS idx_group_attendance_session_status ON group_session_attendance(session_id, attendance_status);

CREATE TABLE IF NOT EXISTS supervisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER,
    group_id INTEGER,
    supervision_date DATE NOT NULL,
    supervisor_name TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id),
    FOREIGN KEY (group_id) REFERENCES groups (id)
);

CREATE TABLE IF NOT EXISTS diagnosis_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'test_document',
    title TEXT,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE INDEX IF NOT EXISTS idx_notifications_read_created ON notifications(is_read, created_at);
CREATE INDEX IF NOT EXISTS idx_goals_patient_status ON goals(patient_id, status);
CREATE INDEX IF NOT EXISTS idx_supervisions_patient ON supervisions(patient_id, supervision_date);
CREATE INDEX IF NOT EXISTS idx_supervisions_group ON supervisions(group_id, supervision_date);
CREATE INDEX IF NOT EXISTS idx_diagnosis_documents_patient ON diagnosis_documents(patient_id, category, created_at);
