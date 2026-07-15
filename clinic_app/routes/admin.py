import csv
import json
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import pyotp
from flask import (
    Blueprint, current_app, flash, jsonify, redirect,
    render_template, request, Response, session, url_for,
)
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from clinic_app.models import get_db
from clinic_app.utils import (
    _smtp_settings_summary, _smtp_health_check, _send_smtp_email,
    _check_public_rate_limit, _request_client_ip,
    parse_date_safe, redirect_to_patient_tab,
)

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / 'scripts')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
try:
    import google_calendar as _gcal
except ImportError:
    _gcal = None
try:
    import google_docs as _gdocs
except ImportError:
    _gdocs = None

admin_bp = Blueprint('admin', __name__)




# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def _get_dashboard_today_appointments(db, today):
    tomorrow = today + timedelta(days=1)
    return db.execute('''
        SELECT a.id, a.appointment_date, a.appointment_time, a.duration_minutes,
               a.meeting_type, a.meeting_link, a.is_recurring,
               p.id AS patient_id, p.name AS patient_name,
               p.status AS patient_status, p.treatment_method
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE COALESCE(a.status, 'scheduled') = 'scheduled'
          AND COALESCE(p.is_deleted, 0) = 0
          AND a.appointment_date IN (?, ?)
        ORDER BY a.appointment_time ASC
    ''', (today.isoformat(), tomorrow.isoformat())).fetchall()


def _get_dashboard_week_appointments(db, today, week_end):
    return db.execute('''
        SELECT a.id, a.appointment_date, a.appointment_time, a.meeting_type,
               p.id AS patient_id, p.name AS patient_name
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE COALESCE(a.status, 'scheduled') = 'scheduled'
          AND COALESCE(p.is_deleted, 0) = 0
          AND a.appointment_date > ?
          AND a.appointment_date <= ?
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    ''', (today.isoformat(), week_end.isoformat())).fetchall()


def _get_dashboard_patient_counts(db, include_deleted=False):
    where_clause = '' if include_deleted else 'WHERE COALESCE(is_deleted, 0) = 0'
    counts_row = db.execute(f'''
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'ongoing' THEN 1 ELSE 0 END) AS ongoing,
            SUM(CASE WHEN status IN ('candidate', 'waiting for scheduling', 'waiting') THEN 1 ELSE 0 END) AS waiting,
            SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) AS archived
        FROM patients {where_clause}
    ''').fetchone()
    return {
        'total':   counts_row['total']   or 0,
        'ongoing': counts_row['ongoing'] or 0,
        'waiting': counts_row['waiting'] or 0,
        'archived':counts_row['archived']or 0,
    }


def _get_dashboard_unread_count(db, user_id):
    return db.execute(
        'SELECT COUNT(*) FROM messages WHERE recipient_id = ? AND COALESCE(is_read, 0) = 0',
        (user_id,)
    ).fetchone()[0]


def _get_dashboard_followup_patients(db):
    return db.execute('''
        SELECT p.id, p.name, p.status, MAX(a.appointment_date) AS last_appt_date
        FROM patients p
        JOIN appointments a ON a.patient_id = p.id
        WHERE p.status = 'candidate'
          AND COALESCE(p.is_deleted, 0) = 0
          AND a.is_recurring = 0
          AND COALESCE(a.status, 'scheduled') = 'scheduled'
          AND a.appointment_date < DATE('now')
          AND NOT EXISTS (
              SELECT 1 FROM appointments a2
              WHERE a2.patient_id = p.id
                AND COALESCE(a2.status, 'scheduled') = 'scheduled'
                AND a2.appointment_date >= DATE('now')
          )
        GROUP BY p.id
        ORDER BY last_appt_date ASC
        LIMIT 8
    ''').fetchall()


def _get_dashboard_waiting_patients(db):
    return db.execute('''
        SELECT p.id, p.name, p.created_at
        FROM patients p
                WHERE p.status IN ('candidate', 'waiting', 'waiting for scheduling')
          AND COALESCE(p.is_deleted, 0) = 0
          AND NOT EXISTS (
              SELECT 1 FROM appointments a WHERE a.patient_id = p.id
                AND COALESCE(a.status, 'scheduled') = 'scheduled'
                AND a.appointment_date >= DATE('now')
          )
        ORDER BY p.created_at ASC
        LIMIT 6
    ''').fetchall()


def _get_dashboard_recent_patients(db):
    return db.execute('''
        SELECT id, name, status, patient_type, treatment_method, created_at
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
        ORDER BY created_at DESC
        LIMIT 6
    ''').fetchall()


def _get_dashboard_recent_activity(db):
    return db.execute('''
        SELECT al.action, al.details, al.created_at,
               p.name AS patient_name, p.id AS patient_id
        FROM audit_logs al
        LEFT JOIN patients p ON p.id = al.patient_id
        ORDER BY al.created_at DESC
        LIMIT 10
    ''').fetchall()


def _get_dashboard_missing_recurring(db):
    return db.execute('''
        SELECT id, name
        FROM patients
        WHERE status = 'ongoing'
          AND COALESCE(is_deleted, 0) = 0
          AND NOT EXISTS (
              SELECT 1 FROM appointments a
              WHERE a.patient_id = patients.id
                AND a.is_recurring = 1
                AND COALESCE(a.status, 'scheduled') = 'scheduled'
          )
        ORDER BY name ASC
        LIMIT 6
    ''').fetchall()


def _get_dashboard_security_metrics(db):
    try:
        row = db.execute('''
            SELECT
                SUM(action = 'auth_login_password_failed')    AS failed_logins,
                SUM(action = 'auth_login_2fa_failed')         AS failed_2fa,
                SUM(action = 'auth_password_reset_requested') AS reset_requests,
                SUM(action = 'auth_login_disabled_account')   AS disabled_attempts
            FROM audit_logs
            WHERE created_at >= datetime('now', '-1 day')
        ''').fetchone()
        recent_failures = db.execute('''
            SELECT details, created_at
            FROM audit_logs
            WHERE action IN ('auth_login_password_failed', 'auth_login_2fa_failed',
                             'auth_login_disabled_account')
              AND created_at >= datetime('now', '-1 day')
            ORDER BY created_at DESC
            LIMIT 5
        ''').fetchall()
        return {
            'failed_logins': int(row['failed_logins'] or 0),
            'failed_2fa': int(row['failed_2fa'] or 0),
            'reset_requests': int(row['reset_requests'] or 0),
            'disabled_attempts': int(row['disabled_attempts'] or 0),
            'recent_failures': [dict(r) for r in recent_failures],
        }
    except Exception:
        return {
            'failed_logins': 0, 'failed_2fa': 0,
            'reset_requests': 0, 'disabled_attempts': 0,
            'recent_failures': [],
        }


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('patient_home'))
    db = get_db()
    today = datetime.now().date()
    week_end = today + timedelta(days=6)
    gdocs_auto_sync_health = {}
    try:
        from clinic_app.utils import _get_gdocs_auto_sync_health
        gdocs_auto_sync_health = _get_gdocs_auto_sync_health(db)
    except Exception:
        pass
    return render_template('admin_home.html',
        today=today,
        today_appointments=_get_dashboard_today_appointments(db, today),
        week_appointments=_get_dashboard_week_appointments(db, today, week_end),
        counts=_get_dashboard_patient_counts(db),
        unread_count=_get_dashboard_unread_count(db, current_user.id),
        followup_patients=_get_dashboard_followup_patients(db),
        waiting_patients=_get_dashboard_waiting_patients(db),
        recent_patients=_get_dashboard_recent_patients(db),
        recent_activity=_get_dashboard_recent_activity(db),
        missing_recurring=_get_dashboard_missing_recurring(db),
        gdocs_auto_sync_health=gdocs_auto_sync_health,
        security_metrics=_get_dashboard_security_metrics(db))


