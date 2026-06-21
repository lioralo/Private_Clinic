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
from flask import request, session, g, current_app, jsonify
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
