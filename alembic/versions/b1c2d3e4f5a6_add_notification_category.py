"""add_notification_category

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-07-16

Add category column to notifications table for unified messaging center.
"""
from alembic import op


revision = 'b1c2d3e4f5a6'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    try:
        op.execute("ALTER TABLE notifications ADD COLUMN category TEXT DEFAULT 'system'")
    except Exception:
        pass


def downgrade():
    pass
