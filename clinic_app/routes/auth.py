from datetime import datetime, timezone
import threading

from flask import redirect, render_template, request, session, url_for, flash
from flask_login import current_user, login_required, logout_user
from werkzeug.security import check_password_hash


_LOGIN_RATE_LIMIT_LOCK = threading.Lock()
_LOGIN_RATE_LIMIT_BUCKETS = {}


def _request_client_ip():
    forwarded_for = (request.headers.get('X-Forwarded-For') or '').strip()
    if forwarded_for:
        first_ip = forwarded_for.split(',')[0].strip()
        if first_ip:
            return first_ip
    return request.remote_addr or 'unknown'


def _rate_limit_key(username):
    normalized_username = (username or '').strip().lower()[:128]
    return f"{_request_client_ip()}:{normalized_username}"


def _check_login_rate_limit(app, username):
    if app.config.get('TESTING') and not app.config.get('ENABLE_RATE_LIMIT_IN_TESTS'):
        return None

    max_attempts = int(app.config.get('LOGIN_RATE_LIMIT_MAX_ATTEMPTS', 5) or 5)
    window_seconds = int(app.config.get('LOGIN_RATE_LIMIT_WINDOW_SECONDS', 300) or 300)
    lockout_seconds = int(app.config.get('LOGIN_RATE_LIMIT_LOCKOUT_SECONDS', 900) or 900)
    if max_attempts <= 0 or window_seconds <= 0 or lockout_seconds <= 0:
        return None

    now_ts = datetime.now(timezone.utc).timestamp()
    key = _rate_limit_key(username)
    cutoff_ts = now_ts - window_seconds

    with _LOGIN_RATE_LIMIT_LOCK:
        state = _LOGIN_RATE_LIMIT_BUCKETS.get(key, {'attempts': [], 'blocked_until': 0.0})
        attempts = [ts for ts in state.get('attempts', []) if ts >= cutoff_ts]
        blocked_until = float(state.get('blocked_until', 0.0) or 0.0)

        _LOGIN_RATE_LIMIT_BUCKETS[key] = {
            'attempts': attempts,
            'blocked_until': blocked_until,
        }

    if blocked_until <= now_ts:
        return None
    return max(1, int(blocked_until - now_ts))


def _record_login_failure(app, username):
    max_attempts = int(app.config.get('LOGIN_RATE_LIMIT_MAX_ATTEMPTS', 5) or 5)
    window_seconds = int(app.config.get('LOGIN_RATE_LIMIT_WINDOW_SECONDS', 300) or 300)
    lockout_seconds = int(app.config.get('LOGIN_RATE_LIMIT_LOCKOUT_SECONDS', 900) or 900)
    if max_attempts <= 0 or window_seconds <= 0 or lockout_seconds <= 0:
        return False, None

    now_ts = datetime.now(timezone.utc).timestamp()
    key = _rate_limit_key(username)
    cutoff_ts = now_ts - window_seconds

    with _LOGIN_RATE_LIMIT_LOCK:
        state = _LOGIN_RATE_LIMIT_BUCKETS.get(key, {'attempts': [], 'blocked_until': 0.0})
        attempts = [ts for ts in state.get('attempts', []) if ts >= cutoff_ts]
        attempts.append(now_ts)

        blocked_until = 0.0
        if len(attempts) >= max_attempts:
            blocked_until = now_ts + lockout_seconds
            attempts = []

        _LOGIN_RATE_LIMIT_BUCKETS[key] = {
            'attempts': attempts,
            'blocked_until': blocked_until,
        }

    if blocked_until <= now_ts:
        return False, None
    return True, max(1, int(blocked_until - now_ts))


def _clear_login_failures(username):
    key = _rate_limit_key(username)
    with _LOGIN_RATE_LIMIT_LOCK:
        _LOGIN_RATE_LIMIT_BUCKETS.pop(key, None)


def register_auth_routes(
    app,
    *,
    get_db,
    verify_totp_code,
    login_redirect_for_user,
    dummy_password_hash,
):
    def login():
        if current_user.is_authenticated:
            if current_user.role == 'admin':
                return redirect(url_for('patients'))
            return redirect(url_for('patient_home'))

        pending_user_id = session.get('pending_2fa_user_id')
        pending_username = session.get('pending_2fa_username', '')

        if request.method == 'POST':
            otp_code = (request.form.get('otp_code') or '').strip()
            if pending_user_id and otp_code:
                db = get_db()
                pending_user = db.execute('SELECT * FROM users WHERE id = ?', (pending_user_id,)).fetchone()
                if not pending_user or not pending_user['is_active']:
                    session.pop('pending_2fa_user_id', None)
                    session.pop('pending_2fa_username', None)
                    flash('Login session expired. Please sign in again.')
                    return redirect(url_for('login'))

                if not pending_user['totp_enabled'] or not pending_user['totp_secret']:
                    session.pop('pending_2fa_user_id', None)
                    session.pop('pending_2fa_username', None)
                    flash('Authenticator is not configured for this admin account.')
                    return redirect(url_for('login'))

                if verify_totp_code(pending_user['totp_secret'], otp_code):
                    session.pop('pending_2fa_user_id', None)
                    session.pop('pending_2fa_username', None)
                    return login_redirect_for_user(pending_user)

                flash('Invalid authenticator code.')
                return render_template('login.html', requires_otp=True, pending_username=pending_username)

            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_username', None)

            username = request.form.get('username', '')
            password = request.form.get('password', '')

            retry_after = _check_login_rate_limit(app, username)
            if retry_after is not None:
                flash(f'Too many failed login attempts. Please try again in {retry_after} seconds.')
                return render_template('login.html')

            db = get_db()
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

            if user:
                password_correct = check_password_hash(user['password_hash'], password)
            else:
                check_password_hash(dummy_password_hash, password)
                password_correct = False

            if user and password_correct:
                if not user['is_active']:
                    flash('Account is disabled. Contact administrator.')
                    return render_template('login.html')

                _clear_login_failures(username)

                # REQUIRE 2FA for all admin accounts in PRODUCTION
                # IN TESTING: Allow bypass for admin logins
                if user['role'] == 'admin' and not app.config.get('TESTING'):
                    if not user['totp_enabled'] or not user['totp_secret']:
                        return login_redirect_for_user(user)

                    session['pending_2fa_user_id'] = int(user['id'])
                    session['pending_2fa_username'] = user['username']
                    flash('Two-factor authentication required. Check your authenticator app.')
                    return render_template('login.html', requires_otp=True, pending_username=user['username'])

                return login_redirect_for_user(user)

            lockout_triggered, retry_after = _record_login_failure(app, username)
            if lockout_triggered and retry_after is not None:
                flash(f'Too many failed login attempts. Please try again in {retry_after} seconds.')
            else:
                flash('Invalid username or password')

        if pending_user_id:
            return render_template('login.html', requires_otp=True, pending_username=pending_username)

        return render_template('login.html')

    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    def register():
        if request.method == 'POST':
            name = request.form['name']
            email = request.form.get('email')
            phone = request.form.get('phone')

            if not name:
                flash('Name is required!')
            else:
                db = get_db()
                db.execute(
                    'INSERT INTO patients (name, status, email, phone) VALUES (?, ?, ?, ?)',
                    (name, 'candidate', email, phone),
                )
                db.commit()
                flash('Registration successful! We will contact you soon.')
                return redirect(url_for('login'))

        return render_template('register.html')

    app.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    app.add_url_rule('/logout', endpoint='logout', view_func=logout, methods=['GET'])
    app.add_url_rule('/register', endpoint='register', view_func=register, methods=['GET', 'POST'])
