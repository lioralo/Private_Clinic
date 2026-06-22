import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import g, current_app


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        database = current_app.config.get('DATABASE', 'clinic.db')
        db = g._database = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
    return db


def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def get_primary_admin_user(db):
    return db.execute(
        "SELECT * FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1"
    ).fetchone()


def get_site_settings(db=None):
    DEFAULT_SITE_SETTINGS = {
        'about_enabled': '0',
        'about_phone': '',
        'about_email': '',
        'about_text': '',
        'about_map_url': '',
        'questionnaires_source_sheet_url': '',
        'gdocs_auto_sync_enabled': '0',
        'gdocs_auto_sync_interval': 'daily',
        'gdocs_auto_sync_targets_json': '[]',
        'gdocs_auto_sync_targets_config_json': '[]',
        'gdocs_auto_sync_last_run_at': '',
        'google_enabled_integrations': '["calendar","docs","sheets"]',
    }
    settings = DEFAULT_SITE_SETTINGS.copy()
    try:
        active_db = db or get_db()
        rows = active_db.execute('SELECT setting_key, setting_value FROM site_settings').fetchall()
        for row in rows:
            key = row['setting_key']
            if key in settings:
                settings[key] = row['setting_value'] or ''
    except Exception:
        return settings
    settings['about_enabled'] = '1' if str(settings.get('about_enabled') or '0') in {'1', 'true', 'yes', 'on'} else '0'
    return settings


def save_site_settings(db, updates):
    if not updates:
        return
    _defaults = {
        'about_enabled': '0', 'about_phone': '', 'about_email': '', 'about_text': '', 'about_map_url': '',
        'questionnaires_source_sheet_url': '', 'gdocs_auto_sync_enabled': '0', 'gdocs_auto_sync_interval': 'daily',
        'gdocs_auto_sync_targets_json': '[]', 'gdocs_auto_sync_targets_config_json': '[]',
        'gdocs_auto_sync_last_run_at': '', 'google_enabled_integrations': '["calendar","docs","sheets"]',
    }
    for key in _defaults:
        if key not in updates:
            continue
        value = updates.get(key)
        if key == 'about_enabled':
            value = '1' if str(value or '0') in {'1', 'true', 'yes', 'on'} else '0'
        elif value is None:
            value = _defaults[key]
        db.execute(
            'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
            'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
            (key, str(value))
        )


def fetch_patients_by_status(db, status, patient_type='all', search_query='', sort_by='status_priority',
                              admin_user_id=None, include_group=True, treatment_method='all'):
    select_clause = _get_patients_select_clause(admin_user_id)
    where_clause, params = _get_patients_where_clause(status, patient_type, search_query, include_group, treatment_method)
    order_clause = _get_patients_order_clause(sort_by)
    sql = f"{select_clause}{where_clause}{order_clause}"
    return db.execute(sql, tuple(params)).fetchall()


def _get_patients_select_clause(admin_user_id):
    return """
        p.*,
        (SELECT COUNT(*) FROM appointments WHERE patient_id = p.id AND status = 'Scheduled') AS upcoming_appointments,
        (SELECT MAX(session_number) FROM notes WHERE patient_id = p.id) AS last_session_number,
        (SELECT MAX(appointment_date) FROM appointments WHERE patient_id = p.id) AS last_appointment_date,
        (SELECT MAX(n.created_at) FROM notes n WHERE n.patient_id = p.id) AS last_note_date,
        CASE
            WHEN COALESCE(p.is_deleted, 0) = 1 THEN 99
            WHEN p.status = 'ongoing' THEN 1
            WHEN p.status = 'candidate' THEN 2
            WHEN p.status = 'waiting' THEN 3
            WHEN p.status = 'archived' THEN 4
            ELSE 5
        END AS status_priority
    """


def _get_patients_where_clause(status, patient_type, search_query, include_group, treatment_method):
    conditions = ["COALESCE(p.is_deleted, 0) = 0"]
    params = []
    if status and status != 'all':
        conditions.append("p.status = ?")
        params.append(status)
    if patient_type and patient_type != 'all':
        conditions.append("p.patient_type = ?")
        params.append(patient_type)
    if treatment_method and treatment_method != 'all':
        conditions.append("p.treatment_method = ?")
        params.append(treatment_method)
    if search_query:
        conditions.append("(p.name LIKE ? OR p.email LIKE ? OR p.phone LIKE ?)")
        like_val = f"%{search_query}%"
        params.extend([like_val, like_val, like_val])
    if not include_group:
        conditions.append("(COALESCE(p.patient_type, '') != 'group' AND (p.patient_type IS NULL OR p.patient_type NOT IN ('group', 'dynamic_group')))")
    where = " WHERE " + " AND ".join(conditions)
    return where, params


def _get_patients_order_clause(sort_by):
    ordering = {
        'name': "p.name COLLATE NOCASE ASC",
        'name_desc': "p.name COLLATE NOCASE DESC",
        'status_priority': "status_priority ASC, p.name COLLATE NOCASE ASC",
        'recent': "COALESCE(p.created_at, '1900-01-01') DESC",
        'last_note': "last_note_date DESC NULLS LAST",
    }
    order_sql = ordering.get(sort_by, ordering['status_priority'])
    return f"ORDER BY {order_sql}"


def sqlite3_quote(value):
    if value is None:
        return 'NULL'
    return "'" + str(value).replace("'", "''") + "'"


def _normalize_patient_status(status):
    mapping = {
        'ongoing': 'ongoing',
        'active': 'ongoing',
        'candidate': 'candidate',
        'waiting': 'waiting',
        'waiting_for_scheduling': 'waiting',
        'archived': 'archived',
        'deleted': 'deleted',
    }
    return mapping.get(status.strip().lower() if status else '', 'candidate')


def _get_notification_unread_count(db, user):
    if not getattr(user, 'is_authenticated', False):
        return 0
    try:
        if getattr(user, 'role', None) == 'admin':
            row = db.execute('''
                SELECT COUNT(*) AS count
                FROM notifications
                WHERE COALESCE(is_read, 0) = 0
                  AND (COALESCE(audience, 'admin') = 'admin' OR recipient_user_id = ?)
            ''', (user.id,)).fetchone()
        else:
            row = db.execute('''
                SELECT COUNT(*) AS count
                FROM notifications
                WHERE COALESCE(is_read, 0) = 0
                  AND recipient_user_id = ?
            ''', (user.id,)).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int((row['count'] if row else 0) or 0)


def get_primary_admin_user(db):
    return db.execute(
        "SELECT * FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1"
    ).fetchone()


def format_lead_time_for_notice(target_dt, reference_dt=None):
    if not target_dt:
        return ''
    ref = reference_dt or datetime.now()
    diff = target_dt - ref
    total_minutes = int(diff.total_seconds() / 60)
    if total_minutes <= 0:
        return 'now'
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours >= 24:
        days = hours // 24
        return f'{days}d' if not hours % 24 else f'{days}d {hours % 24}h'
    if hours > 0:
        return f'{hours}h {minutes}m' if minutes else f'{hours}h'
    return f'{minutes}m'
