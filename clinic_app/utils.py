import os
import re
import json
import hashlib
import sqlite3
import smtplib
import shutil
import zipfile
import threading
import secrets
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
from email.message import EmailMessage
from flask import request, session, g, current_app, jsonify, url_for
from werkzeug.security import generate_password_hash

DUMMY_PASSWORD_HASH = generate_password_hash('dummy_password_for_timing_attack_mitigation')

ALLOWED_UPLOAD_EXTENSIONS = {'.docx', '.pdf', '.txt', '.png', '.jpg', '.jpeg', '.gif', '.xlsx', '.csv'}
ALLOWED_DIAGNOSIS_EXTENSIONS = {'.pdf', '.docx', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}

_PUBLIC_RATE_LIMIT_LOCK = threading.Lock()
_PUBLIC_RATE_LIMIT_BUCKETS = {}

def _request_client_ip():
    forwarded_for = (request.headers.get('X-Forwarded-For') or '').strip()
    if forwarded_for:
        first_ip = forwarded_for.split(',')[0].strip()
        if first_ip:
            return first_ip
    return request.remote_addr or 'unknown'

def _allowed_upload(filename, allowed_set):
    ext = os.path.splitext(filename)[1].lower()
    return bool(ext) and ext in allowed_set

def _validate_patient_fields(name, phone=None, birth_date=None, email=None):
    errors = []
    if not (name or '').strip():
        errors.append('Name is required.')
    if phone:
        cleaned = re.sub(r'[\s\-().]+', '', phone)
        if not re.fullmatch(r'\+?[0-9]{7,15}', cleaned):
            errors.append('Phone number appears invalid. Use digits, spaces, or dashes only (7–15 digits).')
    if birth_date:
        try:
            datetime.strptime(birth_date, '%Y-%m-%d')
        except ValueError:
            errors.append('Birth date must be in YYYY-MM-DD format.')
    if email:
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            errors.append('Email address appears invalid.')
    return errors

_APPOINTMENT_DURATION_MIN = 5
_APPOINTMENT_DURATION_MAX = 480

def _validate_appointment_duration(duration_minutes):
    try:
        val = int(duration_minutes)
    except (TypeError, ValueError):
        return None, 'Appointment duration must be a whole number of minutes.'
    if val < _APPOINTMENT_DURATION_MIN:
        return None, f'Appointment duration must be at least {_APPOINTMENT_DURATION_MIN} minutes.'
    if val > _APPOINTMENT_DURATION_MAX:
        return None, f'Appointment duration cannot exceed {_APPOINTMENT_DURATION_MAX} minutes (8 hours).'
    return val, None

def _validate_password_strength(password, username=None, email=None):
    candidate = str(password or '')
    if len(candidate) < 10:
        return False, 'Password must include at least 10 characters.'
    if not re.search(r'[A-Z]', candidate):
        return False, 'Password must include at least one uppercase letter.'
    if not re.search(r'[a-z]', candidate):
        return False, 'Password must include at least one lowercase letter.'
    if not re.search(r'\d', candidate):
        return False, 'Password must include at least one number.'
    if not re.search(r'[^A-Za-z0-9]', candidate):
        return False, 'Password must include at least one special character.'
    lowered = candidate.lower()
    for source in (username or '', email or ''):
        token = str(source).strip().lower()
        if token and len(token) >= 3 and token in lowered:
            return False, 'Password should not include your username or email.'
    return True, ''

def _smtp_settings_summary(app=None):
    if app is None:
        app = current_app
    host = (app.config.get('SMTP_HOST') or '').strip()
    port = int(app.config.get('SMTP_PORT', 587) or 587)
    username = (app.config.get('SMTP_USERNAME') or '').strip()
    from_email = (app.config.get('SMTP_FROM_EMAIL') or username).strip()
    use_tls = bool(app.config.get('SMTP_USE_TLS', True))
    configured = bool(host and from_email)
    return {
        'configured': configured,
        'host': host,
        'port': port,
        'username': username,
        'from_email': from_email,
        'use_tls': use_tls,
    }

