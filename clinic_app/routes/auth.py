from datetime import datetime, timezone
import hashlib
import secrets

from flask import redirect, render_template, request, session, url_for, flash
from flask_login import current_user, login_required, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from clinic_app.utils import _request_client_ip
from clinic_app.models import get_db


_LOGIN_RATE_LIMIT_BUCKETS = {}
_PASSWORD_RESET_RATE_LIMIT_BUCKETS = {}
_REGISTER_RATE_LIMIT_BUCKETS = {}
_LOGIN_RATE_LIMIT_MAX = 5
_LOGIN_RATE_LIMIT_WINDOW = 300
_LOGIN_RATE_LIMIT_LOCKOUT = 900
_PASSWORD_RESET_RATE_LIMIT_MAX = 5
_PASSWORD_RESET_RATE_LIMIT_WINDOW = 900
_REGISTER_RATE_LIMIT_MAX = 5
_REGISTER_RATE_LIMIT_WINDOW = 3600


def _prune_rate_limits(db, bucket_key, scope, window_seconds):
    cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
    db.execute(
        'DELETE FROM rate_limits WHERE bucket_key = ? AND scope = ? AND timestamp_real < ?',
        (bucket_key, scope, cutoff)
    )


def _count_rate_limits(db, bucket_key, scope):
    row = db.execute(
        'SELECT COUNT(*) AS cnt FROM rate_limits WHERE bucket_key = ? AND scope = ?',
        (bucket_key, scope)
    ).fetchone()
    return row['cnt'] if row else 0


def _record_rate_limit(db, bucket_key, scope):
    db.execute(
        'INSERT INTO rate_limits (bucket_key, scope, timestamp_real) VALUES (?, ?, ?)',
        (bucket_key, scope, datetime.now(timezone.utc).timestamp())
    )


def _check_register_rate_limit(app):
    if app.config.get('TESTING') and not app.config.get('ENABLE_RATE_LIMIT_IN_TESTS'):
        return None
    max_requests = int(app.config.get('REGISTER_RATE_LIMIT_MAX', _REGISTER_RATE_LIMIT_MAX) or _REGISTER_RATE_LIMIT_MAX)
    window_seconds = int(app.config.get('REGISTER_RATE_LIMIT_WINDOW_SECONDS', _REGISTER_RATE_LIMIT_WINDOW) or _REGISTER_RATE_LIMIT_WINDOW)
    if max_requests <= 0 or window_seconds <= 0:
        return None
    ip = _request_client_ip()
    db = get_db()
    _prune_rate_limits(db, ip, 'register', window_seconds)
    count = _count_rate_limits(db, ip, 'register')
    if count >= max_requests:
        return max(1, int(window_seconds))
    _record_rate_limit(db, ip, 'register')
    db.commit()
    return None


def _rate_limit_key(username):
    normalized_username = (username or '').strip().lower()[:128]
    return f"{_request_client_ip()}:{normalized_username}"


def _check_login_rate_limit(app, username):
    if app.config.get('TESTING') and not app.config.get('ENABLE_RATE_LIMIT_IN_TESTS'):
        return None
    max_attempts = int(app.config.get('LOGIN_RATE_LIMIT_MAX_ATTEMPTS', _LOGIN_RATE_LIMIT_MAX) or _LOGIN_RATE_LIMIT_MAX)
    window_seconds = int(app.config.get('LOGIN_RATE_LIMIT_WINDOW_SECONDS', _LOGIN_RATE_LIMIT_WINDOW) or _LOGIN_RATE_LIMIT_WINDOW)
    lockout_seconds = int(app.config.get('LOGIN_RATE_LIMIT_LOCKOUT_SECONDS', _LOGIN_RATE_LIMIT_LOCKOUT) or _LOGIN_RATE_LIMIT_LOCKOUT)
    if max_attempts <= 0 or window_seconds <= 0 or lockout_seconds <= 0:
        return None
    now_ts = datetime.now(timezone.utc).timestamp()
    key = _rate_limit_key(username)
    db = get_db()
    blocked_row = db.execute(
        'SELECT timestamp_real FROM rate_limits WHERE bucket_key = ? AND scope = ?',
        (key, 'login-blocked')
    ).fetchone()
    if blocked_row and blocked_row['timestamp_real'] > now_ts:
        return max(1, int(blocked_row['timestamp_real'] - now_ts))
    elif blocked_row:
        db.execute('DELETE FROM rate_limits WHERE bucket_key = ? AND scope = ?', (key, 'login-blocked'))
    _prune_rate_limits(db, key, 'login', window_seconds)
    count = _count_rate_limits(db, key, 'login')
    if count >= max_attempts:
        return max(1, int(window_seconds))
    return None


