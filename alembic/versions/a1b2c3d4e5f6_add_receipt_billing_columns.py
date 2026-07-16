"""add_receipt_billing_columns

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-16

Add missing billing columns to receipts table and create
assessment_questions / service_types / receipt_items tables.
"""
from alembic import op


revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    for col in [
        "vat_rate REAL DEFAULT 0",
        "vat_amount REAL DEFAULT 0",
        "net_amount REAL",
        "payment_method TEXT",
        "document_type TEXT DEFAULT 'receipt'",
        "client_email TEXT",
    ]:
        try:
            op.execute(f"ALTER TABLE receipts ADD COLUMN {col}")
        except Exception:
            pass

    op.execute('''
        CREATE TABLE IF NOT EXISTS assessment_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_type_id INTEGER NOT NULL REFERENCES assessment_types(id),
            question_order INTEGER NOT NULL,
            question_key TEXT NOT NULL,
            question_text_en TEXT NOT NULL,
            question_text_he TEXT NOT NULL,
            question_type TEXT NOT NULL DEFAULT 'radio',
            options_json TEXT DEFAULT '[]',
            required INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS service_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            default_price REAL NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL REFERENCES receipts(id),
            service_type_id INTEGER REFERENCES service_types(id),
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            line_total REAL NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('CREATE INDEX IF NOT EXISTS idx_ri_receipt ON receipt_items(receipt_id)')


def downgrade():
    for col in ["vat_rate", "vat_amount", "net_amount", "payment_method", "document_type", "client_email"]:
        try:
            op.execute(f"ALTER TABLE receipts DROP COLUMN {col}")
        except Exception:
            pass
    op.execute('DROP TABLE IF EXISTS assessment_questions')
    op.execute('DROP TABLE IF EXISTS service_types')
    op.execute('DROP TABLE IF EXISTS receipt_items')
