"""
Google Calendar integration for the Private Clinic app.

Requirements:
    GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set as environment variables
    (or in a .env file) for the OAuth flow to work.

Usage:
    - Admin visits /admin/google-calendar/connect to start the OAuth flow.
    - After authorisation the tokens are persisted in the DB (google_calendar_tokens table).
    - Call sync_appointment_to_google() / delete_event_from_google() from booking routes
      to keep the clinic calendar mirrored in Google Calendar.
"""
import os
import json
import sqlite3
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Soft-import Google libs so the app still starts without them
# ---------------------------------------------------------------------------
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# Full scope list (kept for backward-compat; prefer INTEGRATION_SCOPES below)
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
]

# Per-integration scope mapping.  Keys are the short names shown in the UI.
INTEGRATION_SCOPES = {
    'calendar': ['https://www.googleapis.com/auth/calendar'],
    'docs': [
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/documents',
    ],
    'sheets': ['https://www.googleapis.com/auth/spreadsheets'],
}
ALL_INTEGRATIONS = list(INTEGRATION_SCOPES.keys())  # ['calendar', 'docs', 'sheets']

DB_TOKEN_TABLE = 'google_calendar_tokens'
DEFAULT_USER_LABEL = 'admin'   # stored as "owner" in the tokens table


def get_scopes_for_integrations(integrations) -> list:
    """Return the OAuth scope list for the given integration names.

    ``integrations`` may be a list/set of strings like ['calendar', 'docs'].
    Unknown names are silently ignored.  Falls back to ALL SCOPES when the
    supplied list is empty or None.
    """
    if not integrations:
        return list(SCOPES)
    result = []
    seen = set()
    for name in integrations:
        for scope in INTEGRATION_SCOPES.get(name, []):
            if scope not in seen:
                seen.add(scope)
                result.append(scope)
    return result if result else list(SCOPES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_secrets_available() -> bool:
    return bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))


def _client_config() -> dict:
    return {
        'web': {
            'client_id': os.environ.get('GOOGLE_CLIENT_ID', ''),
            'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET', ''),
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [_redirect_uri()],
        }
    }


def _redirect_uri() -> str:
    base = os.environ.get('APP_BASE_URL', 'http://localhost:5000').rstrip('/')
    return f'{base}/admin/google-calendar/callback'


# ---------------------------------------------------------------------------
# Token persistence (stored as JSON in the DB)
# ---------------------------------------------------------------------------