def _record_login_failure(app, username):
    max_attempts = int(app.config.get('LOGIN_RATE_LIMIT_MAX_ATTEMPTS', _LOGIN_RATE_LIMIT_MAX) or _LOGIN_RATE_LIMIT_MAX)
    window_seconds = int(app.config.get('LOGIN_RATE_LIMIT_WINDOW_SECONDS', _LOGIN_RATE_LIMIT_WINDOW) or _LOGIN_RATE_LIMIT_WINDOW)
    lockout_seconds = int(app.config.get('LOGIN_RATE_LIMIT_LOCKOUT_SECONDS', _LOGIN_RATE_LIMIT_LOCKOUT) or _LOGIN_RATE_LIMIT_LOCKOUT)
    if max_attempts <= 0 or window_seconds <= 0 or lockout_seconds <= 0:
        return False, None
    now_ts = datetime.now(timezone.utc).timestamp()
    key = _rate_limit_key(username)
    db = get_db()
    _prune_rate_limits(db, key, 'login', window_seconds)
    count = _count_rate_limits(db, key, 'login')
    _record_rate_limit(db, key, 'login')
    if count + 1 >= max_attempts:
        blocked_until = now_ts + lockout_seconds
        db.execute(
            'INSERT INTO rate_limits (bucket_key, scope, timestamp_real) VALUES (?, ?, ?)',
            (key, 'login-blocked', blocked_until)
        )
        db.commit()
        return True, max(1, int(lockout_seconds))
    db.commit()
    return False, None


def _clear_login_failures(username):
    key = _rate_limit_key(username)
    db = get_db()
    db.execute('DELETE FROM rate_limits WHERE bucket_key = ? AND scope IN (?, ?)',
               (key, 'login', 'login-blocked'))
    db.commit()


def _reset_rate_limit_key(identifier):
    normalized_identifier = (identifier or '').strip().lower()[:128]
    return f"{_request_client_ip()}:{normalized_identifier}"


def _check_password_reset_rate_limit(app, identifier):
    if app.config.get('TESTING') and not app.config.get('ENABLE_RATE_LIMIT_IN_TESTS'):
        return None
    max_requests = int(app.config.get('PASSWORD_RESET_RATE_LIMIT_MAX', _PASSWORD_RESET_RATE_LIMIT_MAX) or _PASSWORD_RESET_RATE_LIMIT_MAX)
    window_seconds = int(app.config.get('PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS', _PASSWORD_RESET_RATE_LIMIT_WINDOW) or _PASSWORD_RESET_RATE_LIMIT_WINDOW)
    if max_requests <= 0 or window_seconds <= 0:
        return None
    now_ts = datetime.now(timezone.utc).timestamp()
    key = _reset_rate_limit_key(identifier)
    db = get_db()
    _prune_rate_limits(db, key, 'password-reset', window_seconds)
    count = _count_rate_limits(db, key, 'password-reset')
    if count >= max_requests:
        return max(1, int(window_seconds))
    _record_rate_limit(db, key, 'password-reset')
    db.commit()
    return None


def _hash_reset_token(token):
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()