def _smtp_health_check(app=None):
    if app is None:
        app = current_app
    settings = _smtp_settings_summary(app)
    if not settings['configured']:
        return {
            'configured': False,
            'ok': False,
            'message': 'SMTP is not configured (missing SMTP_HOST or SMTP_FROM_EMAIL).',
        }
    try:
        with smtplib.SMTP(settings['host'], settings['port'], timeout=10) as smtp:
            smtp.ehlo()
            if settings['use_tls']:
                smtp.starttls()
                smtp.ehlo()
            if settings['username']:
                smtp.login(settings['username'], app.config.get('SMTP_PASSWORD') or '')
        return {
            'configured': True,
            'ok': True,
            'message': 'SMTP connection is healthy.',
        }
    except Exception as exc:
        return {
            'configured': True,
            'ok': False,
            'message': f'SMTP connection failed: {exc}',
        }

def _send_smtp_email(recipient_email, subject, body_text, app=None):
    if app is None:
        app = current_app
    settings = _smtp_settings_summary(app)
    if not settings['configured']:
        return False, 'SMTP is not configured.'
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = settings['from_email']
    message['To'] = recipient_email
    message.set_content(body_text)
    try:
        with smtplib.SMTP(settings['host'], settings['port'], timeout=15) as smtp:
            smtp.ehlo()
            if settings['use_tls']:
                smtp.starttls()
                smtp.ehlo()
            if settings['username']:
                smtp.login(settings['username'], app.config.get('SMTP_PASSWORD') or '')
            smtp.send_message(message)
    except Exception as exc:
        return False, str(exc)
    return True, 'sent'

def _check_public_rate_limit(scope_key, token=''):
    app = current_app
    if app.config.get('TESTING') and not app.config.get('ENABLE_RATE_LIMIT_IN_TESTS'):
        return None
    max_requests = int(app.config.get('PUBLIC_BOOKING_RATE_LIMIT_MAX', 20) or 20)
    window_seconds = int(app.config.get('PUBLIC_BOOKING_RATE_LIMIT_WINDOW_SECONDS', 60) or 60)
    if max_requests <= 0 or window_seconds <= 0:
        return None
    now_ts = datetime.now(timezone.utc).timestamp()
    client_ip = _request_client_ip()
    token_prefix = (token or '')[:32]
    bucket_key = f'{scope_key}:{client_ip}:{token_prefix}'
    cutoff_ts = now_ts - window_seconds
    with _PUBLIC_RATE_LIMIT_LOCK:
        timestamps = _PUBLIC_RATE_LIMIT_BUCKETS.get(bucket_key, [])
        timestamps = [ts for ts in timestamps if ts >= cutoff_ts]
        if len(timestamps) >= max_requests:
            _PUBLIC_RATE_LIMIT_BUCKETS[bucket_key] = timestamps
            retry_after = max(1, int(window_seconds - (now_ts - timestamps[0])))
            response = jsonify({
                'status': 'error',
                'message': 'Too many requests. Please retry shortly.',
                'retry_after_seconds': retry_after,
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            return response
        timestamps.append(now_ts)
        _PUBLIC_RATE_LIMIT_BUCKETS[bucket_key] = timestamps
    return None

def parse_date_safe(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

def parse_time_safe(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), '%H:%M').time()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(value).strip(), '%H:%M:%S').time()
        except (ValueError, TypeError):
            return None

def combine_dt(date_obj, time_str):
    time_obj = parse_time_safe(time_str)
    if date_obj and time_obj:
        return datetime.combine(date_obj, time_obj)
    return None

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days)):
        yield start_date + timedelta(n)

def custom_weekday(date_obj):
    weekday = date_obj.weekday()
    return (weekday + 1) % 7

def _week_start_for_date(day_obj):
    return day_obj - timedelta(days=custom_weekday(day_obj))

def calendar_allowed_windows(day_code):
    windows = []
    if day_code < 5:
        for hour in range(8, 20):
            windows.append(f'{hour:02d}:00')
    return windows