def _ensure_token_table(db: sqlite3.Connection):
    db.execute('''
        CREATE TABLE IF NOT EXISTS google_calendar_tokens (
            id INTEGER PRIMARY KEY,
            owner TEXT NOT NULL DEFAULT 'admin',
            token_json TEXT NOT NULL,
            calendar_id TEXT NOT NULL DEFAULT 'primary',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.commit()


def load_credentials(db: sqlite3.Connection):
    """Return a Credentials object if a stored token exists, or None."""
    if not GOOGLE_LIBS_AVAILABLE:
        return None
    _ensure_token_table(db)
    row = db.execute(
        'SELECT token_json FROM google_calendar_tokens WHERE owner = ? LIMIT 1',
        (DEFAULT_USER_LABEL,)
    ).fetchone()
    if not row:
        return None
    try:
        token_data = json.loads(row['token_json'])
        creds = Credentials(
            token=token_data.get('token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID', ''),
            client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET', ''),
            scopes=token_data.get('scopes', SCOPES),
        )
        return creds
    except Exception:
        return None


def save_credentials(db: sqlite3.Connection, creds, calendar_id: str = 'primary'):
    """Persist (or update) OAuth credentials in the DB."""
    _ensure_token_table(db)
    token_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes) if creds.scopes else SCOPES,
    }
    token_json = json.dumps(token_data)
    existing = db.execute(
        'SELECT id FROM google_calendar_tokens WHERE owner = ?',
        (DEFAULT_USER_LABEL,)
    ).fetchone()
    now = datetime.now().isoformat()
    if existing:
        db.execute(
            'UPDATE google_calendar_tokens SET token_json = ?, calendar_id = ?, updated_at = ? WHERE owner = ?',
            (token_json, calendar_id, now, DEFAULT_USER_LABEL)
        )
    else:
        db.execute(
            'INSERT INTO google_calendar_tokens (owner, token_json, calendar_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            (DEFAULT_USER_LABEL, token_json, calendar_id, now, now)
        )
    db.commit()


def delete_credentials(db: sqlite3.Connection):
    _ensure_token_table(db)
    db.execute('DELETE FROM google_calendar_tokens WHERE owner = ?', (DEFAULT_USER_LABEL,))
    db.commit()


def get_calendar_id(db: sqlite3.Connection) -> str:
    _ensure_token_table(db)
    row = db.execute(
        'SELECT calendar_id FROM google_calendar_tokens WHERE owner = ? LIMIT 1',
        (DEFAULT_USER_LABEL,)
    ).fetchone()
    return (row['calendar_id'] if row else None) or 'primary'


def is_connected(db: sqlite3.Connection) -> bool:
    _ensure_token_table(db)
    row = db.execute(
        'SELECT id FROM google_calendar_tokens WHERE owner = ? LIMIT 1',
        (DEFAULT_USER_LABEL,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

def create_oauth_flow(state: str = None, scopes=None) -> 'Flow':
    if not GOOGLE_LIBS_AVAILABLE:
        raise RuntimeError('Google API libraries are not installed.')
    if not _client_secrets_available():
        raise RuntimeError('GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set.')
    flow = Flow.from_client_config(
        _client_config(),
        scopes=scopes if scopes else SCOPES,
        state=state,
        redirect_uri=_redirect_uri(),
    )
    return flow


def get_authorization_url(integrations=None) -> tuple:
    """Return (auth_url, state, code_verifier). code_verifier may be None.

    ``integrations`` is an optional list of integration names (e.g.
    ['calendar', 'docs']).  When supplied only the matching OAuth scopes
    are requested.  When omitted all scopes are requested.
    """
    scopes = get_scopes_for_integrations(integrations)
    flow = create_oauth_flow(scopes=scopes)
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )
    code_verifier = getattr(flow, 'code_verifier', None)
    return auth_url, state, code_verifier


def exchange_code_for_tokens(code: str, state: str, code_verifier: str = None):
    """Exchange the OAuth code for credentials. Returns Credentials."""
    flow = create_oauth_flow(state=state)
    flow.fetch_token(code=code)
    return flow.credentials


# ---------------------------------------------------------------------------
# Calendar API wrappers
# ---------------------------------------------------------------------------

def _build_service(creds):
    return build('calendar', 'v3', credentials=creds, cache_discovery=False)


def _refresh_and_save(db, creds):
    """Refresh the token if expired and persist the updated credentials."""
    if not creds.valid and creds.refresh_token:
        from google.auth.transport.requests import Request
        from google.auth.exceptions import RefreshError
        try:
            creds.refresh(Request())
            save_credentials(db, creds, get_calendar_id(db))
        except RefreshError as e:
            # Token has been revoked or expired and cannot be refreshed
            # RefreshError args can be:
            # - (message_str, error_dict) tuple
            # - just a message string
            error_str = str(e)
            error_args = str(e.args) if hasattr(e, 'args') else ''
            
            # Check for invalid_grant in multiple places
            if ('invalid_grant' in error_str or
                'invalid_grant' in error_args or
                'revoked' in error_str.lower()):
                # Clear the invalid token so user must reconnect
                db.execute('DELETE FROM google_calendar_tokens WHERE owner = ?', (DEFAULT_USER_LABEL,))
                db.commit()
                raise Exception('Google authentication expired. Please reconnect via Admin Profile → Google Calendar.')
            raise
    return creds


def list_calendars(db: sqlite3.Connection) -> list:
    """Return a list of {'id': ..., 'summary': ...} dicts for all calendars."""
    creds = load_credentials(db)
    if not creds:
        return []
    try:
        creds = _refresh_and_save(db, creds)
        service = _build_service(creds)
        result = service.calendarList().list().execute()
        return [
            {'id': c['id'], 'summary': c.get('summary', c['id'])}
            for c in result.get('items', [])
        ]
    except Exception:
        return []


def list_events_for_week(db: sqlite3.Connection, week_start_iso: str, week_end_iso: str) -> list:
    """Return Google Calendar events for the given week as a list of dicts.

    Each dict has: google_event_id, title, start (ISO datetime), end (ISO datetime), description.
    Returns [] if not connected or on any error.
    """
    if not GOOGLE_LIBS_AVAILABLE:
        return []
    creds = load_credentials(db)
    if not creds:
        return []
    try:
        creds = _refresh_and_save(db, creds)
        service = _build_service(creds)
        calendar_id = get_calendar_id(db)
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=f'{week_start_iso}T00:00:00Z',
            timeMax=f'{week_end_iso}T23:59:59Z',
            singleEvents=True,
            orderBy='startTime',
            maxResults=200,
        ).execute()
        events = []
        for item in result.get('items', []):
            start = item.get('start', {})
            end = item.get('end', {})
            events.append({
                'google_event_id': item.get('id', ''),
                'title': item.get('summary', ''),
                'start': start.get('dateTime') or start.get('date', ''),
                'end': end.get('dateTime') or end.get('date', ''),
                'description': item.get('description', ''),
            })
        return events
    except Exception as exc:
        print(f'[Google Calendar] list_events_for_week failed: {exc}')
        return []


def sync_appointment_to_google(
    db: sqlite3.Connection,
    appointment_id: int,
    patient_name: str,
    date_iso: str,
    time_str: str,
    duration_minutes: int,
    meeting_type: str = 'in-person',
    meeting_link: str = '',
    google_event_id: str = None,
) -> str | None:
    """
    Create or update a Google Calendar event for an appointment.
    Returns the Google event ID, or None on failure / no connection.
    Only syncs when the appointment's save_to_google flag is truthy *or* a
    google_event_id already exists (i.e. it was previously synced).
    """
    if not GOOGLE_LIBS_AVAILABLE:
        return None
    creds = load_credentials(db)
    if not creds:
        return None

    try:
        creds = _refresh_and_save(db, creds)
        service = _build_service(creds)
        calendar_id = get_calendar_id(db)

        start_dt = datetime.fromisoformat(f'{date_iso}T{time_str or "00:00"}')
        end_dt = start_dt + timedelta(minutes=int(duration_minutes or 60))

        description_parts = [f'Appointment #{appointment_id}']
        if meeting_type and meeting_type != 'in-person':
            description_parts.append(f'Type: {meeting_type}')
        if meeting_link:
            description_parts.append(f'Link: {meeting_link}')

        event_body = {
            'summary': f'Appointment – {patient_name}',
            'description': '\n'.join(description_parts),
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Jerusalem'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Jerusalem'},
        }
        if meeting_link:
            event_body['location'] = meeting_link

        if google_event_id:
            event = service.events().update(
                calendarId=calendar_id, eventId=google_event_id, body=event_body
            ).execute()
        else:
            event = service.events().insert(
                calendarId=calendar_id, body=event_body
            ).execute()

        event_id = event.get('id')
        # Persist the google_event_id on the appointment row
        try:
            db.execute(
                'UPDATE appointments SET google_event_id = ? WHERE id = ?',
                (event_id, appointment_id)
            )
            db.commit()
        except Exception:
            pass  # column may not exist yet; handled by migration
        return event_id

    except Exception as exc:
        print(f'[Google Calendar] sync_appointment_to_google failed: {exc}')
        return None


def delete_event_from_google(db: sqlite3.Connection, google_event_id: str) -> bool:
    """Delete a previously synced event from Google Calendar. Returns True on success."""
    if not GOOGLE_LIBS_AVAILABLE or not google_event_id:
        return False
    creds = load_credentials(db)
    if not creds:
        return False
    try:
        creds = _refresh_and_save(db, creds)
        service = _build_service(creds)
        calendar_id = get_calendar_id(db)
        service.events().delete(calendarId=calendar_id, eventId=google_event_id).execute()
        return True
    except Exception as exc:
        print(f'[Google Calendar] delete_event_from_google failed: {exc}')
        return False


def sync_group_session_to_google(
    db: sqlite3.Connection,
    session_id: int,
    group_name: str,
    date_iso: str,
    time_str: str,
    duration_minutes: int,
    facilitator: str = '',
    google_event_id: str = None,
) -> str | None:
    """Create or update a Google Calendar event for a group session."""
    if not GOOGLE_LIBS_AVAILABLE:
        return None
    creds = load_credentials(db)
    if not creds:
        return None
    try:
        creds = _refresh_and_save(db, creds)
        service = _build_service(creds)
        calendar_id = get_calendar_id(db)

        start_dt = datetime.fromisoformat(f'{date_iso}T{time_str or "00:00"}')
        end_dt = start_dt + timedelta(minutes=int(duration_minutes or 60))
        desc = f'Group session #{session_id}'
        if facilitator:
            desc += f'\nFacilitator: {facilitator}'

        event_body = {
            'summary': f'Group: {group_name}',
            'description': desc,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Jerusalem'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Jerusalem'},
        }
        if google_event_id:
            event = service.events().update(
                calendarId=calendar_id, eventId=google_event_id, body=event_body
            ).execute()
        else:
            event = service.events().insert(
                calendarId=calendar_id, body=event_body
            ).execute()

        event_id = event.get('id')
        try:
            db.execute(
                'UPDATE group_sessions SET google_event_id = ? WHERE id = ?',
                (event_id, session_id)
            )
            db.commit()
        except Exception:
            pass
        return event_id
    except Exception as exc:
        print(f'[Google Calendar] sync_group_session_to_google failed: {exc}')
        return None
