"""add email reminder templates and incoming email tables

Revision ID: bfa630fc62a3
Revises: 32d4a8bb1807
Create Date: 2026-06-28 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bfa630fc62a3'
down_revision: Union[str, Sequence[str], None] = '32d4a8bb1807'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS email_reminder_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL UNIQUE,
            hours_before REAL NOT NULL DEFAULT 24.0,
            subject_template TEXT NOT NULL DEFAULT 'Appointment Reminder',
            body_template TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS incoming_email (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT,
            from_email TEXT NOT NULL,
            from_name TEXT,
            subject TEXT NOT NULL,
            body_text TEXT,
            body_html TEXT,
            related_type TEXT,
            related_id INTEGER,
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS idx_incoming_email_read ON incoming_email(is_read)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_incoming_email_created ON incoming_email(created_at)')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS incoming_email')
    op.execute('DROP TABLE IF EXISTS email_reminder_templates')
