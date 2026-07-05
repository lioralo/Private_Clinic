"""unify_availability_and_simplify_appointments

Revision ID: c9199256007c
Revises: 32d4a8bb1807
Create Date: 2026-07-02 09:48:50.731829

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9199256007c'
down_revision: Union[str, Sequence[str], None] = '32d4a8bb1807'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. Create unified `availability` table
    #    Replaces slots_override (one-time) + vacancy_recurring (weekly)
    # ---------------------------------------------------------------
    op.execute('''
        CREATE TABLE IF NOT EXISTS availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_date DATE,
            slot_time TIME NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 60,
            recurrence TEXT NOT NULL DEFAULT 'one_time'
                CHECK(recurrence IN ('one_time', 'weekly')),
            weekday INTEGER CHECK(weekday IS NULL OR (weekday >= 0 AND weekday <= 6)),
            status TEXT NOT NULL DEFAULT 'available'
                CHECK(status IN ('available', 'booked')),
            booked_by_name TEXT,
            booked_by_phone TEXT,
            booked_notes TEXT,
            booked_at TIMESTAMP,
            share_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS idx_availability_date ON availability(slot_date)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_availability_status ON availability(status)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_availability_share_token ON availability(share_token)')

    # Migrate one-time slots from slots_override
    op.execute('''
        INSERT INTO availability
            (slot_date, slot_time, duration_minutes, recurrence, status,
             booked_by_name, booked_by_phone, booked_notes, booked_at, share_token)
        SELECT
            slot_date, slot_time,
            COALESCE(duration_minutes, 60),
            'one_time',
            CASE WHEN status = 'available' THEN 'available' ELSE 'booked' END,
            booked_by_name, booked_by_phone, booked_notes, booked_at, share_token
        FROM slots_override
    ''')

    # Migrate weekly recurring slots from vacancy_recurring
    op.execute('''
        INSERT INTO availability
            (slot_time, duration_minutes, recurrence, weekday, status)
        SELECT
            slot_time,
            COALESCE(duration_minutes, 60),
            'weekly',
            weekday,
            'available'
        FROM vacancy_recurring
        WHERE COALESCE(is_active, 1) = 1
    ''')

    # ---------------------------------------------------------------
    # 2. Simplify appointments recurring model
    #    Add cancelled_dates JSON column; keep old columns for
    #    backward compatibility but they become unused.
    # ---------------------------------------------------------------
    op.execute('''
        CREATE TABLE IF NOT EXISTS appointments_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER REFERENCES patients(id),
            appointment_date DATE,
            appointment_time TIME,
            status TEXT DEFAULT 'scheduled',
            cost REAL NOT NULL DEFAULT 0,
            duration_minutes INTEGER NOT NULL DEFAULT 60,
            is_recurring BOOLEAN NOT NULL DEFAULT 0,
            recurrence_end_date DATE,
            cancelled_dates TEXT DEFAULT '[]',
            meeting_type TEXT DEFAULT 'in-person',
            meeting_link TEXT,
            meeting_platform TEXT,
            meeting_title TEXT,
            recurrence_group_id TEXT,
            missed_reason TEXT,
            save_to_google BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            google_event_id TEXT,
            reminder_sent_at TIMESTAMP
        )
    ''')

    # Migrate data into the new table
    op.execute('''
        INSERT INTO appointments_new
        SELECT
            id, patient_id, appointment_date, appointment_time,
            status, cost, duration_minutes,
            COALESCE(is_recurring, 0) AS is_recurring,
            recurrence_end_date,
            CASE
                WHEN COALESCE(excluded_dates, '') = '' THEN '[]'
                ELSE '["' || REPLACE(excluded_dates, ',', '","') || '"]'
            END AS cancelled_dates,
            meeting_type, meeting_link, meeting_platform, meeting_title,
            recurrence_group_id, missed_reason,
            COALESCE(save_to_google, 0) AS save_to_google,
            created_at, google_event_id, reminder_sent_at
        FROM appointments
    ''')

    op.execute('DROP TABLE IF EXISTS appointments')
    op.execute('ALTER TABLE appointments_new RENAME TO appointments')
    op.execute('CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments(patient_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appointment_date)')

    # ---------------------------------------------------------------
    # 3. Add recurrence support for group_sessions
    # ---------------------------------------------------------------
    op.execute('''
        CREATE TABLE IF NOT EXISTS group_sessions_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER REFERENCES groups(id),
            session_date DATE,
            session_time TIME,
            duration_minutes INTEGER NOT NULL DEFAULT 60,
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
            google_event_id TEXT,
            is_recurring BOOLEAN NOT NULL DEFAULT 0,
            recurrence_end_date DATE,
            cancelled_dates TEXT DEFAULT '[]',
            recurrence_group_id TEXT
        )
    ''')

    op.execute('''
        INSERT INTO group_sessions_new
        SELECT
            id, group_id, session_date, session_time,
            duration_minutes, title, facilitator,
            meeting_type, meeting_link,
            supervision_id, series_id, occurrence_index,
            session_summary, status, created_at,
            google_event_id,
            0 AS is_recurring,
            NULL AS recurrence_end_date,
            '[]' AS cancelled_dates,
            NULL AS recurrence_group_id
        FROM group_sessions
    ''')

    op.execute('DROP TABLE IF EXISTS group_sessions')
    op.execute('ALTER TABLE group_sessions_new RENAME TO group_sessions')
    op.execute('CREATE INDEX IF NOT EXISTS idx_group_sessions_date ON group_sessions(session_date)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_group_sessions_group ON group_sessions(group_id)')


def downgrade() -> None:
    # Revert group_sessions
    op.execute('''
        CREATE TABLE IF NOT EXISTS group_sessions_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            session_date DATE,
            session_time TIME,
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
            google_event_id TEXT
        )
    ''')
    op.execute('''
        INSERT INTO group_sessions_old
        SELECT id, group_id, session_date, session_time,
               duration_minutes, title, facilitator,
               meeting_type, meeting_link,
               supervision_id, series_id, occurrence_index,
               session_summary, status, created_at,
               google_event_id
        FROM group_sessions
    ''')
    op.execute('DROP TABLE IF EXISTS group_sessions')
    op.execute('ALTER TABLE group_sessions_old RENAME TO group_sessions')
    op.execute('CREATE INDEX IF NOT EXISTS idx_group_sessions_date ON group_sessions(session_date)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_group_sessions_group ON group_sessions(group_id)')

    # Revert appointments
    op.execute('''
        CREATE TABLE IF NOT EXISTS appointments_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            appointment_date DATE,
            appointment_time TIME,
            status TEXT DEFAULT 'scheduled',
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
            excluded_dates TEXT,
            google_event_id TEXT,
            reminder_sent_at TIMESTAMP
        )
    ''')
    op.execute('''
        INSERT INTO appointments_old
        SELECT
            a.id, a.patient_id, a.appointment_date, a.appointment_time,
            a.status, a.cost, a.duration_minutes,
            a.is_recurring,
            NULL AS recurrence_interval,
            CASE WHEN a.is_recurring = 1
                THEN CAST((julianday(a.appointment_date) % 7) AS INTEGER)
                ELSE NULL
            END AS recurrence_days,
            a.recurrence_end_date,
            NULL AS recurrence_count,
            a.meeting_type, a.meeting_link, a.meeting_platform,
            a.meeting_title, a.recurrence_group_id,
            a.missed_reason, a.save_to_google,
            a.created_at,
            CASE
                WHEN a.cancelled_dates IS NULL OR a.cancelled_dates = '[]' THEN ''
                ELSE REPLACE(REPLACE(REPLACE(a.cancelled_dates, '[', ''), ']', ''), '"', '')
            END AS excluded_dates,
            a.google_event_id, a.reminder_sent_at
        FROM appointments a
    ''')
    op.execute('DROP TABLE IF EXISTS appointments')
    op.execute('ALTER TABLE appointments_old RENAME TO appointments')
    op.execute('CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments(patient_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appointment_date)')

    # Drop availability table
    op.execute('DROP TABLE IF EXISTS availability')