@admin_bp.route('/api/admin/export_calendar')
@login_required
def export_calendar():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    appointments = db.execute('''
        SELECT appointment_date, appointment_time, meeting_type, meeting_link,
               is_recurring, recurrence_interval, recurrence_days, recurrence_end_date, recurrence_count,
               duration_minutes, cost
        FROM appointments
        ORDER BY appointment_date ASC, appointment_time ASC
    ''').fetchall()
    data = [dict(row) for row in appointments]
    response = Response(json.dumps(data, indent=4), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename=calendar_export.json'
    return response


@admin_bp.route('/api/admin/export_appointments.csv')
@login_required
def export_appointments_csv():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    from_date = (request.args.get('from_date') or '').strip()
    to_date = (request.args.get('to_date') or '').strip()
    status = (request.args.get('status') or 'all').strip().lower()
    where_clauses = ['COALESCE(p.is_deleted, 0) = 0']
    params = []
    if from_date:
        parsed_from = parse_date_safe(from_date)
        if parsed_from:
            where_clauses.append('a.appointment_date >= ?')
            params.append(parsed_from.isoformat())
    if to_date:
        parsed_to = parse_date_safe(to_date)
        if parsed_to:
            where_clauses.append('a.appointment_date <= ?')
            params.append(parsed_to.isoformat())
    allowed_statuses = {'scheduled', 'completed', 'cancelled'}
    if status in allowed_statuses:
        where_clauses.append("COALESCE(a.status, 'scheduled') = ?")
        params.append(status)
    rows = db.execute(f'''
        SELECT a.id, a.appointment_date, a.appointment_time, a.duration_minutes,
               COALESCE(a.status, 'scheduled') AS status, a.meeting_type, a.meeting_title,
               a.meeting_link, a.is_recurring, a.created_at,
               p.id AS patient_id, p.name AS patient_name, p.status AS patient_status,
               COALESCE(p.patient_type, 'private') AS patient_type
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY a.appointment_date ASC, a.appointment_time ASC, a.id ASC
    ''', tuple(params)).fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'appointment_id', 'appointment_date', 'appointment_time', 'duration_minutes',
        'status', 'meeting_type', 'meeting_title', 'meeting_link', 'is_recurring',
        'patient_id', 'patient_name', 'patient_status', 'patient_type', 'created_at'])
    for row in rows:
        writer.writerow([
            row['id'], row['appointment_date'], row['appointment_time'],
            row['duration_minutes'], row['status'], row['meeting_type'],
            row['meeting_title'] or '', row['meeting_link'] or '',
            int(row['is_recurring'] or 0), row['patient_id'], row['patient_name'],
            row['patient_status'], row['patient_type'], row['created_at'] or ''])
    csv_content = '\ufeff' + output.getvalue()
    response = Response(csv_content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename=appointments_export_{datetime.now().strftime("%Y%m%d")}.csv'
    return response


@admin_bp.route('/api/admin/bulk_complete_past_appointments', methods=['POST'])
@login_required
def bulk_complete_past_appointments():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    result = db.execute(
        "UPDATE appointments SET status = 'completed' WHERE status = 'scheduled' AND appointment_date < DATE('now')")
    updated = result.rowcount
    if updated:
        db.execute(
            'INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)',
            (None, 'bulk-complete-appointments', f'Bulk marked {updated} past scheduled appointments as completed'))
        db.commit()
    return jsonify({'status': 'success', 'updated': updated})


# ---------------------------------------------------------------------------
# Seed / test data helpers and routes
# ---------------------------------------------------------------------------

def _seed_ongoing_patient(db, admin_id, today):
    db.execute(
        """INSERT INTO patients (name, status, email, phone, background, treatment_info)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            'Maya Cohen',
            'ongoing',
            'maya.cohen@example.com',
            '050-1234567',
            'Mid-30s professional. Referred by GP following prolonged work-related stress. '
            'Presents with symptoms of generalized anxiety and mild sleep disturbance.',
            'CBT formulation agreed. Exploring cognitive distortions related to performance at work. '
            'Engagement is strong, regular homework compliance.'
        )
    )
    ongoing_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Past appointments (last 8 weeks)
    past_appt_ids = []
    for week in range(8, 0, -1):
        appt_date = (today - timedelta(weeks=week)).strftime('%Y-%m-%d')
        db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                        cost, duration_minutes, status, meeting_type, is_recurring,
                        recurrence_interval, recurrence_days)
                      VALUES (?, ?, '10:00', 350, 50, 'completed', 'in-person', 1, 1, '0')""",
                   (ongoing_id, appt_date))
        past_appt_ids.append((db.execute("SELECT last_insert_rowid()").fetchone()[0], week, appt_date))

    # Session notes for past appointments
    notes_data = [
        (1, 'Initial assessment. Patient reports chronic work stress for ~18 months. Sleep disturbed — waking at 3am with racing thoughts. Explored presenting concerns, treatment goals set: reduce anxiety baseline, improve sleep hygiene, build assertiveness at work.'),
        (2, 'Introduced thought records. Patient practiced identifying automatic negative thoughts around a recent conflict with manager. Good engagement. Homework: daily thought record.'),
        (3, 'Reviewed homework — completed 4/7 days. Identified core belief: "I must not disappoint others." Explored origin. Introduced behavioural activation for mood.'),
        (4, 'Sleep significantly improved (5→7hrs avg). Reports using progressive relaxation technique. Discussed assertiveness — role-played declining extra work from colleague. Patient found it difficult but agreed to try.'),
        (5, 'Used assertiveness with manager — partial success. Processed feelings of guilt. Sleep still good. Introduced mindfulness breathing.'),
        (6, 'Mid-treatment review. PHQ-9 reduced from 14 to 7. GAD-7 reduced from 16 to 9. Patient attributes progress to thought monitoring and sleep routine. Identified remaining work: perfectionism.'),
        (7, 'Explored perfectionism schema — linked to early family expectations. Patient journalled between sessions about "good enough." Discussed self-compassion.'),
        (8, 'Strong session. Patient reported turning down optional weekend project without significant guilt. Sleep 7-8hrs consistently. Planning consolidation phase.'),
    ]
    for (appt_id, week, appt_date), (sn, content) in zip(past_appt_ids, notes_data):
        db.execute("""INSERT INTO notes (patient_id, appointment_id, session_number, content)
                      VALUES (?, ?, ?, ?)""",
                   (ongoing_id, appt_id, str(sn), content))

    # Upcoming recurring appointment (next Monday)
    days_ahead = (7 - today.weekday()) % 7 or 7
    next_session = (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                    cost, duration_minutes, status, meeting_type, is_recurring,
                    recurrence_interval, recurrence_days)
                  VALUES (?, ?, '10:00', 350, 50, 'scheduled', 'in-person', 1, 1, '0')""",
               (ongoing_id, next_session))

    # Receipts for past sessions
    for (appt_id, week, appt_date) in past_appt_ids:
        db.execute("INSERT INTO receipts (patient_id, amount, description, created_at) VALUES (?, 350, 'Session payment', ?)",
                   (ongoing_id, appt_date))

    # Goals
    db.execute("INSERT INTO goals (patient_id, description, status) VALUES (?, ?, 'achieved')",
               (ongoing_id, 'Improve sleep to at least 6 hours per night'))
    db.execute("INSERT INTO goals (patient_id, description, status) VALUES (?, ?, 'achieved')",
               (ongoing_id, 'Set one work boundary per week'))
    db.execute("INSERT INTO goals (patient_id, description, status) VALUES (?, ?, 'active')",
               (ongoing_id, 'Reduce perfectionist self-criticism using self-compassion exercises'))

    # Message exchange
    from werkzeug.security import generate_password_hash as _gph
    existing_maya = db.execute("SELECT id FROM users WHERE username = 'maya'").fetchone()
    if not existing_maya:
        db.execute("INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', ?)",
                   ('maya', _gph('patient123'), ongoing_id))
    maya_user = db.execute("SELECT id FROM users WHERE username = 'maya'").fetchone()
    if maya_user and admin_id:
        db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                   (maya_user['id'], admin_id, 'Hi, just confirming our appointment next Monday at 10:00. See you then!'))
        db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                   (admin_id, maya_user['id'], 'Confirmed! See you Monday at 10:00. Bring your thought record homework if you have it ready.'))


def _seed_candidate_patient(db, admin_id):
    db.execute(
        """INSERT INTO patients (name, status, email, phone, background)
           VALUES (?, ?, ?, ?, ?)""",
        (
            'Daniel Levy',
            'candidate',
            'daniel.levy@example.com',
            '052-9876543',
            'Late 20s, referred by his GP. Experiencing social anxiety and avoidance '
            'behaviour. First contact made via intake form. Awaiting initial assessment session.'
        )
    )
    candidate_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    if admin_id:
        from werkzeug.security import generate_password_hash as _gph
        existing_daniel = db.execute("SELECT id FROM users WHERE username = 'daniel'").fetchone()
        if not existing_daniel:
            db.execute("INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', ?)",
                       ('daniel', _gph('patient123'), candidate_id))
        daniel_user = db.execute("SELECT id FROM users WHERE username = 'daniel'").fetchone()
        if daniel_user:
            db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                       (daniel_user['id'], admin_id, 'Hello, I was referred by Dr. Shapira. I struggle a lot with social situations and anxiety. When would we be able to meet?'))
            db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                       (admin_id, daniel_user['id'], 'Thank you for reaching out, Daniel. I have reviewed your intake form. I can offer an initial assessment on Sunday at 11:00. Does that work for you?'))
            db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                       (daniel_user['id'], admin_id, 'Yes, Sunday at 11:00 works perfectly. Thank you!'))


def _seed_waiting_patient(db, admin_id, today):
    db.execute(
        """INSERT INTO patients (name, status, email, phone, background, treatment_info)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            'Noa Shapiro',
            'candidate',
            'noa.shapiro@example.com',
            '054-3456789',
            'Early 40s, presenting with grief and adjustment difficulties following loss of parent. '
            'Initial assessment completed. Psychoeducation around grief provided.',
            'Humanistic integrative approach planned. Weekly sessions. '
            'Awaiting mutually available recurring slot to be confirmed.'
        )
    )
    waiting_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Initial assessment appointment (2 weeks ago)
    assess_date = (today - timedelta(weeks=2)).strftime('%Y-%m-%d')
    db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                    cost, duration_minutes, status, meeting_type)
                  VALUES (?, ?, '14:00', 350, 60, 'completed', 'in-person')""",
               (waiting_id, assess_date))
    assess_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        """INSERT INTO notes (patient_id, appointment_id, session_number, content)
           VALUES (?, ?, '0', ?)""",
        (
            waiting_id,
            assess_id,
            "Initial assessment session. Patient describes grief following mother's passing 4 months ago. "
            "Reports low mood, social withdrawal, and difficulty returning to routine. "
            "No risk indicators present. Agreed on weekly therapy."
        )
    )
    db.execute("INSERT INTO receipts (patient_id, amount, description, created_at) VALUES (?, 350, 'Assessment session', ?)",
               (waiting_id, assess_date))

    from werkzeug.security import generate_password_hash as _gph
    existing_noa = db.execute("SELECT id FROM users WHERE username = 'noa'").fetchone()
    if not existing_noa:
        db.execute("INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', ?)",
                   ('noa', _gph('patient123'), waiting_id))
    noa_user = db.execute("SELECT id FROM users WHERE username = 'noa'").fetchone()
    if noa_user and admin_id:
        db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                   (admin_id, noa_user['id'], 'Hi Noa, thank you for coming in last week. I am looking for a recurring Tuesday slot for us. Are mornings or afternoons better for you?'))
        db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                   (noa_user['id'], admin_id, 'Afternoons work better, anytime after 15:00. Thank you for checking.'))


def _seed_archived_patient(db, today):
    db.execute(
        """INSERT INTO patients (name, status, email, phone, background, treatment_info)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            'Eran Mizrahi',
            'archived',
            'eran.mizrahi@example.com',
            '053-7654321',
            'Early 50s. Presented with panic disorder and agoraphobia. '
            'Referred by psychiatrist. Treatment completed after 22 sessions.',
            'CBT for panic disorder. Completed January 2025. Full remission achieved. '
            'Discharged with relapse prevention plan. Follow-up offered in 6 months.'
        )
    )
    archived_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 6 representative past sessions
    archive_notes = [
        ('1', 'Psychoeducation on panic cycle. Explained fight/flight response. Patient very relieved to understand physical symptoms are not dangerous.'),
        ('5', 'Began interoceptive exposure — spun in chair, breathing through straw. High anxiety initially but habituated within session. Great work.'),
        ('10', 'First in vivo exposure — entered shopping centre for 10 minutes. Panic peaked at SUDS 7, dropped to 3. Huge milestone.'),
        ('15', 'Supermarket visit alone completed between sessions. No panic attack. Patient reports increased confidence. PRN medication use dropped to zero past 3 weeks.'),
        ('20', 'Near full remission. PDQ-A score 4 (was 28 at intake). Patient planning holiday abroad — first since onset.'),
        ('22', 'Termination session. Reviewed progress, consolidated relapse prevention plan. Patient tearful and grateful. Discussed open-door policy for future support.'),
    ]
    for i, (sn, content) in enumerate(archive_notes):
        session_offset_weeks = 22 - (i * 4) + 8
        appt_date = (today - timedelta(weeks=session_offset_weeks)).strftime('%Y-%m-%d')
        db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                        cost, duration_minutes, status, meeting_type)
                      VALUES (?, ?, '09:00', 350, 50, 'completed', 'in-person')""",
                   (archived_id, appt_date))
        appt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""INSERT INTO notes (patient_id, appointment_id, session_number, content)
                      VALUES (?, ?, ?, ?)""",
                   (archived_id, appt_id, sn, content))
        db.execute("INSERT INTO receipts (patient_id, amount, description, created_at) VALUES (?, 350, 'Session payment', ?)",
                   (archived_id, appt_date))


