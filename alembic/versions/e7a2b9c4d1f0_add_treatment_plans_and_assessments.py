"""add_treatment_plans_and_assessments

Revision ID: e7a2b9c4d1f0
Revises: c9199256007c
Create Date: 2026-07-04 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op


revision: str = 'e7a2b9c4d1f0'
down_revision: Union[str, Sequence[str], None] = 'c9199256007c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. Treatment plans table
    # ---------------------------------------------------------------
    op.execute('''
        CREATE TABLE IF NOT EXISTS treatment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            diagnosis_code TEXT,
            diagnosis_description TEXT,
            problem_statement TEXT,
            strengths TEXT,
            created_date DATE NOT NULL DEFAULT (DATE('now')),
            review_date DATE,
            next_review_date DATE,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'completed', 'review', 'discontinued')),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS idx_treatment_plans_patient ON treatment_plans(patient_id)')

    op.execute('''
        CREATE TABLE IF NOT EXISTS treatment_plan_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES treatment_plans(id),
            goal_number INTEGER NOT NULL,
            goal_description TEXT NOT NULL,
            objectives TEXT,
            interventions TEXT,
            target_date DATE,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'in_progress', 'achieved', 'discontinued', 'revised')),
            progress_percentage INTEGER DEFAULT 0
                CHECK(progress_percentage >= 0 AND progress_percentage <= 100),
            revised_from_goal_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS idx_treatment_plan_goals_plan ON treatment_plan_goals(plan_id)')

    # ---------------------------------------------------------------
    # 2. Clinical outcome assessments
    # ---------------------------------------------------------------
    op.execute('''
        CREATE TABLE IF NOT EXISTS assessment_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL DEFAULT 'mental_health',
            num_questions INTEGER NOT NULL,
            scoring_method TEXT NOT NULL DEFAULT 'sum'
                CHECK(scoring_method IN ('sum', 'average', 'custom')),
            scoring_rules_json TEXT NOT NULL DEFAULT '{}',
            interpretation_json TEXT NOT NULL DEFAULT '[]',
            min_score REAL DEFAULT 0,
            max_score REAL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            assessment_type_id INTEGER NOT NULL REFERENCES assessment_types(id),
            admin_user_id INTEGER REFERENCES users(id),
            appointment_id INTEGER REFERENCES appointments(id),
            raw_scores_json TEXT NOT NULL DEFAULT '[]',
            total_score REAL,
            severity_level TEXT,
            interpretation TEXT,
            notes TEXT,
            taken_at DATE NOT NULL DEFAULT (DATE('now')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS idx_assessments_patient ON assessments(patient_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_assessments_type ON assessments(assessment_type_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_assessments_date ON assessments(taken_at)')

    # ---------------------------------------------------------------
    # 3. Seed built-in assessment types
    # ---------------------------------------------------------------
    op.execute('''
        INSERT OR IGNORE INTO assessment_types
            (name, display_name, description, category, num_questions,
             scoring_method, scoring_rules_json, interpretation_json,
             min_score, max_score)
        VALUES
            ('PHQ-9', 'Patient Health Questionnaire (PHQ-9)',
             '9-item depression screening. Scores 0-27' || CHAR(58) || ' None (0-4), Mild (5-9), Moderate (10-14), Moderately Severe (15-19), Severe (20-27).',
             'depression', 9, 'sum', '{"min_per_item"' || CHAR(58) || '0,"max_per_item"' || CHAR(58) || '3}',
             '[{"range"' || CHAR(58) || '[0,4],"label"' || CHAR(58) || '"None","severity"' || CHAR(58) || '"none"},{"range"' || CHAR(58) || '[5,9],"label"' || CHAR(58) || '"Mild","severity"' || CHAR(58) || '"mild"},{"range"' || CHAR(58) || '[10,14],"label"' || CHAR(58) || '"Moderate","severity"' || CHAR(58) || '"moderate"},{"range"' || CHAR(58) || '[15,19],"label"' || CHAR(58) || '"Moderately Severe","severity"' || CHAR(58) || '"moderately_severe"},{"range"' || CHAR(58) || '[20,27],"label"' || CHAR(58) || '"Severe","severity"' || CHAR(58) || '"severe"}]',
             0, 27)
    ''')

    op.execute('''
        INSERT OR IGNORE INTO assessment_types
            (name, display_name, description, category, num_questions,
             scoring_method, scoring_rules_json, interpretation_json,
             min_score, max_score)
        VALUES
            ('GAD-7', 'Generalized Anxiety Disorder (GAD-7)',
             '7-item anxiety screening. Scores 0-21' || CHAR(58) || ' None (0-4), Mild (5-9), Moderate (10-14), Severe (15-21).',
             'anxiety', 7, 'sum', '{"min_per_item"' || CHAR(58) || '0,"max_per_item"' || CHAR(58) || '3}',
             '[{"range"' || CHAR(58) || '[0,4],"label"' || CHAR(58) || '"None","severity"' || CHAR(58) || '"none"},{"range"' || CHAR(58) || '[5,9],"label"' || CHAR(58) || '"Mild","severity"' || CHAR(58) || '"mild"},{"range"' || CHAR(58) || '[10,14],"label"' || CHAR(58) || '"Moderate","severity"' || CHAR(58) || '"moderate"},{"range"' || CHAR(58) || '[15,21],"label"' || CHAR(58) || '"Severe","severity"' || CHAR(58) || '"severe"}]',
             0, 21)
    ''')

    # ---------------------------------------------------------------
    # 4. Add SMS preference to patients
    # ---------------------------------------------------------------
    try:
        op.execute('ALTER TABLE patients ADD COLUMN reminder_sms_enabled BOOLEAN DEFAULT 0')
    except Exception:
        pass

    # ---------------------------------------------------------------
    # 5. SMS log
    # ---------------------------------------------------------------
    op.execute('''
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_phone TEXT NOT NULL,
            message_body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'sent', 'failed')),
            gateway_response TEXT,
            sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS sms_logs')
    op.execute('DROP TABLE IF EXISTS assessments')
    op.execute('DROP TABLE IF EXISTS assessment_types')
    op.execute('DROP TABLE IF EXISTS treatment_plan_goals')
    op.execute('DROP TABLE IF EXISTS treatment_plans')
