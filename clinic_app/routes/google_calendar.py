import os
import json
import hmac
import hashlib
import secrets
from datetime import datetime, timezone

from flask import (
    Blueprint, flash, jsonify, redirect,
    request, session, url_for,
)
from flask_login import current_user, login_user, login_required

from clinic_app.models import get_db


google_calendar_bp = Blueprint('google_calendar', __name__)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _google_oauth_state_max_age_seconds() -> int:
    return int(os.environ.get('GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS', '900') or 900)


def _google_oauth_state_signature(payload: str) -> str:
    from app import app as _flask_app
    key = str(_flask_app.secret_key or '').encode('utf-8')
    return hmac.new(key, payload.encode('utf-8'), hashlib.sha256).hexdigest()


def _generate_google_oauth_state() -> str:
    now_ts = str(int(datetime.now(timezone.utc).timestamp()))
    nonce = secrets.token_urlsafe(24)
    payload = f'{now_ts}.{nonce}'
    signature = _google_oauth_state_signature(payload)
    return f'{payload}.{signature}'


def _is_valid_google_oauth_state(state_value: str) -> bool:
    raw = (state_value or '').strip()
    if not raw:
        return False
    parts = raw.split('.')
    if len(parts) < 3:
        return False
    ts = parts[0]
    signature = parts[-1]
    nonce = '.'.join(parts[1:-1])
    if not ts.isdigit() or not nonce or not signature:
        return False

    payload = f'{ts}.{nonce}'
    expected_signature = _google_oauth_state_signature(payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    now_ts = int(datetime.now(timezone.utc).timestamp())
    issued_ts = int(ts)
    max_age = max(60, _google_oauth_state_max_age_seconds())
    if issued_ts > now_ts + 60:
        return False
    return (now_ts - issued_ts) <= max_age


def _ensure_google_oauth_pending_table(db):
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS google_oauth_pending_states (
            state TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            redirect_uri TEXT NOT NULL,
            code_verifier TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        '''
    )
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_google_oauth_pending_created_at '
        'ON google_oauth_pending_states(created_at)'
    )


def _prune_google_oauth_pending_states(db):
    max_age = max(60, _google_oauth_state_max_age_seconds())
    db.execute(
        "DELETE FROM google_oauth_pending_states WHERE created_at < datetime('now', ?)",
        (f'-{max_age} seconds',),
    )


def _store_google_oauth_pending_state(db, state_value: str, user_id: int, redirect_uri: str, code_verifier: str = None):
    _ensure_google_oauth_pending_table(db)
    _prune_google_oauth_pending_states(db)
    db.execute(
        '''
        INSERT INTO google_oauth_pending_states (state, user_id, redirect_uri, code_verifier, created_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(state) DO UPDATE SET
            user_id = excluded.user_id,
            redirect_uri = excluded.redirect_uri,
            code_verifier = excluded.code_verifier,
            created_at = CURRENT_TIMESTAMP
        ''',
        (state_value, int(user_id), redirect_uri, code_verifier),
    )


def _pop_google_oauth_pending_state(db, state_value: str):
    _ensure_google_oauth_pending_table(db)
    _prune_google_oauth_pending_states(db)
    row = db.execute(
        'SELECT state, user_id, redirect_uri, code_verifier, created_at '
        'FROM google_oauth_pending_states WHERE state = ?',
        ((state_value or '').strip(),),
    ).fetchone()
    if not row:
        return None
    db.execute('DELETE FROM google_oauth_pending_states WHERE state = ?', (row['state'],))
    db.commit()
    return row


def _load_active_admin_user(user_id):
    from app import load_user
    user = load_user(user_id)
    if not user:
        return None
    db = get_db()
    row = db.execute('SELECT is_active FROM users WHERE id = ?', (user_id,)).fetchone()
    if not row or not bool(row['is_active']) or user.role != 'admin':
        return None
    return user


# ---------------------------------------------------------------------------
# Route functions
# ---------------------------------------------------------------------------


@google_calendar_bp.route('/admin/google-calendar/status')
@login_required
def google_calendar_status():
    from app import get_site_settings, gcal
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    settings = get_site_settings(db)
    try:
        enabled_integrations = json.loads(settings.get('google_enabled_integrations') or '["calendar","docs","sheets"]')
    except (ValueError, TypeError):
        enabled_integrations = ['calendar', 'docs', 'sheets']
    if not gcal:
        return jsonify({
            'connected': False,
            'google_libs': False,
            'client_configured': False,
            'calendar_id': None,
            'calendars': [],
            'enabled_integrations': enabled_integrations,
            'reason': 'Google libraries not installed.',
        })
    try:
        connected = bool(gcal.is_connected(db))
        calendars_raw = gcal.list_calendars(db) if connected else []
        calendars = calendars_raw if isinstance(calendars_raw, list) else []
        calendar_id_raw = gcal.get_calendar_id(db) if connected else None
        calendar_id = str(calendar_id_raw) if calendar_id_raw is not None else None
    except Exception as exc:
        return jsonify({'connected': False, 'error': str(exc)})
    return jsonify({
        'connected': connected,
        'google_libs': bool(getattr(gcal, 'GOOGLE_LIBS_AVAILABLE', False)),
        'client_configured': bool(gcal._client_secrets_available()) if gcal else False,
        'calendar_id': calendar_id,
        'calendars': calendars,
        'enabled_integrations': enabled_integrations,
    })


@google_calendar_bp.route('/api/google_calendar/status')
@login_required
def api_google_calendar_status():
    return google_calendar_status()


@google_calendar_bp.route('/admin/google-calendar/connect', methods=['GET', 'POST'])
@login_required
def google_calendar_connect():
    from app import gcal, build_external_public_url, get_site_settings, save_site_settings
    if current_user.role != 'admin':
        flash('Unauthorized.')
        return redirect(url_for('admin_profile'))
    if not gcal:
        flash('Google API libraries are not installed. Run: pip install google-auth-oauthlib google-api-python-client')
        return redirect(url_for('admin_profile'))
    if not gcal._client_secrets_available():
        flash('Google OAuth credentials are not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.')
        return redirect(url_for('admin_profile'))
    db = get_db()
    if request.method == 'POST':
        selected = request.form.getlist('google_integration')
        valid_options = list(gcal.INTEGRATION_SCOPES.keys()) if gcal else ['calendar', 'docs', 'sheets']
        integrations = [i for i in selected if i in valid_options] or valid_options
        save_site_settings(db, {'google_enabled_integrations': json.dumps(integrations)})
        db.commit()
    else:
        settings = get_site_settings(db)
        try:
            integrations = json.loads(settings.get('google_enabled_integrations') or '[]') or list(gcal.INTEGRATION_SCOPES.keys())
        except (ValueError, TypeError):
            integrations = list(gcal.INTEGRATION_SCOPES.keys())
    try:
        redirect_uri = build_external_public_url('google_calendar_callback')
        oauth_state = _generate_google_oauth_state()
        auth_url, state, code_verifier = gcal.get_authorization_url(
            integrations=integrations, redirect_uri=redirect_uri, state=oauth_state)
        _store_google_oauth_pending_state(db, state, current_user.id, redirect_uri, code_verifier)
        db.commit()
        session['gcal_oauth_state'] = state
        session['gcal_redirect_uri'] = redirect_uri
        if code_verifier:
            session['gcal_code_verifier'] = code_verifier
        return redirect(auth_url)
    except Exception as exc:
        flash(f'Failed to initiate Google connection: {exc}')
        return redirect(url_for('admin_profile'))


@google_calendar_bp.route('/admin/google-calendar/callback')
def google_calendar_callback():
    from app import gcal, build_external_public_url
    code = request.args.get('code')
    state = request.args.get('state')
    oauth_error = (request.args.get('error') or '').strip()
    oauth_error_description = (request.args.get('error_description') or '').strip()
    db = get_db()
    pending_oauth = _pop_google_oauth_pending_state(db, state)
    stored_state = session.pop('gcal_oauth_state', None)
    if oauth_error:
        if oauth_error_description:
            flash(f'Google authorisation failed: {oauth_error} - {oauth_error_description}')
        else:
            flash(f'Google authorisation failed: {oauth_error}')
        return redirect(url_for('admin_profile'))
    if not code:
        flash('Google authorisation was cancelled or failed.')
        return redirect(url_for('admin_profile'))
    state_matches_session = bool(stored_state and state == stored_state)
    state_matches_signed_token = _is_valid_google_oauth_state(state)
    if not (state_matches_session or state_matches_signed_token):
        flash('OAuth state mismatch – please try connecting again.')
        return redirect(url_for('admin_profile'))

    callback_user = current_user if current_user.is_authenticated else None
    if callback_user and callback_user.role != 'admin':
        callback_user = None
    if pending_oauth and callback_user and int(callback_user.id) != int(pending_oauth['user_id']):
        flash('OAuth state mismatch – please try connecting again.')
        return redirect(url_for('login'))
    if not callback_user and pending_oauth:
        callback_user = _load_active_admin_user(pending_oauth['user_id'])
        if callback_user:
            login_user(callback_user)
    if not callback_user or callback_user.role != 'admin':
        flash('Google authorisation session expired. Please sign in and try again.')
        return redirect(url_for('login'))

    try:
        code_verifier = session.pop('gcal_code_verifier', None) or (pending_oauth['code_verifier'] if pending_oauth else None)
        redirect_uri = (
            session.pop('gcal_redirect_uri', None)
            or (pending_oauth['redirect_uri'] if pending_oauth else None)
            or build_external_public_url('google_calendar_callback')
        )
        creds = gcal.exchange_code_for_tokens(
            code, state, code_verifier=code_verifier, redirect_uri=redirect_uri)
        calendar_id = request.args.get('calendar_id', 'primary')
        gcal.save_credentials(db, creds, calendar_id=calendar_id)
        flash('Google Calendar connected successfully!')
    except Exception as exc:
        flash(f'Failed to complete Google Calendar connection: {exc}')
    return redirect(url_for('admin_profile'))


@google_calendar_bp.route('/admin/google-calendar/disconnect', methods=['POST'])
@login_required
def google_calendar_disconnect():
    from app import gcal
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    if gcal:
        gcal.delete_credentials(db)
    flash('Google Calendar disconnected.')
    return redirect(url_for('admin_profile'))


@google_calendar_bp.route('/admin/google-calendar/set-calendar', methods=['POST'])
@login_required
def google_calendar_set_calendar():
    from app import gcal
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    if not gcal:
        return jsonify({'error': 'Google libraries not installed'}), 500

    calendar_id = (request.form.get('calendar_id') or '').strip()
    if not calendar_id:
        return jsonify({'error': 'Calendar ID is required'}), 400

    db = get_db()
    creds = gcal.load_credentials(db)
    if not creds:
        return jsonify({'error': 'Google not connected'}), 400

    calendars = gcal.list_calendars(db)
    if calendars and calendar_id not in {str(item.get('id')) for item in calendars}:
        return jsonify({'error': 'Selected calendar was not found'}), 400

    gcal.save_credentials(db, creds, calendar_id=calendar_id)
    return jsonify({'status': 'success', 'calendar_id': calendar_id})