@admin_bp.route('/admin/seed_data', methods=('POST',))
@login_required
def seed_data():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    from app import init_db
    init_db()
    db = get_db()
    existing_service_types = db.execute("SELECT COUNT(*) AS count FROM service_types").fetchone()['count']
    if existing_service_types == 0:
        for name, desc, price in [
            ('Initial Assessment', 'Comprehensive initial evaluation session', 350.0),
            ('Individual Therapy', 'Standard one-on-one therapy session', 250.0),
            ('Family Therapy', 'Family therapy session', 300.0),
            ('Group Therapy', 'Group therapy session per participant', 150.0),
            ('Crisis Intervention', 'Urgent crisis counseling session', 400.0),
            ('Telehealth Session', 'Remote video therapy session', 200.0),
            ('Psychiatric Evaluation', 'Medication assessment and management', 500.0),
            ('Report Writing', 'Psychological report or letter', 150.0),
        ]:
            db.execute('INSERT INTO service_types (name, description, default_price) VALUES (?, ?, ?)', (name, desc, price))
        db.commit()
    existing_total = db.execute("SELECT COUNT(*) AS count FROM patients").fetchone()['count']
    if existing_total > 0:
        flash('Patient records already exist in the database. Seed data was not added.', 'info')
        return redirect(url_for('patients'))
    try:
        today = datetime.now()
        admin_user = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        admin_id = admin_user['id'] if admin_user else None
        _seed_ongoing_patient(db, admin_id, today)
        _seed_candidate_patient(db, admin_id)
        _seed_waiting_patient(db, admin_id, today)
        _seed_archived_patient(db, today)
        db.commit()
        flash('Example patients created.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error seeding data: {str(e)}', 'error')
    return redirect(url_for('patients'))


