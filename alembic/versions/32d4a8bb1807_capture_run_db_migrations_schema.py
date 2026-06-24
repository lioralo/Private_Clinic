"""capture_run_db_migrations_schema

Revision ID: 32d4a8bb1807
Revises: 8dcaf298fef3
Create Date: 2026-06-23 13:52:27.181138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '32d4a8bb1807'
down_revision: Union[str, Sequence[str], None] = '8dcaf298fef3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column(table, column_def):
    op.execute(f'ALTER TABLE {table} ADD COLUMN {column_def}')


def upgrade() -> None:
    # Tables not in schema.sql / initial migration
    op.execute('''
        CREATE TABLE IF NOT EXISTS slots_override (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_date DATE NOT NULL,
            slot_time TIME NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS blocked_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blocked_date DATE NOT NULL,
            blocked_time TIME NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS vacancy_recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),
            slot_time TEXT NOT NULL,
            duration_minutes INTEGER DEFAULT 60,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            message TEXT NOT NULL,
            recipient_user_id INTEGER,
            sender_id INTEGER,
            audience TEXT DEFAULT 'admin',
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS public_booking_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            created_by INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_type TEXT DEFAULT 'support',
            description TEXT,
            is_active BOOLEAN DEFAULT 1,
            gdoc_id TEXT,
            gdoc_watch_channel TEXT,
            gdoc_watch_expiry TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            left_at TIMESTAMP,
            role TEXT DEFAULT 'member',
            PRIMARY KEY (group_id, patient_id),
            FOREIGN KEY (group_id) REFERENCES groups (id),
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )
    ''')
    op.execute('''
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
            series_id INTEGER,
            occurrence_index INTEGER,
            session_summary TEXT,
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES groups (id)
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS group_member_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            left_at TIMESTAMP,
            role TEXT DEFAULT 'member',
            FOREIGN KEY (group_id) REFERENCES groups (id),
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )
    ''')
    op.execute('''
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
        )
    ''')
    op.execute('''
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
        )
    ''')
    op.execute('''
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
        )
    ''')
    op.execute('''
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
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS google_calendar_tokens (
            id INTEGER PRIMARY KEY,
            owner TEXT NOT NULL DEFAULT 'admin',
            token_json TEXT NOT NULL,
            calendar_id TEXT NOT NULL DEFAULT 'primary',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS treatment_method_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL UNIQUE,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS contact_inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS rate_limits (
            bucket_key TEXT NOT NULL,
            scope TEXT NOT NULL,
            timestamp_real REAL NOT NULL,
            PRIMARY KEY (bucket_key, scope, timestamp_real)
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS service_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            default_price REAL NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            service_type_id INTEGER,
            quantity INTEGER DEFAULT 1,
            unit_price REAL NOT NULL,
            line_total REAL NOT NULL,
            description TEXT,
            FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE,
            FOREIGN KEY (service_type_id) REFERENCES service_types(id)
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS cancel_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,
            admin_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (appointment_id) REFERENCES appointments(id),
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (reviewed_by) REFERENCES users(id)
        )
    ''')

    # ALTER TABLE ADD COLUMN — idempotent via try/except
    conn = op.get_bind()

    # appointments
    for col in [
        "duration_minutes INTEGER DEFAULT 60",
        "is_recurring BOOLEAN DEFAULT 0",
        "recurrence_interval INTEGER",
        "recurrence_days TEXT",
        'meeting_type TEXT DEFAULT "in-person"',
        "meeting_link TEXT",
        "recurrence_end_date DATE",
        "recurrence_count INTEGER",
        "meeting_platform TEXT",
        "meeting_title TEXT",
        "missed_reason TEXT",
        "save_to_google BOOLEAN DEFAULT 0",
        "excluded_dates TEXT",
        "recurrence_group_id TEXT",
        "google_event_id TEXT",
        "reminder_sent_at TIMESTAMP",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE appointments ADD COLUMN {col}'))
        except Exception:
            pass

    # notes
    for col in [
        "content_hebrew TEXT",
        "note_date DATE",
        "patient_appearance TEXT",
        "key_topics TEXT",
        "updated_at TIMESTAMP",
        "behavior_checklist TEXT",
        "mood_summary TEXT",
        "behavior_notes TEXT",
        "is_missed_meeting BOOLEAN DEFAULT 0",
        "missed_reason TEXT",
        "appointment_id INTEGER",
        "session_number INTEGER",
        "needs_review BOOLEAN DEFAULT 0",
        "link_url TEXT",
        "share_with_patient BOOLEAN DEFAULT 0",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE notes ADD COLUMN {col}'))
        except Exception:
            pass

    # files
    for col in [
        "treatment_id INTEGER",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE files ADD COLUMN {col}'))
        except Exception:
            pass

    # patients
    for col in [
        "background TEXT",
        "treatment_info TEXT",
        "profile_image TEXT",
        "can_self_schedule BOOLEAN DEFAULT 0",
        "patient_type TEXT DEFAULT 'private'",
        "intake_assessment TEXT",
        "intake_questionnaire TEXT",
        "is_deleted BOOLEAN DEFAULT 0",
        "deleted_at TIMESTAMP",
        "deleted_reason TEXT",
        "birth_date DATE",
        "id_number TEXT",
        "has_intake_tab BOOLEAN DEFAULT 0",
        "has_questionnaire_tab BOOLEAN DEFAULT 0",
        "treatment_method TEXT",
        "sort_order INTEGER",
        "gdoc_id TEXT",
        "gdoc_watch_channel TEXT",
        "gdoc_watch_expiry TEXT",
        "questionnaires_file_id TEXT",
        "questionnaires_file_url TEXT",
        "questionnaires_selected TEXT",
        "reminder_email_enabled BOOLEAN DEFAULT 1",
        "treatment_plan TEXT",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE patients ADD COLUMN {col}'))
        except Exception:
            pass

    # users
    for col in [
        "display_name TEXT",
        "email TEXT",
        "phone TEXT",
        "id_number TEXT",
        "birth_date DATE",
        "totp_secret TEXT",
        "totp_enabled BOOLEAN DEFAULT 0",
        "force_password_change BOOLEAN DEFAULT 0",
        "session_version INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE users ADD COLUMN {col}'))
        except Exception:
            pass

    # slots_override
    for col in [
        "duration_minutes INTEGER DEFAULT 60",
        "share_token TEXT",
        "booked_by_name TEXT",
        "booked_by_phone TEXT",
        "booked_notes TEXT",
        "booked_at TIMESTAMP",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE slots_override ADD COLUMN {col}'))
        except Exception:
            pass

    # blocked_slots
    for col in [
        "duration_minutes INTEGER DEFAULT 60",
        "title TEXT",
        "is_private BOOLEAN DEFAULT 0",
        "block_type TEXT DEFAULT 'blocked'",
        "created_by INTEGER",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE blocked_slots ADD COLUMN {col}'))
        except Exception:
            pass

    # resources
    for col in [
        "allow_patient_view BOOLEAN DEFAULT 1",
        "allow_patient_download BOOLEAN DEFAULT 1",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE resources ADD COLUMN {col}'))
        except Exception:
            pass

    # patient_resources
    try:
        conn.execute(sa.text("ALTER TABLE patient_resources ADD COLUMN assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
    except Exception:
        pass

    # notifications
    for col in [
        "title TEXT",
        "recipient_user_id INTEGER",
        "sender_id INTEGER",
        "audience TEXT DEFAULT 'admin'",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE notifications ADD COLUMN {col}'))
        except Exception:
            pass

    # groups
    for col in [
        "gdoc_id TEXT",
        "gdoc_watch_channel TEXT",
        "gdoc_watch_expiry TEXT",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE groups ADD COLUMN {col}'))
        except Exception:
            pass

    # group_sessions
    for col in [
        "series_id INTEGER",
        "occurrence_index INTEGER",
        "session_summary TEXT",
        "supervision_id INTEGER",
        "google_event_id TEXT",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE group_sessions ADD COLUMN {col}'))
        except Exception:
            pass

    # group_session_attendance
    try:
        conn.execute(sa.text("ALTER TABLE group_session_attendance ADD COLUMN notified_on_time BOOLEAN DEFAULT 0"))
    except Exception:
        pass

    # vacancy_recurring
    try:
        conn.execute(sa.text("ALTER TABLE vacancy_recurring ADD COLUMN duration_minutes INTEGER DEFAULT 60"))
    except Exception:
        pass

    # diagnosis_documents
    for col in [
        "category TEXT NOT NULL DEFAULT 'test_document'",
        "title TEXT",
        "original_filename TEXT",
        "stored_filename TEXT",
        "notes TEXT",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE diagnosis_documents ADD COLUMN {col}'))
        except Exception:
            pass

    # receipts
    for col in [
        "receipt_number TEXT",
        "status TEXT DEFAULT 'paid'",
    ]:
        try:
            conn.execute(sa.text(f'ALTER TABLE receipts ADD COLUMN {col}'))
        except Exception:
            pass

    # Indexes
    for idx in [
        'CREATE INDEX IF NOT EXISTS idx_patient_logs_patient_date ON patient_logs(patient_id, encounter_date)',
        'CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id)',
        'CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at)',
        'CREATE INDEX IF NOT EXISTS idx_patients_status_deleted ON patients(status, is_deleted)',
        'CREATE INDEX IF NOT EXISTS idx_patients_type_deleted ON patients(patient_type, is_deleted)',
        'CREATE INDEX IF NOT EXISTS idx_patients_name ON patients(name COLLATE NOCASE)',
        'CREATE INDEX IF NOT EXISTS idx_patients_email ON patients(email)',
        'CREATE INDEX IF NOT EXISTS idx_patients_phone ON patients(phone)',
        'CREATE INDEX IF NOT EXISTS idx_users_patient_id ON users(patient_id)',
        'CREATE INDEX IF NOT EXISTS idx_appointments_patient_date_time ON appointments(patient_id, appointment_date, appointment_time)',
        'CREATE INDEX IF NOT EXISTS idx_appointments_patient_status_date ON appointments(patient_id, status, appointment_date)',
        'CREATE INDEX IF NOT EXISTS idx_appointments_date_time_status ON appointments(appointment_date, appointment_time, status)',
        'CREATE INDEX IF NOT EXISTS idx_appointments_recurrence_group ON appointments(recurrence_group_id)',
        'CREATE INDEX IF NOT EXISTS idx_notes_patient_created ON notes(patient_id, created_at)',
        'CREATE INDEX IF NOT EXISTS idx_receipts_patient_created ON receipts(patient_id, created_at)',
        'CREATE INDEX IF NOT EXISTS idx_files_patient_created ON files(patient_id, created_at)',
        'CREATE INDEX IF NOT EXISTS idx_messages_recipient_read_time ON messages(recipient_id, is_read, timestamp)',
        'CREATE INDEX IF NOT EXISTS idx_messages_sender_recipient_time ON messages(sender_id, recipient_id, timestamp)',
        'CREATE INDEX IF NOT EXISTS idx_slots_override_date_time_status ON slots_override(slot_date, slot_time, status)',
        'CREATE INDEX IF NOT EXISTS idx_blocked_slots_date_time ON blocked_slots(blocked_date, blocked_time)',
        'CREATE INDEX IF NOT EXISTS idx_vacancy_recurring_weekday_active_time ON vacancy_recurring(weekday, is_active, slot_time)',
        'CREATE INDEX IF NOT EXISTS idx_group_members_patient_left ON group_members(patient_id, left_at)',
        'CREATE INDEX IF NOT EXISTS idx_group_sessions_date_time_status ON group_sessions(session_date, session_time, status)',
        'CREATE INDEX IF NOT EXISTS idx_group_member_history_group_patient ON group_member_history(group_id, patient_id, joined_at)',
        'CREATE INDEX IF NOT EXISTS idx_group_series_group_start ON group_session_series(group_id, start_date)',
        'CREATE INDEX IF NOT EXISTS idx_group_attendance_session_status ON group_session_attendance(session_id, attendance_status)',
        'CREATE INDEX IF NOT EXISTS idx_notifications_read_created ON notifications(is_read, created_at)',
        'CREATE INDEX IF NOT EXISTS idx_goals_patient_status ON goals(patient_id, status)',
        'CREATE INDEX IF NOT EXISTS idx_supervisions_patient ON supervisions(patient_id, supervision_date)',
        'CREATE INDEX IF NOT EXISTS idx_supervisions_group ON supervisions(group_id, supervision_date)',
        'CREATE INDEX IF NOT EXISTS idx_diagnosis_documents_patient ON diagnosis_documents(patient_id, category, created_at)',
        'CREATE INDEX IF NOT EXISTS idx_rate_limits_lookup ON rate_limits (bucket_key, scope, timestamp_real)',
        'CREATE INDEX IF NOT EXISTS idx_cancel_requests_appointment ON cancel_requests(appointment_id)',
        'CREATE INDEX IF NOT EXISTS idx_cancel_requests_patient_status ON cancel_requests(patient_id, status)',
        'CREATE INDEX IF NOT EXISTS idx_cancel_requests_status_created ON cancel_requests(status, created_at)',
        'CREATE INDEX IF NOT EXISTS idx_schedules_patient ON schedules(patient_id)',
        'CREATE INDEX IF NOT EXISTS idx_slots_patient ON slots(patient_id)',
    ]:
        try:
            conn.execute(sa.text(idx))
        except Exception:
            pass

    # Partial index for reminder queries
    try:
        conn.execute(sa.text(
            'CREATE INDEX IF NOT EXISTS idx_appointments_reminder_pending '
            'ON appointments (appointment_date, appointment_time) '
            "WHERE COALESCE(status, 'scheduled') = 'scheduled' AND reminder_sent_at IS NULL"
        ))
    except Exception:
        pass

    # Seed treatment method options
    for label in ['Psychodynamic', 'CBT', 'EFT', 'Management', '15 sessions', '3 sessions']:
        try:
            conn.execute(sa.text("INSERT OR IGNORE INTO treatment_method_options (label) VALUES (:l)"), {"l": label})
        except Exception:
            pass

    # Normalize legacy patient statuses
    try:
        conn.execute(sa.text("UPDATE patients SET status = 'candidate' WHERE status IN ('waiting', 'waiting for scheduling')"))
    except Exception:
        pass

    # Backfill resource default columns
    try:
        conn.execute(sa.text(
            "UPDATE resources SET allow_patient_view = COALESCE(allow_patient_view, 1), "
            "allow_patient_download = COALESCE(allow_patient_download, 1)"
        ))
    except Exception:
        pass


def downgrade() -> None:
    pass
