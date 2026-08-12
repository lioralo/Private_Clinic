"""Migrate named public blocked_slots bookings into appointments.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6, bfa630fc62a3
Create Date: 2026-08-12

Merges Alembic heads and converts person-titled public bookings that were
stored as blocked_slots into waiting patients + appointments. True admin
blocks (created_by set, preserved titles, private) are left unchanged.
"""
from typing import Sequence, Union
import sqlite3

from alembic import op


revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = ('b1c2d3e4f5a6', 'bfa630fc62a3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sqlite_path_from_bind(bind) -> str | None:
    try:
        database = bind.engine.url.database
    except Exception:
        database = None
    if database:
        return database
    try:
        raw = bind.get_dbapi_connection()
        return raw.execute('PRAGMA database_list').fetchone()[2]
    except Exception:
        return None


def upgrade() -> None:
    from clinic_app.utils import migrate_named_blocked_bookings_to_appointments

    bind = op.get_bind()
    db_path = _sqlite_path_from_bind(bind)
    if not db_path:
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        migrate_named_blocked_bookings_to_appointments(conn)
    finally:
        conn.close()


def downgrade() -> None:
    # Data migration is not reversible (appointments/patients already created).
    pass