@admin_bp.route('/admin/reset_test_patients', methods=('POST',))
@login_required
def reset_test_patients():
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    if (request.form.get('confirm') or '').strip().upper() != 'RESET':
        flash('Type RESET to confirm test-patient reset.', 'error')
        return redirect(url_for('admin_dashboard'))

    from app import init_db
    init_db()
    db = get_db()

    for table in (
        'patient_resources', 'diagnosis_documents', 'supervisions', 'goals', 'audit_logs',
        'group_session_attendance', 'group_member_history', 'group_members', 'group_sessions', 'groups',
        'messages', 'appointments', 'receipts', 'files', 'notes', 'patient_logs'
    ):
        db.execute(f'DELETE FROM {table}')

    db.execute("DELETE FROM users WHERE role = 'patient'")
    db.execute('DELETE FROM patients')

    treatment_options = [
        row['label'] for row in db.execute(
            'SELECT label FROM treatment_method_options ORDER BY display_order ASC, id ASC'
        ).fetchall()
    ]
    if not treatment_options:
        treatment_options = ['Psychodynamic', 'CBT', 'EFT', 'Management']

    sample_specs = [
        ('Neta Private', 'ongoing', 'private', treatment_options[0 % len(treatment_options)]),
        ('Avi Residency', 'candidate', 'residency', treatment_options[1 % len(treatment_options)]),
        ('Maya Group', 'ongoing', 'group', treatment_options[2 % len(treatment_options)]),
        ('Roi Intake', 'candidate', 'initial-intake', treatment_options[3 % len(treatment_options)]),
        ('Dana Diagnosee', 'archived', 'diagnosee', treatment_options[0 % len(treatment_options)]),
    ]

    seeded_patient_ids = {}

    for index, (name, status, patient_type, method) in enumerate(sample_specs, start=1):
        has_intake = 1 if patient_type in ('initial-intake', 'diagnosee') else 0
        db.execute(
            '''INSERT INTO patients (name, status, email, phone, patient_type, has_intake_tab, treatment_method, background, can_self_schedule)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                name,
                status,
                f'test{index}@example.com',
                f'050-00000{index}',
                patient_type,
                has_intake,
                method,
                'Seeded sample record for layout and workflow checks.',
                1 if patient_type in ('private', 'group') else 0
            )
        )
        patient_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        seeded_patient_ids[patient_type] = patient_id

        db.execute(
            'INSERT INTO notes (patient_id, session_number, content, key_topics) VALUES (?, ?, ?, ?)',
            (patient_id, str(index), 'Initial seeded treatment log entry.', 'seed,workflow')
        )
        db.execute(
            'INSERT INTO patient_logs (patient_id, encounter_date, title, content) VALUES (?, ?, ?, ?)',
            (patient_id, datetime.now().date().isoformat(), 'Seed Encounter', 'Seeded non-therapy encounter note.')
        )

        if patient_type != 'archived':
            db.execute(
                '''INSERT INTO appointments (patient_id, appointment_date, appointment_time, status, meeting_type, cost)
                   VALUES (?, ?, ?, 'scheduled', 'in-person', 300)''',
                (patient_id, (datetime.now().date() + timedelta(days=index)).isoformat(), '10:00')
            )

        if index <= 3:
            username = f'test_patient_{index}'
            db.execute(
                'INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, ?, ?)',
                (username, generate_password_hash('patient123'), 'patient', patient_id)
            )

    group_patient_id = seeded_patient_ids.get('group')
    if group_patient_id:
        db.execute(
            'INSERT INTO groups (name, group_type, description) VALUES (?, ?, ?)',
            ('Sunday Skills Group', 'therapy', 'Seeded sample therapy group for UI and workflow validation.')
        )
        group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        joined_on = datetime.now().date().isoformat()
        db.execute(
            'INSERT INTO group_members (group_id, patient_id, joined_at, role) VALUES (?, ?, ?, ?)',
            (group_id, group_patient_id, joined_on, 'member')
        )
        db.execute(
            'INSERT INTO group_member_history (group_id, patient_id, joined_at, role) VALUES (?, ?, ?, ?)',
            (group_id, group_patient_id, joined_on, 'member')
        )

        past_session_date = (datetime.now().date() - timedelta(days=7)).isoformat()
        next_session_date = (datetime.now().date() + timedelta(days=7)).isoformat()
        db.execute(
            '''INSERT INTO group_sessions (group_id, session_date, session_time, duration_minutes, title, facilitator, meeting_type, status)
               VALUES (?, ?, '18:00', 90, ?, ?, 'in-person', 'completed')''',
            (group_id, past_session_date, 'Sunday Skills Circle', 'Dr. Lior Aloni')
        )
        past_session_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute(
            '''INSERT INTO group_session_attendance (session_id, patient_id, attendance_status, attendance_note)
               VALUES (?, ?, 'present', ?)''',
            (past_session_id, group_patient_id, 'Seeded attendance sample for group workflow checks.')
        )
        db.execute(
            '''INSERT INTO group_sessions (group_id, session_date, session_time, duration_minutes, title, facilitator, meeting_type, status)
               VALUES (?, ?, '18:00', 90, ?, ?, 'in-person', 'scheduled')''',
            (group_id, next_session_date, 'Sunday Skills Circle', 'Dr. Lior Aloni')
        )

    db.commit()
    flash('Test patients reset successfully: compact examples for private, residency, group, intake, and diagnosee workflows.', 'success')
    return redirect(url_for('crm_dashboard'))


# ---------------------------------------------------------------------------
# Calendar import
# ---------------------------------------------------------------------------

@admin_bp.route('/api/admin/import_calendar', methods=('POST',))
@login_required
def import_calendar():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    file = request.files.get('file')
    if not file:
        return jsonify({'status': 'error', 'message': 'No file uploaded.'}), 400
    try:
        content = file.read().decode('utf-8-sig')
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({'status': 'error', 'message': 'Invalid JSON file.'}), 400
    if not isinstance(data, list):
        data = [data]
    imported = 0
    errors = []
    for idx, entry in enumerate(data):
        patient_name = (entry.get('patient_name') or '').strip()
        if not patient_name:
            errors.append(f'Row {idx}: missing patient_name')
            continue
        patient = db.execute(
            "SELECT id FROM patients WHERE name = ? AND COALESCE(is_deleted, 0) = 0",
            (patient_name,)).fetchone()
        if not patient:
            errors.append(f'Row {idx}: patient "{patient_name}" not found')
            continue
        if not entry.get('appointment_date') or not entry.get('appointment_time'):
            errors.append(f'Row {idx}: missing date or time')
            continue
        try:
            db.execute('''INSERT INTO appointments
                (patient_id, appointment_date, appointment_time, duration_minutes, meeting_type,
                 meeting_link, meeting_title, is_recurring, recurrence_interval, recurrence_days,
                 recurrence_end_date, recurrence_count, cost, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (patient['id'], entry['appointment_date'], entry['appointment_time'],
                 int(entry.get('duration_minutes', 60)), entry.get('meeting_type', 'in-person'),
                 entry.get('meeting_link'), entry.get('meeting_title'),
                 int(entry.get('is_recurring', 0)), entry.get('recurrence_interval'),
                 entry.get('recurrence_days'), entry.get('recurrence_end_date'),
                 entry.get('recurrence_count'), float(entry.get('cost', 0)),
                 entry.get('status', 'scheduled')))
            imported += 1
        except Exception as e:
            errors.append(f'Row {idx}: {str(e)}')
    db.commit()
    return jsonify({'status': 'success', 'imported': imported, 'errors': errors})


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/search')
@login_required
def admin_global_search():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    q = (request.args.get('q') or '').strip()
    results = {'patients': [], 'notes': [], 'appointments': []}
    if len(q) < 2:
        return render_template('admin_global_search.html', query=q, results=results)
    db = get_db()
    like = f'%{q}%'
    results['patients'] = db.execute('''
        SELECT id, name, status, patient_type
        FROM patients WHERE COALESCE(is_deleted, 0) = 0
          AND (name LIKE ? OR email LIKE ? OR phone LIKE ?)
        ORDER BY CASE status WHEN 'ongoing' THEN 1 WHEN 'candidate' THEN 2
                    WHEN 'waiting' THEN 3 WHEN 'archived' THEN 4 ELSE 5 END,
                 name COLLATE NOCASE ASC LIMIT 20
    ''', (like, like, like)).fetchall()
    results['notes'] = db.execute('''
        SELECT n.id, n.note_date, n.content, n.key_topics, n.session_number,
               n.patient_id, p.name AS patient_name
        FROM notes n JOIN patients p ON n.patient_id = p.id
        WHERE COALESCE(p.is_deleted, 0) = 0
          AND (n.content LIKE ? OR n.key_topics LIKE ? OR n.behavior_notes LIKE ? OR n.mood_summary LIKE ?)
        ORDER BY n.created_at DESC LIMIT 20
    ''', (like, like, like, like)).fetchall()
    results['appointments'] = db.execute('''
        SELECT a.id, a.appointment_date, a.appointment_time, a.meeting_title,
               a.meeting_type, a.status, a.missed_reason, a.patient_id, p.name AS patient_name
        FROM appointments a JOIN patients p ON a.patient_id = p.id
        WHERE COALESCE(p.is_deleted, 0) = 0
          AND (a.meeting_title LIKE ? OR a.meeting_type LIKE ? OR a.missed_reason LIKE ? OR a.meeting_link LIKE ?)
        ORDER BY a.appointment_date DESC LIMIT 20
    ''', (like, like, like, like)).fetchall()
    return render_template('admin_global_search.html', query=q, results=results)


# ---------------------------------------------------------------------------
# Cancel request management
# ---------------------------------------------------------------------------

@admin_bp.route('/cancel_requests')
@login_required
def list_cancel_requests():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    from clinic_app.utils import combine_dt
    requests = db.execute('''
        SELECT cr.id, cr.appointment_id, cr.reason, cr.created_at AS requested_at, cr.status,
               a.appointment_date, a.appointment_time, a.meeting_type,
               p.id AS patient_id, p.name AS patient_name
        FROM cancel_requests cr
        JOIN appointments a ON a.id = cr.appointment_id
        JOIN patients p ON p.id = a.patient_id
        WHERE cr.status = 'pending'
        ORDER BY cr.created_at ASC
    ''').fetchall()
    return render_template('cancel_requests.html', requests=requests)


@admin_bp.route('/cancel_requests/<int:request_id>/approve', methods=['POST'])
@login_required
def approve_cancel_request(request_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    req = db.execute('''
        SELECT cr.*, a.patient_id, a.appointment_date, a.appointment_time
        FROM cancel_requests cr
        JOIN appointments a ON a.id = cr.appointment_id
        WHERE cr.id = ?
    ''', (request_id,)).fetchone()
    if not req:
        flash('Cancel request not found.')
        return redirect(url_for('.list_cancel_requests'))
    db.execute('UPDATE cancel_requests SET status = \'approved\', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?', (current_user.id, request_id,))
    db.execute('UPDATE appointments SET status = ? WHERE id = ?', ('cancelled', req['appointment_id']))
    db.commit()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (req['patient_id'],)).fetchone()
    if patient:
        appt = db.execute('SELECT * FROM appointments WHERE id = ?', (req['appointment_id'],)).fetchone()
        if appt:
            from app import _notify_patient_appointment_change
            _notify_patient_appointment_change('cancelled', db, appt, patient)
    flash('Cancellation approved.')
    return redirect(url_for('.list_cancel_requests'))


@admin_bp.route('/cancel_requests/<int:request_id>/reject', methods=['POST'])
@login_required
def reject_cancel_request(request_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    db.execute('UPDATE cancel_requests SET status = \'rejected\', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?', (current_user.id, request_id,))
    db.commit()
    flash('Cancellation rejected.')
    return redirect(url_for('.list_cancel_requests'))


# ---------------------------------------------------------------------------
# Google Docs auto-sync
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/google-docs/auto-sync-now', methods=['POST'])
@login_required
def google_docs_auto_sync_now():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    from flask import current_app
    if current_app.config.get('TESTING'):
        db = get_db()
        from app import _GDOC_AUTO_SYNC_LOCK, _run_google_docs_auto_sync
        with _GDOC_AUTO_SYNC_LOCK:
            result = _run_google_docs_auto_sync(db, force=True, trigger_source='manual')

        if not result.get('ran'):
            reason = result.get('reason')
            if reason == 'dependency':
                return jsonify({'error': '; '.join(result.get('errors') or ['Google dependencies unavailable'])}), 400
            if reason in {'no-targets', 'no-connected-targets'}:
                return jsonify({'error': 'No connected Google Docs are selected for automatic sync.'}), 400
            return jsonify({'error': 'Google Docs auto-sync is disabled or not due yet.'}), 400

        return jsonify({
            'status': 'ok',
            'run_status': result.get('status') or 'success',
            'synced': int(result.get('total_synced') or 0),
            'patients': int(result.get('synced_patients') or 0),
            'groups': int(result.get('synced_groups') or 0),
            'pushed_groups': int(result.get('pushed_groups') or 0),
            'targets_total': int(result.get('targets_total') or 0),
            'targets_processed': int(result.get('targets_processed') or 0),
            'errors': result.get('errors') or [],
            'warnings': result.get('warnings') or [],
            'history_id': result.get('history_id'),
            'message': f"Synced {int(result.get('total_synced') or 0)} records from Google Docs.",
        })

    if not _gdocs:
        return jsonify({'error': 'Google Docs module not available.'}), 500
    db = get_db()
    try:
        from app import _create_manual_sync_job, _run_manual_google_docs_sync_job
        job_id, existing_id = _create_manual_sync_job(current_user.id)
        if not job_id and existing_id:
            return jsonify({'status': 'already_running', 'job_id': existing_id}), 409
        _run_manual_google_docs_sync_job(job_id)
        return jsonify({'status': 'triggered', 'job_id': job_id})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@admin_bp.route('/admin/google-docs/auto-sync-status/<job_id>', methods=['GET'])
@login_required
def google_docs_auto_sync_status(job_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        from app import _snapshot_manual_sync_job
        return jsonify(_snapshot_manual_sync_job(job_id))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# Admin profile
# ---------------------------------------------------------------------------


@admin_bp.route('/admin/profile', methods=['GET', 'POST'])
@login_required
def admin_profile():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    admin = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    if admin is None:
        return "Admin not found", 404

    from app import get_site_settings, _list_connected_google_docs, _get_google_docs_auto_sync_state
    from app import _get_recent_gdocs_sync_history, _get_gdocs_auto_sync_health
    from app import list_encrypted_backups, _admin_totp_uri, DEFAULT_SITE_SETTINGS
    from app import GDOC_AUTO_SYNC_INTERVAL_SECONDS, GDOC_AUTO_SYNC_GROUP_MODES
    from app import save_site_settings, _parse_gdoc_target_key, _format_gdoc_target_key

    if request.method == 'POST':
        display_name = request.form.get('display_name') if 'display_name' in request.form else (admin['display_name'] or admin['username'])
        email = request.form.get('email') if 'email' in request.form else admin['email']
        phone = request.form.get('phone') if 'phone' in request.form else admin['phone']
        id_number = request.form.get('id_number') if 'id_number' in request.form else admin['id_number']
        birth_date = request.form.get('birth_date') if 'birth_date' in request.form else admin['birth_date']

        display_name = (display_name or '').strip() or admin['username']
        email = (email or '').strip() or None
        phone = (phone or '').strip() or None
        id_number = (id_number or '').strip() or None
        birth_date = birth_date or None

        db.execute('''
            UPDATE users
            SET display_name = ?, email = ?, phone = ?, id_number = ?, birth_date = ?
            WHERE id = ?
        ''', (display_name, email, phone, id_number, birth_date, current_user.id))

        selected_sync_targets = []
        selected_sync_targets_config = []
        for raw_target in request.form.getlist('gdoc_sync_targets'):
            target_type, target_id = _parse_gdoc_target_key(raw_target)
            if not target_type:
                continue
            target_key = _format_gdoc_target_key(target_type, target_id)
            if target_key and target_key not in selected_sync_targets:
                selected_sync_targets.append(target_key)
                target_mode = (request.form.get(f'gdoc_sync_mode::{target_key}') or 'pull').strip().lower()
                if target_type == 'group':
                    target_mode = target_mode if target_mode in GDOC_AUTO_SYNC_GROUP_MODES else 'pull'
                else:
                    target_mode = 'pull'
                selected_sync_targets_config.append({'target_key': target_key, 'mode': target_mode})

        selected_interval = (request.form.get('gdocs_auto_sync_interval') or 'daily').strip().lower()
        if selected_interval not in GDOC_AUTO_SYNC_INTERVAL_SECONDS:
            selected_interval = 'daily'

        if any(key in request.form for key in DEFAULT_SITE_SETTINGS.keys()) or 'gdoc_sync_targets' in request.form:
            save_site_settings(db, {
                'about_enabled': '1' if request.form.get('about_enabled') else '0',
                'about_phone': (request.form.get('about_phone') or '').strip(),
                'about_email': (request.form.get('about_email') or '').strip(),
                'about_text': (request.form.get('about_text') or '').strip(),
                'about_map_url': (request.form.get('about_map_url') or '').strip(),
                'questionnaires_source_sheet_url': (request.form.get('questionnaires_source_sheet_url') or '').strip(),
                'gdocs_auto_sync_enabled': '1' if request.form.get('gdocs_auto_sync_enabled') else '0',
                'gdocs_auto_sync_interval': selected_interval,
                'gdocs_auto_sync_targets_json': json.dumps(selected_sync_targets),
                'gdocs_auto_sync_targets_config_json': json.dumps(selected_sync_targets_config),
            })

        db.commit()
        flash('Admin profile updated.')
        return redirect(url_for('.admin_profile'))

    site_settings = get_site_settings(db)
    try:
        raw_enabled_integrations = json.loads(site_settings.get('google_enabled_integrations') or '["calendar","docs","sheets"]')
        if not isinstance(raw_enabled_integrations, list):
            raise ValueError('enabled integrations must be a list')
    except (ValueError, TypeError, json.JSONDecodeError):
        raw_enabled_integrations = ['calendar', 'docs', 'sheets']

    valid_integrations = {'calendar', 'docs', 'sheets'}
    enabled_integrations = [key for key in raw_enabled_integrations if key in valid_integrations]

    google_calendar_ui = {
        'google_libs': bool(_gcal and getattr(_gcal, 'GOOGLE_LIBS_AVAILABLE', False)),
        'client_configured': False,
        'connected': False,
        'calendar_id': None,
        'calendars': [],
        'enabled_integrations': enabled_integrations,
        'error': None,
    }

    if _gcal:
        try:
            google_calendar_ui['client_configured'] = bool(_gcal._client_secrets_available())
            if google_calendar_ui['client_configured']:
                google_calendar_ui['connected'] = bool(_gcal.is_connected(db))
                if google_calendar_ui['connected']:
                    calendar_id_raw = _gcal.get_calendar_id(db)
                    google_calendar_ui['calendar_id'] = str(calendar_id_raw) if calendar_id_raw is not None else None
                    calendars_raw = _gcal.list_calendars(db)
                    google_calendar_ui['calendars'] = calendars_raw if isinstance(calendars_raw, list) else []
        except Exception as exc:
            google_calendar_ui['error'] = str(exc)

    backup_files = list_encrypted_backups()
    pending_secret = session.get('pending_totp_secret')
    pending_created_at = session.get('pending_totp_created_at', 0)
    if pending_secret and (datetime.utcnow().timestamp() - pending_created_at) > 600:
        session.pop('pending_totp_secret', None)
        session.pop('pending_totp_uri', None)
        session.pop('pending_totp_created_at', None)
        pending_secret = None
    totp_uri = _admin_totp_uri(admin, pending_secret) if pending_secret else None
    connected_google_docs = _list_connected_google_docs(db)
    gdocs_auto_sync_state = _get_google_docs_auto_sync_state(db, connected_docs=connected_google_docs)
    gdocs_sync_history = _get_recent_gdocs_sync_history(db, limit=12)
    gdocs_auto_sync_health = _get_gdocs_auto_sync_health(db)
    smtp_health = _smtp_health_check()
    recent_auth_events = db.execute(
        '''
        SELECT action, details, created_at
        FROM audit_logs
        WHERE action LIKE 'auth_%'
        ORDER BY created_at DESC
        LIMIT 8
        '''
    ).fetchall()
    recovery_codes = session.pop('mfa_recovery_codes', None)
    return render_template(
        'admin_profile.html',
        admin=admin,
        backup_files=backup_files,
        pending_totp_secret=pending_secret,
        totp_uri=totp_uri,
        site_settings=site_settings,
        google_calendar_ui=google_calendar_ui,
        connected_google_docs=connected_google_docs,
        gdocs_auto_sync_state=gdocs_auto_sync_state,
        gdocs_sync_history=gdocs_sync_history,
        gdocs_auto_sync_health=gdocs_auto_sync_health,
        smtp_health=smtp_health,
        recent_auth_events=recent_auth_events,
        totp_qr_url=f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote(totp_uri)}" if totp_uri else None,
        recovery_codes=recovery_codes
    )


@admin_bp.route('/admin/smtp/health', methods=['GET'])
@login_required
def admin_smtp_health():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    health = _smtp_health_check()
    return jsonify({
        'status': 'ok' if health.get('ok') else 'error',
        'configured': bool(health.get('configured')),
        'smtp_ok': bool(health.get('ok')),
        'message': health.get('message') or '',
    })


@admin_bp.route('/admin/security-log')
@login_required
def admin_security_log():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    action_filter = request.args.get('action', '')
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    where_clauses = []
    params = []
    if action_filter:
        where_clauses.append('al.action = ?')
        params.append(action_filter)
    if search:
        where_clauses.append('(al.action LIKE ? OR al.details LIKE ?)')
        like_val = f'%{search}%'
        params.append(like_val)
        params.append(like_val)
    where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
    total = db.execute(f'SELECT COUNT(*) AS cnt FROM audit_logs al {where_sql}', params).fetchone()['cnt']
    total_pages = max(1, (total + per_page - 1) // per_page)
    events = db.execute(f'''
        SELECT al.id, al.action, al.details, al.created_at,
               p.name AS patient_name, p.id AS patient_id
        FROM audit_logs al
        LEFT JOIN patients p ON p.id = al.patient_id
        {where_sql}
        ORDER BY al.created_at DESC
        LIMIT ? OFFSET ?
    ''', params + [per_page, offset]).fetchall()
    action_names = [r['action'] for r in db.execute('SELECT DISTINCT action FROM audit_logs ORDER BY action').fetchall()]
    from app import get_site_settings
    site_settings = get_site_settings(db)
    scan_results = {}
    results_raw = site_settings.get('security_scan_last_results_json')
    if results_raw:
        try:
            scan_results = json.loads(results_raw)
        except Exception:
            pass
    return render_template('admin_security_log.html',
                           events=events, action_filter=action_filter, page=page, search=search,
                           total=total, total_pages=total_pages, action_names=action_names,
                           site_settings=site_settings, scan_results=scan_results)



@admin_bp.route('/admin/security/scan-now', methods=['POST'])
@login_required
def admin_security_scan_now():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    from app import _run_automated_security_scan
    try:
        res = _run_automated_security_scan(db, force=True)
        db.commit()
        if res.get('ran'):
            status = res['results']['status']
            if status == 'ok':
                flash('Security scan completed successfully. No issues found!')
            elif status == 'warning':
                flash('Security scan completed with warnings. Review findings below.', 'warning')
            else:
                flash('Security scan completed. High severity issues found!', 'error')
        else:
            flash('Security scan failed to run.', 'error')
    except Exception as exc:
        flash(f'Security scan failed: {exc}', 'error')
    return redirect(url_for('.admin_security_log'))


@admin_bp.route('/admin/security/save-settings', methods=['POST'])
@login_required
def admin_security_save_settings():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    from app import save_site_settings
    enabled = '1' if request.form.get('security_scan_enabled') else '0'
    interval = request.form.get('security_scan_interval') or 'daily'
    save_site_settings(db, {
        'security_scan_enabled': enabled,
        'security_scan_interval': interval,
    })
    db.commit()
    flash('Security scan settings updated successfully.')
    return redirect(url_for('.admin_security_log'))



@admin_bp.route('/admin/security-log/export')
@login_required
def admin_security_log_export():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    logs = db.execute('''
        SELECT al.id, al.action, al.details, al.created_at,
               p.name AS patient_name
        FROM audit_logs al
        LEFT JOIN patients p ON p.id = al.patient_id
        ORDER BY al.created_at DESC
    ''').fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'action', 'details', 'created_at', 'patient_name'])
    for log in logs:
        writer.writerow([log['id'], log['action'], log['details'], log['created_at'], log['patient_name']])
    csv_content = '\ufeff' + output.getvalue()
    response = Response(csv_content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename=security_log_{datetime.now().strftime("%Y%m%d")}.csv'
    return response


@admin_bp.route('/admin/smtp/test', methods=['POST'])
@login_required
def admin_smtp_test():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    recipient = (request.form.get('test_email') or '').strip()
    if not recipient:
        return jsonify({'ok': False, 'message': 'Test email address is required.'})
    success, msg = _send_smtp_email(recipient, 'SMTP Test from Private Clinic', 'This is a test email from your clinic management system.')
    return jsonify({'ok': success, 'message': msg})


@admin_bp.route('/admin/setup_authenticator', methods=['POST'])
@login_required
def setup_authenticator():
    if current_user.role not in ('admin', 'patient'):
        return "Unauthorized", 403
    action = request.form.get('action', '')
    code = (request.form.get('code') or request.form.get('otp_code') or '').strip()
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    
    # Helper to check if client expects JSON response
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    redirect_url = url_for('.admin_profile') if current_user.role == 'admin' else url_for('patient_settings')

    if action == 'generate' or action == 'start':
        secret = pyotp.random_base32()
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user['username'], issuer_name='Private Clinic')
        session['pending_totp_secret'] = secret
        session['pending_totp_uri'] = totp_uri
        session['pending_totp_created_at'] = time.time()
        if wants_json:
            return jsonify({'secret': secret, 'uri': totp_uri})
        return redirect(redirect_url)
        
    elif action == 'verify':
        secret = session.get('pending_totp_secret')
        if not secret:
            if wants_json:
                return jsonify({'ok': False, 'message': 'No pending secret. Generate one first.'})
            flash('No pending secret. Generate one first.', 'error')
            return redirect(redirect_url)
        if not code:
            if wants_json:
                return jsonify({'ok': False, 'message': 'Verification code is required.'})
            flash('Verification code is required.', 'error')
            return redirect(redirect_url)
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            if wants_json:
                return jsonify({'ok': False, 'message': 'Invalid code. Try again.'})
            flash('Invalid code. Try again.', 'error')
            return redirect(redirect_url)
            
        session.pop('pending_totp_secret', None)
        session.pop('pending_totp_uri', None)
        
        # Generate 5 recovery codes
        import secrets
        raw_codes = [secrets.token_hex(4) for _ in range(5)]
        from werkzeug.security import generate_password_hash
        hashed_codes = [generate_password_hash(c) for c in raw_codes]
        
        db.execute(
            'UPDATE users SET totp_secret = ?, totp_enabled = 1, totp_recovery_codes = ? WHERE id = ?',
            (secret, json.dumps(hashed_codes), current_user.id)
        )
        db.commit()
        
        # Store in session to display once to user on redirect
        session['mfa_recovery_codes'] = raw_codes
        
        if wants_json:
            return jsonify({'ok': True, 'recovery_codes': raw_codes})
        flash('Authenticator verified successfully.')
        return redirect(redirect_url)
        
    elif action == 'disable':
        db.execute('UPDATE users SET totp_secret = NULL, totp_enabled = 0, totp_recovery_codes = NULL, session_version = COALESCE(session_version, 0) + 1 WHERE id = ?', (current_user.id,))
        db.commit()
        flash('Two-factor authentication disabled.')
        return redirect(redirect_url)
        
    if wants_json:
        return jsonify({'ok': False, 'message': 'Unknown action.'})
    return redirect(redirect_url)



@admin_bp.route('/admin/questionnaires/options')
@login_required
def admin_questionnaire_options():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    from app import _list_questionnaire_tabs
    tabs, err = _list_questionnaire_tabs(db)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({'status': 'ok', 'options': [item['title'] for item in tabs]})


@admin_bp.route('/admin/change_password', methods=['POST'])
@login_required
def admin_change_password():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')
    if not current_pw or not new_pw or not confirm_pw:
        flash('All password fields are required.')
        return redirect(url_for('.admin_profile'))
    if new_pw != confirm_pw:
        flash('New passwords do not match.')
        return redirect(url_for('.admin_profile'))
    from clinic_app.utils import _validate_password_strength
    valid, msg = _validate_password_strength(new_pw)
    if not valid:
        flash(msg)
        return redirect(url_for('.admin_profile'))
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    if not check_password_hash(user['password_hash'], current_pw):
        flash('Current password is incorrect.')
        return redirect(url_for('.admin_profile'))
    db.execute('UPDATE users SET password_hash = ?, force_password_change = 0, session_version = COALESCE(session_version, 0) + 1 WHERE id = ?',
               (generate_password_hash(new_pw), current_user.id))
    db.commit()
    current_user.session_version += 1
    flash('Password updated successfully.')
    return redirect(url_for('.admin_profile'))


@admin_bp.route('/admin/backup_now', methods=['POST'])
@login_required
def admin_backup_now():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        from flask import current_app
        from clinic_app.backup import perform_encrypted_backup
        db_path = current_app.config.get('DATABASE')
        result = perform_encrypted_backup(db_path)
        return jsonify({'status': 'success', 'path': str(result)})
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@admin_bp.route('/admin/restore_backup', methods=['POST'])
@login_required
def admin_restore_backup():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    backup_file = (request.form.get('backup_file') or '').strip()
    if not backup_file:
        return jsonify({'status': 'error', 'message': 'Backup file path is required.'}), 400
    from app import BACKUP_DIR
    backup_path = os.path.join(BACKUP_DIR, backup_file)
    if not os.path.exists(backup_path):
        backup_path = backup_file
        if not os.path.exists(backup_path):
            return jsonify({'status': 'error', 'message': f'Backup file not found: {backup_file}'}), 400
    try:
        from app import _perform_restore
        result = _perform_restore(backup_path)
        flash(f'Restore completed successfully. Restored {result["tables_restored"]} tables.')
    except Exception as exc:
        flash(f'Restore failed: {exc}', 'error')
    return redirect(url_for('.admin_profile'))


@admin_bp.route('/admin/resources', methods=['GET', 'POST'])
@login_required
def manage_resources():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('manage_resources'))
        description = request.form.get('description', '')
        url = request.form.get('url', '')
        is_public = 1 if request.form.get('is_public') else 0
        allow_patient_view = 1 if request.form.get('allow_patient_view') else 0
        allow_patient_download = 1 if request.form.get('allow_patient_download') else 0

        db.execute(
            'INSERT INTO resources (title, description, url, is_public, allow_patient_view, allow_patient_download) VALUES (?, ?, ?, ?, ?, ?)',
            (title, description, url, is_public, allow_patient_view, allow_patient_download)
        )
        db.commit()
        flash('Resource added.')
        return redirect(url_for('.manage_resources'))

    resources = db.execute('SELECT * FROM resources ORDER BY created_at DESC LIMIT 200').fetchall()
    return render_template('manage_resources.html', resources=resources)