def overlaps(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a

def _request_expects_json_error():
    if request.path.startswith('/api/'):
        return True
    return request.accept_mimetypes.best == 'application/json'


def redirect_to_patient_tab(patient_id, default_tab='info'):
    from flask import request, redirect, url_for
    tab = request.form.get('active_tab') or request.args.get('tab') or default_tab
    return redirect(url_for('patient_detail', patient_id=patient_id, tab=tab))


def _prune_rate_limits(db, bucket_key, scope, window_seconds):
    cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
    db.execute(
        'DELETE FROM rate_limits WHERE bucket_key = ? AND scope = ? AND timestamp_real < ?',
        (bucket_key, scope, cutoff)
    )


def _check_db_rate_limit(db, bucket_key, scope, max_requests, window_seconds):
    _prune_rate_limits(db, bucket_key, scope, window_seconds)
    row = db.execute(
        'SELECT COUNT(*) AS cnt FROM rate_limits WHERE bucket_key = ? AND scope = ?',
        (bucket_key, scope)
    ).fetchone()
    count = row['cnt'] if row else 0
    if count >= max_requests:
        oldest = db.execute(
            'SELECT timestamp_real FROM rate_limits WHERE bucket_key = ? AND scope = ? ORDER BY timestamp_real ASC LIMIT 1',
            (bucket_key, scope)
        ).fetchone()
        if oldest:
            retry_after = max(1, int(window_seconds - (datetime.now(timezone.utc).timestamp() - oldest['timestamp_real'])))
            return retry_after
        return window_seconds
    return None


def _record_db_rate_limit(db, bucket_key, scope):
    now_ts = datetime.now(timezone.utc).timestamp()
    db.execute(
        'INSERT OR IGNORE INTO rate_limits (bucket_key, scope, timestamp_real) VALUES (?, ?, ?)',
        (bucket_key, scope, now_ts)
    )


def _clear_db_rate_limits(db, bucket_key, scope=None):
    if scope:
        db.execute('DELETE FROM rate_limits WHERE bucket_key = ? AND scope = ?', (bucket_key, scope))
    else:
        db.execute('DELETE FROM rate_limits WHERE bucket_key = ?', (bucket_key,))


def parse_recurrence_days(appt):
    raw = (appt['recurrence_days'] or '').strip()
    if raw:
        days = []
        for part in raw.split(','):
            part = part.strip()
            if part.isdigit():
                val = int(part)
                if 0 <= val <= 6:
                    days.append(val)
        if days:
            return sorted(set(days))
    base_date = parse_date_safe(appt['appointment_date'])
    if not base_date:
        return [0]
    return [custom_weekday(base_date)]


def has_time_conflict(db, day_obj, start_dt, end_dt, exclude_appointment_id=None, exclude_group_session_id=None, exclude_block_id=None):
    day_iso = day_obj.isoformat()
    appointment_rows = db.execute('''
        SELECT id, appointment_time, duration_minutes
        FROM appointments
        WHERE appointment_date = ?
    ''', (day_iso,)).fetchall()
    for row in appointment_rows:
        if exclude_appointment_id and int(row['id']) == int(exclude_appointment_id):
            continue
        row_start = combine_dt(day_obj, row['appointment_time'])
        row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
        if overlaps(start_dt, end_dt, row_start, row_end):
            return 'Time overlaps an existing appointment.'
    block_rows = db.execute('''
        SELECT id, blocked_time, duration_minutes
        FROM blocked_slots
        WHERE blocked_date = ?
    ''', (day_iso,)).fetchall()
    for row in block_rows:
        if exclude_block_id and int(row['id']) == int(exclude_block_id):
            continue
        row_start = combine_dt(day_obj, row['blocked_time'])
        row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
        if overlaps(start_dt, end_dt, row_start, row_end):
            return 'Time overlaps a blocked slot.'
    group_rows = db.execute('''
        SELECT id, session_time, duration_minutes
        FROM group_sessions
        WHERE session_date = ?
          AND COALESCE(status, 'scheduled') = 'scheduled'
    ''', (day_iso,)).fetchall()
    for row in group_rows:
        if exclude_group_session_id and int(row['id']) == int(exclude_group_session_id):
            continue
        row_start = combine_dt(day_obj, row['session_time'])
        row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
        if overlaps(start_dt, end_dt, row_start, row_end):
            return 'Time overlaps an existing group session.'
    return None


def ensure_ongoing_recurrence_from_previous_week(db, reference_date=None):
    today = reference_date or datetime.now().date()
    current_week_start = today - timedelta(days=custom_weekday(today))
    prev_week_start = current_week_start - timedelta(days=7)
    prev_week_end = current_week_start - timedelta(days=1)
    candidate_rows = db.execute('''
        SELECT a.id AS appointment_id, a.patient_id, a.appointment_date, a.appointment_time
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE p.status = 'ongoing'
          AND COALESCE(p.patient_type, 'private') NOT IN ('initial-intake', 'diagnosee')
          AND COALESCE(a.status, 'scheduled') = 'scheduled'
          AND COALESCE(a.is_recurring, 0) = 0
          AND a.appointment_date BETWEEN ? AND ?
        ORDER BY a.patient_id ASC, a.appointment_date DESC, a.id DESC
    ''', (prev_week_start.isoformat(), prev_week_end.isoformat())).fetchall()
    latest_by_patient = {}
    for row in candidate_rows:
        if row['patient_id'] not in latest_by_patient:
            latest_by_patient[row['patient_id']] = row
    if not latest_by_patient:
        return 0
    converted = 0
    for patient_id, row in latest_by_patient.items():
        has_recurring = db.execute('''
            SELECT 1
            FROM appointments
            WHERE patient_id = ?
              AND COALESCE(status, 'scheduled') = 'scheduled'
              AND COALESCE(is_recurring, 0) = 1
            LIMIT 1
        ''', (patient_id,)).fetchone()
        if has_recurring:
            continue
        base_date = parse_date_safe(row['appointment_date'])
        if not base_date:
            continue
        recurrence_end = (base_date + timedelta(days=365)).isoformat()
        recurrence_day = str(custom_weekday(base_date))
        db.execute('''
            UPDATE appointments
            SET is_recurring = 1,
                recurrence_interval = 1,
                recurrence_days = ?,
                recurrence_end_date = ?,
                recurrence_count = NULL
            WHERE id = ?
        ''', (recurrence_day, recurrence_end, row['appointment_id']))
        converted += 1
    if converted:
        db.commit()
    return converted


def _ensure_patient_has_upcoming_booking(db, patient_id, patient_type, today, now_time, horizon_weeks):
    if patient_type in ('initial-intake', 'diagnosee'):
        return False
    has_future = db.execute('''
        SELECT 1
        FROM appointments
        WHERE patient_id = ?
          AND COALESCE(status, 'scheduled') = 'scheduled'
          AND (
              (COALESCE(is_recurring, 0) = 0 AND appointment_date >= ?)
              OR (COALESCE(is_recurring, 0) = 1
                  AND (recurrence_end_date IS NULL
                       OR recurrence_end_date >= DATE(?, ? || ' days')))
          )
        LIMIT 1
    ''', (patient_id, today.isoformat(), today.isoformat(), f'-{horizon_weeks * 7}')).fetchone()
    if has_future:
        return False
    latest = db.execute('''
        SELECT *
        FROM appointments
        WHERE patient_id = ?
        ORDER BY appointment_date DESC, appointment_time DESC, id DESC
        LIMIT 1
    ''', (patient_id,)).fetchone()
    if not latest:
        return False
    base_date = parse_date_safe(latest['appointment_date'])
    base_time = parse_time_safe(latest['appointment_time'])
    if not base_date or not base_time:
        return False
    day_code = custom_weekday(base_date)
    today_code = custom_weekday(today)
    offset_days = (day_code - today_code) % 7
    candidate_date = today + timedelta(days=offset_days)
    if candidate_date == today and base_time <= now_time:
        candidate_date += timedelta(days=7)
    duration = int(latest['duration_minutes'] or 60)
    if duration <= 0:
        duration = 60
    meeting_type = latest['meeting_type'] or 'in-person'
    meeting_link = latest['meeting_link'] or None
    meeting_title = latest['meeting_title'] or None
    meeting_platform = latest['meeting_platform'] if 'meeting_platform' in latest.keys() else None
    if not meeting_platform and meeting_type in ('zoom', 'google-meet'):
        meeting_platform = meeting_type
    save_to_google = int(latest['save_to_google'] or 0) if 'save_to_google' in latest.keys() else 0
    booked = False
    for week_step in range(0, max(1, horizon_weeks)):
        booking_day = candidate_date + timedelta(days=week_step * 7)
        start_dt = combine_dt(booking_day, base_time.strftime('%H:%M'))
        end_dt = start_dt + timedelta(minutes=duration)
        conflict = has_time_conflict(db, booking_day, start_dt, end_dt)
        if conflict:
            continue
        db.execute('''
            INSERT INTO appointments (
                patient_id, appointment_date, appointment_time, duration_minutes,
                meeting_type, meeting_link, meeting_platform, meeting_title,
                save_to_google, status, is_recurring, recurrence_interval,
                recurrence_days, recurrence_end_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', 1, 1, ?, ?)
        ''', (
            patient_id,
            booking_day.isoformat(),
            base_time.strftime('%H:%M'),
            duration,
            meeting_type,
            meeting_link,
            meeting_platform,
            meeting_title,
            save_to_google,
            str(day_code),
            (booking_day + timedelta(days=365)).isoformat()
        ))
        booked = True
        break
    return booked


def ensure_ongoing_patients_have_upcoming_bookings(db, reference_date=None, horizon_weeks=12):
    today = reference_date or datetime.now().date()
    now_time = datetime.now().time()
    rows = db.execute('''
        SELECT id, status, patient_type
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
          AND status = 'ongoing'
    ''').fetchall()
    created = 0
    for patient in rows:
        patient_id = int(patient['id'])
        patient_type = (patient['patient_type'] or 'private').strip().lower()
        if _ensure_patient_has_upcoming_booking(db, patient_id, patient_type, today, now_time, horizon_weeks):
            created += 1
    if created:
        db.commit()
    return created


def ensure_default_recurring_vacancies(db):
    has_future_override = db.execute('''
        SELECT 1
        FROM slots_override
        WHERE status = 'available' AND slot_date >= ?
        LIMIT 1
    ''', (datetime.now().date().isoformat(),)).fetchone()
    has_recurring = db.execute('''
        SELECT 1
        FROM vacancy_recurring
        WHERE COALESCE(is_active, 1) = 1
        LIMIT 1
    ''').fetchone()
    if has_future_override or has_recurring:
        return 0
    default_slots = [
        (0, '09:00', 60), (0, '15:00', 60),
        (1, '09:00', 60), (1, '15:00', 60),
        (2, '09:00', 60), (2, '15:00', 60),
        (3, '09:00', 60), (3, '15:00', 60),
        (4, '09:00', 60), (4, '15:00', 60),
    ]
    for weekday, slot_time, duration in default_slots:
        db.execute('''
            INSERT INTO vacancy_recurring (weekday, slot_time, duration_minutes, is_active)
            VALUES (?, ?, ?, 1)
        ''', (weekday, slot_time, duration))
    db.commit()
    return len(default_slots)


def recurring_occurrences_between(appt, range_start, range_end, max_occurrences=600):
    base_date = parse_date_safe(appt['appointment_date'])
    if not base_date:
        return []
    interval = int(appt['recurrence_interval'] or 1)
    if interval <= 0:
        interval = 1
    recurrence_end = parse_date_safe(appt['recurrence_end_date'])
    recurrence_count = int(appt['recurrence_count'] or 0)
    days = parse_recurrence_days(appt)
    try:
        excluded_raw = appt['excluded_dates'] or ''
    except (KeyError, IndexError):
        excluded_raw = ''
    excluded = {d.strip() for d in excluded_raw.split(',') if d.strip()}
    anchor_week_start = base_date - timedelta(days=custom_weekday(base_date))
    occurrences = []
    produced = 0
    week_index = 0
    while len(occurrences) < max_occurrences:
        block_week_start = anchor_week_start + timedelta(weeks=week_index * interval)
        if block_week_start > range_end:
            break
        for day_code in days:
            occ_date = block_week_start + timedelta(days=day_code)
            if occ_date < base_date:
                continue
            if recurrence_end and occ_date > recurrence_end:
                continue
            if occ_date.isoformat() in excluded:
                produced += 1
                if recurrence_count and produced > recurrence_count:
                    return occurrences
                continue
            produced += 1
            if recurrence_count and produced > recurrence_count:
                return occurrences
            if range_start <= occ_date <= range_end:
                occurrences.append(occ_date)
        week_index += 1
    return sorted(occurrences)


def build_booking_management_payload(db, mode='upcoming', future_days=180, history_days=120):
    today = datetime.now().date()
    if mode == 'history':
        range_start = today - timedelta(days=history_days)
        range_end = today - timedelta(days=1)
        sort_reverse = True
    else:
        range_start = today
        range_end = today + timedelta(days=future_days)
        sort_reverse = False
    items = []
    appointment_rows = db.execute('''
        SELECT a.*, p.name AS patient_name, p.status AS patient_status
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE COALESCE(a.status, 'scheduled') = 'scheduled'
          AND ((COALESCE(a.is_recurring, 0) = 0 AND a.appointment_date BETWEEN ? AND ?)
               OR (COALESCE(a.is_recurring, 0) = 1 AND a.appointment_date <= ?))
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    ''', (range_start.isoformat(), range_end.isoformat(), range_end.isoformat())).fetchall()
    seen_mgmt_keys: set = set()
    for appt in appointment_rows:
        is_recurring = int(appt['is_recurring'] or 0) == 1
        if is_recurring:
            occ_dates = recurring_occurrences_between(appt, range_start, range_end)
        else:
            occ_date = parse_date_safe(appt['appointment_date'])
            occ_dates = [occ_date] if occ_date else []
        for occ_date in occ_dates:
            _mgmt_key = (int(appt['patient_id']), occ_date.isoformat(), (appt['appointment_time'] or '')[:5])
            if _mgmt_key in seen_mgmt_keys:
                continue
            seen_mgmt_keys.add(_mgmt_key)
            start_dt = combine_dt(occ_date, appt['appointment_time'])
            duration = int(appt['duration_minutes'] or 60)
            end_dt = start_dt + timedelta(minutes=duration)
            items.append({
                'kind': 'appointment',
                'source_id': appt['id'],
                'occurrence_id': f"appointment-{appt['id']}-{occ_date.isoformat()}",
                'date': occ_date.isoformat(),
                'time': start_dt.strftime('%H:%M'),
                'end_time': end_dt.strftime('%H:%M'),
                'duration_minutes': duration,
                'title': appt['patient_name'],
                'patient_id': appt['patient_id'],
                'type_label': 'Recurring Appointment' if is_recurring else 'Appointment',
                'status': appt['patient_status'] or '',
                'meeting_type': appt['meeting_type'] or 'in-person',
                'meeting_link': appt['meeting_link'] or '',
                'meeting_title': appt['meeting_title'] or '',
                'is_recurring': is_recurring,
                'can_edit': True,
                'can_delete': True
            })
    block_rows = db.execute('''
        SELECT *
        FROM blocked_slots
        WHERE blocked_date BETWEEN ? AND ?
        ORDER BY blocked_date ASC, blocked_time ASC
    ''', (range_start.isoformat(), range_end.isoformat())).fetchall()
    for block in block_rows:
        block_date = parse_date_safe(block['blocked_date'])
        if not block_date:
            continue
        start_dt = combine_dt(block_date, block['blocked_time'])
        duration = int(block['duration_minutes'] or 60)
        end_dt = start_dt + timedelta(minutes=duration)
        block_type = (block['block_type'] or 'blocked').strip().lower()
        if block_type != 'blocked':
            block_type = 'blocked'
        items.append({
            'kind': 'block',
            'source_id': block['id'],
            'occurrence_id': f"block-{block['id']}",
            'date': block_date.isoformat(),
            'time': start_dt.strftime('%H:%M'),
            'end_time': end_dt.strftime('%H:%M'),
            'duration_minutes': duration,
            'title': block['title'] or 'Blocked Slot',
            'type_label': 'Blocked',
            'status': '',
            'meeting_type': '',
            'meeting_link': '',
            'meeting_title': '',
            'is_recurring': False,
            'block_type': block_type,
            'is_private': int(block['is_private'] or 0),
            'can_edit': True,
            'can_delete': True
        })
    group_rows = db.execute('''
        SELECT gs.*, g.name AS group_name
        FROM group_sessions gs
        JOIN groups g ON g.id = gs.group_id
        WHERE COALESCE(gs.status, 'scheduled') = 'scheduled'
          AND gs.session_date BETWEEN ? AND ?
        ORDER BY gs.session_date ASC, gs.session_time ASC
    ''', (range_start.isoformat(), range_end.isoformat())).fetchall()
    for row in group_rows:
        session_date = parse_date_safe(row['session_date'])
        if not session_date:
            continue
        start_dt = combine_dt(session_date, row['session_time'])
        duration = int(row['duration_minutes'] or 60)
        end_dt = start_dt + timedelta(minutes=duration)
        detail_url = url_for('group_detail', group_id=row['group_id'], show_upcoming='all') + f"#session-record-{row['id']}"
        items.append({
            'kind': 'group_session',
            'source_id': row['id'],
            'occurrence_id': f"group-session-{row['id']}",
            'date': session_date.isoformat(),
            'time': start_dt.strftime('%H:%M'),
            'end_time': end_dt.strftime('%H:%M'),
            'duration_minutes': duration,
            'title': row['title'] or f"Group: {row['group_name']}",
            'type_label': 'Group Session',
            'status': row['group_name'],
            'meeting_type': row['meeting_type'] or 'in-person',
            'meeting_link': row['meeting_link'] or '',
            'meeting_title': row['title'] or '',
            'detail_url': detail_url,
            'is_recurring': False,
            'can_edit': True,
            'can_delete': True
        })
    items.sort(key=lambda item: (item['date'], item['time']), reverse=sort_reverse)
    return {
        'mode': mode,
        'range_start': range_start.isoformat(),
        'range_end': range_end.isoformat(),
        'items': items
    }
