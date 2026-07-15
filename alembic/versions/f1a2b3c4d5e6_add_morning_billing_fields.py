"""add_morning_billing_fields

Revision ID: f1a2b3c4d5e6
Revises: e7a2b9c4d1f0
Create Date: 2026-07-15

Add Morning API sync columns to receipts table and address fields to patients.
"""
from alembic import op
import sqlite3


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'e7a2b9c4d1f0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE receipts ADD COLUMN morning_doc_id TEXT")
    op.execute("ALTER TABLE receipts ADD COLUMN morning_sync_status TEXT DEFAULT 'pending'")
    op.execute("ALTER TABLE receipts ADD COLUMN morning_synced_at TIMESTAMP")
    op.execute("ALTER TABLE patients ADD COLUMN street TEXT")
    op.execute("ALTER TABLE patients ADD COLUMN city TEXT")
    op.execute("ALTER TABLE patients ADD COLUMN zip_code TEXT")


def downgrade():
    op.execute("ALTER TABLE receipts DROP COLUMN morning_doc_id")
    op.execute("ALTER TABLE receipts DROP COLUMN morning_sync_status")
    op.execute("ALTER TABLE receipts DROP COLUMN morning_synced_at")
    op.execute("ALTER TABLE patients DROP COLUMN street")
    op.execute("ALTER TABLE patients DROP COLUMN city")
    op.execute("ALTER TABLE patients DROP COLUMN zip_code")