@admin_bp.route('/admin/resources/<int:resource_id>/edit', methods=['POST'])
@login_required
def edit_resource(resource_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Title is required.')
        return redirect(url_for('.manage_resources'))
    description = request.form.get('description', '')
    url = request.form.get('url', '')
    is_public = 1 if request.form.get('is_public') else 0
    allow_patient_view = 1 if request.form.get('allow_patient_view') else 0
    allow_patient_download = 1 if request.form.get('allow_patient_download') else 0
    db = get_db()
    db.execute(
        'UPDATE resources SET title=?, description=?, url=?, is_public=?, allow_patient_view=?, allow_patient_download=? WHERE id=?',
        (title, description, url, is_public, allow_patient_view, allow_patient_download, resource_id)
    )
    db.commit()
    flash('Resource updated.')
    return redirect(url_for('.manage_resources'))


@admin_bp.route('/admin/resources/<int:resource_id>/delete', methods=['POST'])
@login_required
def delete_resource(resource_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    db.execute('DELETE FROM patient_resources WHERE resource_id = ?', (resource_id,))
    db.execute('DELETE FROM resources WHERE id = ?', (resource_id,))
    db.commit()
    flash('Resource deleted.')
    return redirect(url_for('.manage_resources'))


@admin_bp.route('/patient/<int:patient_id>/unassign_resource/<int:resource_id>', methods=['POST'])
@login_required
def unassign_resource(patient_id, resource_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    db.execute('DELETE FROM patient_resources WHERE patient_id = ? AND resource_id = ?', (patient_id, resource_id))
    db.commit()
    flash('Resource unassigned.')
    return redirect_to_patient_tab(patient_id, 'info')


@admin_bp.route('/patient/<int:patient_id>/assign_resource', methods=['POST'])
@login_required
def assign_resource(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    resource_id = (request.form.get('resource_id') or '').strip()
    if not resource_id:
        flash('No resource selected.', 'error')
        return redirect(request.referrer or url_for('crm_dashboard'))
    if resource_id:
        db = get_db()
        try:
            db.execute('INSERT INTO patient_resources (patient_id, resource_id) VALUES (?, ?)', (patient_id, resource_id))
            db.commit()
            flash('Resource assigned to patient.')
        except sqlite3.IntegrityError:
            flash('Resource already assigned to this patient.')

    return redirect_to_patient_tab(patient_id, 'info')


@admin_bp.route('/admin/google-setup')
@login_required
def google_setup():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    from app import gcal, build_external_public_url, get_site_settings
    db = get_db()
    settings = get_site_settings(db)
    try:
        enabled_integrations = json.loads(settings.get('google_enabled_integrations') or '["calendar","docs","sheets"]')
    except (ValueError, TypeError):
        enabled_integrations = ['calendar', 'docs', 'sheets']
    redirect_uri = build_external_public_url('google_calendar.google_calendar_callback')
    client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    client_secret_set = bool(os.environ.get('GOOGLE_CLIENT_SECRET', ''))
    libs_available = gcal is not None and getattr(gcal, 'GOOGLE_LIBS_AVAILABLE', False)
    connected = False
    if gcal:
        try:
            connected = bool(gcal.is_connected(db))
        except Exception:
            pass
    return render_template('google_setup.html',
        redirect_uri=redirect_uri,
        client_id=client_id,
        client_secret_set=client_secret_set,
        libs_available=libs_available,
        connected=connected,
        enabled_integrations=enabled_integrations)


@admin_bp.route('/admin/profile/name', methods=('POST',))
@login_required
def admin_profile_name():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    new_name = (request.form.get('display_name') or '').strip()
    if new_name:
        db = get_db()
        db.execute('UPDATE users SET display_name = ? WHERE id = ?', (new_name, current_user.id))
        db.commit()
        flash('Display name updated.')
    return redirect(url_for('.admin_profile'))


@admin_bp.route('/admin/email-settings')
@login_required
def admin_email_settings():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    count = db.execute('SELECT COUNT(*) AS cnt FROM email_reminder_templates').fetchone()['cnt']
    if count == 0:
        defaults = [
            ('appointment_reminder', 24,
             'Appointment Reminder: {{ patient_name }} on {{ date }}',
             'Hello {{ patient_name }},\n\nThis is a reminder about your upcoming appointment:\n'
             '  Date: {{ date }}\n  Time: {{ time }}\n  Type: {{ meeting_type }}\n'
             'Join link: {{ meeting_link }}\n\n'
             'If you need to reschedule or cancel, please contact the clinic.\n\n{{ clinic_name }}'),
            ('appointment_cancelled', 0,
             'Appointment Cancelled: {{ patient_name }} on {{ date }}',
             'Hello {{ patient_name }},\n\nYour appointment scheduled for {{ date }} at {{ time }} has been cancelled.\n\n'
             'If you have any questions, please contact the clinic.\n\n{{ clinic_name }}'),
            ('appointment_rescheduled', 0,
             'Appointment Rescheduled: {{ patient_name }} on {{ date }}',
             'Hello {{ patient_name }},\n\nYour appointment has been rescheduled:\n'
             '  New Date: {{ date }}\n  New Time: {{ time }}\n  Type: {{ meeting_type }}\n'
             'Join link: {{ meeting_link }}\n\n'
             'If this does not work for you, please contact the clinic.\n\n{{ clinic_name }}'),
            ('new_appointment', 0,
             'New Appointment Confirmed: {{ patient_name }} on {{ date }}',
             'Hello {{ patient_name }},\n\nYour appointment has been confirmed:\n'
             '  Date: {{ date }}\n  Time: {{ time }}\n  Type: {{ meeting_type }}\n'
             'Join link: {{ meeting_link }}\n\n'
             'Thank you,\n{{ clinic_name }}'),
        ]
        for et, hb, subj, body in defaults:
            db.execute(
                'INSERT OR IGNORE INTO email_reminder_templates (event_type, hours_before, subject_template, body_template, enabled) '
                'VALUES (?, ?, ?, ?, 1)', (et, hb, subj, body))
        db.commit()
    templates = db.execute('SELECT * FROM email_reminder_templates ORDER BY event_type').fetchall()
    incoming = db.execute('SELECT * FROM incoming_email ORDER BY created_at DESC LIMIT 50').fetchall()
    patients = db.execute('SELECT id, name, email FROM patients WHERE COALESCE(is_deleted, 0) = 0 AND COALESCE(email, "") <> "" ORDER BY name COLLATE NOCASE ASC').fetchall()
    smtp = _smtp_health_check()
    return render_template('email_settings.html',
        templates=templates, incoming=incoming, patients=patients, smtp_health=smtp)


@admin_bp.route('/admin/email-settings/save-template', methods=['POST'])
@login_required
def admin_email_settings_save_template():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    template_id = request.form.get('template_id', '').strip()
    event_type = (request.form.get('event_type') or '').strip()
    hours_before = float(request.form.get('hours_before') or 24)
    subject_template = (request.form.get('subject_template') or '').strip()
    body_template = request.form.get('body_template', '').strip()
    enabled = 1 if request.form.get('enabled') else 0

    if not event_type:
        flash('Event type is required.')
        return redirect(url_for('.admin_email_settings'))

    if template_id:
        db.execute('''UPDATE email_reminder_templates SET
            event_type=?, hours_before=?, subject_template=?, body_template=?, enabled=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?''', (event_type, hours_before, subject_template, body_template, enabled, template_id))
    else:
        db.execute('''INSERT OR REPLACE INTO email_reminder_templates
            (event_type, hours_before, subject_template, body_template, enabled)
            VALUES (?, ?, ?, ?, ?)''', (event_type, hours_before, subject_template, body_template, enabled))
    db.commit()
    flash('Reminder template saved.')
    return redirect(url_for('.admin_email_settings'))


@admin_bp.route('/admin/email-settings/template/<int:template_id>/toggle', methods=['POST'])
@login_required
def admin_email_settings_toggle_template(template_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    tpl = db.execute('SELECT enabled FROM email_reminder_templates WHERE id = ?', (template_id,)).fetchone()
    if not tpl:
        return jsonify({'error': 'Not found'}), 404
    new_val = 0 if tpl['enabled'] else 1
    db.execute('UPDATE email_reminder_templates SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (new_val, template_id))
    db.commit()
    return jsonify({'status': 'ok', 'enabled': bool(new_val)})


@admin_bp.route('/admin/email-settings/send-one-time', methods=['POST'])
@login_required
def admin_email_settings_send_one_time():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    from app import _send_smtp_email
    recipient = (request.form.get('recipient') or '').strip()
    subject = (request.form.get('subject') or '').strip()
    body = request.form.get('body', '').strip()

    if not recipient or not subject:
        flash('Recipient email and subject are required.')
        return redirect(url_for('.admin_email_settings'))

    success, msg = _send_smtp_email(recipient, subject, body, html_body=None)
    if success:
        flash(f'Email sent to {recipient}.')
    else:
        flash(f'Failed to send email: {msg}')
    return redirect(url_for('.admin_email_settings'))


@admin_bp.route('/admin/email-settings/incoming/<int:email_id>/read', methods=['POST'])
@login_required
def admin_email_settings_mark_read(email_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    db.execute('UPDATE incoming_email SET is_read = 1 WHERE id = ?', (email_id,))
    db.commit()
    return jsonify({'status': 'ok'})


@admin_bp.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'add':
            username = (request.form.get('username') or '').strip()
            display_name = (request.form.get('display_name') or '').strip()
            email = (request.form.get('email') or '').strip()
            phone = (request.form.get('phone') or '').strip()
            role = (request.form.get('role') or '').strip()
            password = request.form.get('password', '')

            if not username or not password:
                flash('Username and password are required.', 'error')
                return redirect(url_for('.admin_users'))
            if role not in ('admin', 'patient'):
                flash('Invalid role.', 'error')
                return redirect(url_for('.admin_users'))

            existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if existing:
                flash(f'Username "{username}" is already taken.', 'error')
                return redirect(url_for('.admin_users'))

            db.execute(
                'INSERT INTO users (username, display_name, email, phone, role, password_hash) VALUES (?, ?, ?, ?, ?, ?)',
                (username, display_name or username, email or None, phone or None, role, generate_password_hash(password))
            )
            db.commit()
            flash(f'User "{username}" created.', 'success')

        elif action == 'edit':
            user_id = request.form.get('user_id', type=int)
            display_name = (request.form.get('display_name') or '').strip()
            email = (request.form.get('email') or '').strip()
            phone = (request.form.get('phone') or '').strip()
            role = (request.form.get('role') or '').strip()

            if not user_id:
                flash('Missing user ID.', 'error')
                return redirect(url_for('.admin_users'))
            if role and role not in ('admin', 'patient'):
                flash('Invalid role.', 'error')
                return redirect(url_for('.admin_users'))

            db.execute(
                'UPDATE users SET display_name = ?, email = ?, phone = ?, role = ? WHERE id = ?',
                (display_name, email or None, phone or None, role, user_id)
            )
            db.commit()
            flash('User updated.', 'success')

        elif action == 'toggle-active':
            user_id = request.form.get('user_id', type=int)
            if not user_id:
                flash('Missing user ID.', 'error')
                return redirect(url_for('.admin_users'))
            if user_id == current_user.id:
                flash('Cannot disable your own account.', 'error')
                return redirect(url_for('.admin_users'))
            user = db.execute('SELECT id, is_active FROM users WHERE id = ?', (user_id,)).fetchone()
            if not user:
                flash('User not found.', 'error')
                return redirect(url_for('.admin_users'))
            new_state = 0 if user['is_active'] else 1
            db.execute('UPDATE users SET is_active = ? WHERE id = ?', (new_state, user_id))
            db.commit()
            status = 'enabled' if new_state else 'disabled'
            flash(f'User {status}.', 'success')

        elif action == 'reset-password':
            user_id = request.form.get('user_id', type=int)
            new_password = request.form.get('new_password', '')
            if not user_id or not new_password:
                flash('User ID and new password are required.', 'error')
                return redirect(url_for('.admin_users'))
            if len(new_password) < 4:
                flash('Password must be at least 4 characters.', 'error')
                return redirect(url_for('.admin_users'))
            db.execute(
                'UPDATE users SET password_hash = ?, force_password_change = 1, session_version = COALESCE(session_version, 0) + 1 WHERE id = ?',
                (generate_password_hash(new_password), user_id)
            )
            db.commit()
            flash('Password reset. User must change on next login.', 'success')

        return redirect(url_for('.admin_users'))

    users = db.execute(
        'SELECT id, username, display_name, email, phone, role, is_active, totp_enabled, created_at FROM users ORDER BY role, username'
    ).fetchall()
    return render_template('admin_users.html', users=users)


def _smtp_health_check():
    from clinic_app.utils import _smtp_health_check as _check
    return _check()