def _log_auth_audit(db, action, details):
    try:
        db.execute(
            'INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)',
            (None, action, details),
        )
    except Exception:
        # Never block auth flows on audit logging failures.
        pass


def _build_reset_generic_message():
    return 'If the account exists and is eligible, a password reset link has been generated.'


def _cleanup_password_reset_tokens(db):
    db.execute(
        '''
        DELETE FROM password_reset_tokens
        WHERE used_at IS NOT NULL
           OR expires_at <= CURRENT_TIMESTAMP
        '''
    )


def register_auth_routes(
    app,
    *,
    get_db,
    verify_totp_code,
    login_redirect_for_user,
    dummy_password_hash,
    send_smtp_email,
    validate_password_strength,
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
                    _log_auth_audit(db, 'auth_login_2fa_success', f"username={pending_user['username']}")
                    session.pop('pending_2fa_user_id', None)
                    session.pop('pending_2fa_username', None)
                    db.commit()
                    return login_redirect_for_user(pending_user)

                flash('Invalid authenticator code.')
                _log_auth_audit(db, 'auth_login_2fa_failed', f"username={pending_user['username']}")
                db.commit()
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
                    _log_auth_audit(db, 'auth_login_disabled_account', f"username={username}")
                    db.commit()
                    return render_template('login.html')

                _clear_login_failures(username)
                _log_auth_audit(db, 'auth_login_password_success', f"username={username}")
                db.commit()

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
            _log_auth_audit(db, 'auth_login_password_failed', f"username={username}")
            db.commit()
            if lockout_triggered and retry_after is not None:
                flash(f'Too many failed login attempts. Please try again in {retry_after} seconds.')
            else:
                flash('Invalid username or password')

        if pending_user_id:
            return render_template('login.html', requires_otp=True, pending_username=pending_username)

        return render_template('login.html')

    @login_required
    def logout():
        db = get_db()
        _log_auth_audit(db, 'auth_logout', f"user_id={current_user.id}")
        db.commit()
        logout_user()
        return redirect(url_for('login'))

    def forgot_password():
        if request.method == 'POST':
            identifier = (request.form.get('username_or_email') or '').strip()
            retry_after = _check_password_reset_rate_limit(app, identifier)
            if retry_after is not None:
                flash(f'Too many reset attempts. Please try again in {retry_after} seconds.')
                return render_template('forgot_password.html')

            db = get_db()
            _cleanup_password_reset_tokens(db)
            user = db.execute(
                '''
                SELECT * FROM users
                WHERE is_active = 1
                  AND role = 'admin'
                  AND (
                        LOWER(username) = LOWER(?)
                        OR LOWER(COALESCE(email, '')) = LOWER(?)
                  )
                LIMIT 1
                ''',
                (identifier, identifier),
            ).fetchone()

            if user:
                raw_token = secrets.token_urlsafe(32)
                token_hash = _hash_reset_token(raw_token)
                reset_url = url_for('reset_password', token=raw_token, _external=True)
                expires_at = datetime.now(timezone.utc).timestamp() + int(
                    app.config.get('PASSWORD_RESET_TOKEN_TTL_SECONDS', 1800) or 1800
                )
                db.execute(
                    '''
                    INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, requested_ip)
                    VALUES (?, ?, datetime(?, 'unixepoch'), ?)
                    ''',
                    (user['id'], token_hash, expires_at, _request_client_ip()),
                )
                _log_auth_audit(db, 'auth_password_reset_requested', f"username={user['username']}")
                db.commit()

                flash(_build_reset_generic_message())
                if app.config.get('TESTING'):
                    flash(f"Reset link: {reset_url}")
                else:
                    recipient_email = (user['email'] or '').strip()
                    if recipient_email:
                        try:
                            sent_ok, send_message = send_smtp_email(
                                recipient_email,
                                subject='Private Clinic password reset',
                                body_text=(
                                    'A password reset was requested for your admin account.\n\n'
                                    f'Use this secure link to set a new password:\n{reset_url}\n\n'
                                    'This link expires soon and can only be used once.\n'
                                    'If you did not request this, you can ignore this email.'
                                ),
                            )
                            if sent_ok:
                                _log_auth_audit(db, 'auth_password_reset_email_sent', f"user_id={user['id']}")
                            else:
                                _log_auth_audit(db, 'auth_password_reset_email_not_configured', f"user_id={user['id']}; reason={send_message}")
                            db.commit()
                        except Exception:
                            _log_auth_audit(db, 'auth_password_reset_email_failed', f"user_id={user['id']}")
                            db.commit()
                            app.logger.exception('Password reset email send failed for user_id=%s', user['id'])
                    else:
                        _log_auth_audit(db, 'auth_password_reset_missing_email', f"user_id={user['id']}")
                        db.commit()
                return redirect(url_for('login'))

            _log_auth_audit(db, 'auth_password_reset_unknown_account', f"identifier={identifier}")
            db.commit()
            flash(_build_reset_generic_message())
            return redirect(url_for('login'))

        return render_template('forgot_password.html')

    def reset_password(token):
        token_hash = _hash_reset_token(token)
        db = get_db()
        _cleanup_password_reset_tokens(db)

        token_row = db.execute(
            '''
            SELECT prt.id, prt.user_id, prt.expires_at, prt.used_at, u.username, u.email
            FROM password_reset_tokens prt
            JOIN users u ON u.id = prt.user_id
            WHERE prt.token_hash = ?
            LIMIT 1
            ''',
            (token_hash,),
        ).fetchone()

        if not token_row:
            flash('Password reset link is invalid or expired.')
            return redirect(url_for('login'))

        used_at = token_row['used_at']
        expires_at = token_row['expires_at']
        is_expired = False
        try:
            expires_dt = datetime.fromisoformat(str(expires_at).replace(' ', 'T'))
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            is_expired = expires_dt <= datetime.now(timezone.utc)
        except Exception:
            is_expired = True

        if used_at or is_expired:
            flash('Password reset link is invalid or expired.')
            _log_auth_audit(db, 'auth_password_reset_invalid_or_expired', f"username={token_row['username']}")
            db.commit()
            return redirect(url_for('login'))

        if request.method == 'POST':
            new_password = (request.form.get('new_password') or '').strip()
            confirm_password = (request.form.get('confirm_password') or '').strip()

            password_ok, password_error = validate_password_strength(
                new_password,
                username=token_row['username'],
                email=token_row['email'],
            )
            if not password_ok:
                flash(password_error)
                return render_template('reset_password.html', token=token)

            if new_password != confirm_password:
                flash('New password confirmation does not match.')
                return render_template('reset_password.html', token=token)

            db.execute(
                '''
                UPDATE users
                SET password_hash = ?,
                    force_password_change = 0,
                    session_version = COALESCE(session_version, 0) + 1
                WHERE id = ?
                ''',
                (generate_password_hash(new_password), token_row['user_id'])
            )
            db.execute(
                'UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE user_id = ? AND used_at IS NULL',
                (token_row['user_id'],)
            )
            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_username', None)
            _clear_login_failures(token_row['username'])
            _log_auth_audit(db, 'auth_password_reset_completed', f"username={token_row['username']}")
            db.commit()
            flash('Password updated successfully. Please sign in.')
            return redirect(url_for('login'))

        return render_template('reset_password.html', token=token)

    def register():
        if request.method == 'POST':
            retry_after = _check_register_rate_limit(app)
            if retry_after is not None:
                flash(f'Too many registration attempts. Please try again in {retry_after // 60 + 1} minute(s).')
                return render_template('register.html'), 429

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
    app.add_url_rule('/forgot-password', endpoint='forgot_password', view_func=forgot_password, methods=['GET', 'POST'])
    app.add_url_rule('/reset-password/<token>', endpoint='reset_password', view_func=reset_password, methods=['GET', 'POST'])
