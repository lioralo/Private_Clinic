"""
Tests for Google OAuth flow: connect, callback, disconnect, integration scope selector.

Covers:
  - get_scopes_for_integrations()
  - OAuth state validation (missing state → rejected)
  - connect POST saves google_enabled_integrations setting
  - connect GET uses saved integrations
  - disconnect clears credentials
  - _refresh_and_save DELETE only removes the admin row
  - google_calendar_status includes enabled_integrations
"""
import json
import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import google_calendar as gcal_module

from app import app, get_db, _run_db_migrations
import app as app_module


# ---------------------------------------------------------------------------
# Unit tests for google_calendar helpers (no Flask needed)
# ---------------------------------------------------------------------------

class TestGetScopesForIntegrations(unittest.TestCase):

    def test_all_integrations_returns_all_scopes(self):
        scopes = gcal_module.get_scopes_for_integrations(['calendar', 'docs', 'sheets'])
        self.assertIn('https://www.googleapis.com/auth/calendar', scopes)
        self.assertIn('https://www.googleapis.com/auth/documents', scopes)
        self.assertIn('https://www.googleapis.com/auth/spreadsheets', scopes)

    def test_calendar_only(self):
        scopes = gcal_module.get_scopes_for_integrations(['calendar'])
        self.assertIn('https://www.googleapis.com/auth/calendar', scopes)
        self.assertNotIn('https://www.googleapis.com/auth/documents', scopes)
        self.assertNotIn('https://www.googleapis.com/auth/spreadsheets', scopes)

    def test_docs_only(self):
        scopes = gcal_module.get_scopes_for_integrations(['docs'])
        self.assertIn('https://www.googleapis.com/auth/documents', scopes)
        self.assertIn('https://www.googleapis.com/auth/drive.file', scopes)
        self.assertNotIn('https://www.googleapis.com/auth/calendar', scopes)

    def test_sheets_only(self):
        scopes = gcal_module.get_scopes_for_integrations(['sheets'])
        self.assertIn('https://www.googleapis.com/auth/spreadsheets', scopes)
        self.assertNotIn('https://www.googleapis.com/auth/calendar', scopes)

    def test_none_returns_all_scopes(self):
        scopes = gcal_module.get_scopes_for_integrations(None)
        self.assertEqual(scopes, list(gcal_module.SCOPES))

    def test_empty_list_returns_all_scopes(self):
        scopes = gcal_module.get_scopes_for_integrations([])
        self.assertEqual(scopes, list(gcal_module.SCOPES))

    def test_unknown_names_silently_dropped(self):
        scopes = gcal_module.get_scopes_for_integrations(['calendar', 'nonexistent'])
        self.assertIn('https://www.googleapis.com/auth/calendar', scopes)
        self.assertEqual(len(scopes), 1)

    def test_no_duplicate_scopes(self):
        scopes = gcal_module.get_scopes_for_integrations(['calendar', 'docs', 'sheets', 'calendar'])
        self.assertEqual(len(scopes), len(set(scopes)))


class TestRefreshAndSaveDeleteScope(unittest.TestCase):
    """_refresh_and_save must DELETE only the admin row, not all rows."""

    def test_refresh_error_deletes_only_admin_row(self):
        if not gcal_module.GOOGLE_LIBS_AVAILABLE:
            self.skipTest('Google libs not installed')
        from google.auth.exceptions import RefreshError

        mock_db = MagicMock()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.refresh_token = 'some-token'

        with patch.object(gcal_module, 'save_credentials'), \
             patch.object(gcal_module, 'get_calendar_id', return_value='primary'):
            mock_creds.refresh.side_effect = RefreshError('invalid_grant', {'error': 'invalid_grant'})
            with self.assertRaises(Exception) as ctx:
                gcal_module._refresh_and_save(mock_db, mock_creds)

        self.assertIn('reconnect', str(ctx.exception).lower())
        # Must use WHERE clause — not a bare DELETE
        delete_call_args = mock_db.execute.call_args_list
        delete_calls = [str(c) for c in delete_call_args if 'delete' in str(c).lower()]
        self.assertTrue(any('where' in c.lower() for c in delete_calls),
                        f'DELETE call must include a WHERE clause, got: {delete_calls}')


# ---------------------------------------------------------------------------
# Integration tests (Flask test client)
# ---------------------------------------------------------------------------

class GoogleOAuthRoutesTest(unittest.TestCase):

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.upload_dir = tempfile.mkdtemp()
        self.patient_logs_dir = tempfile.mkdtemp()
        self.app_log_fd, self.app_log_path = tempfile.mkstemp()

        app.config['DATABASE'] = self.db_path
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['UPLOAD_FOLDER'] = self.upload_dir
        app.config['PATIENT_LOGS_FOLDER'] = self.patient_logs_dir
        app.config['APP_LOG_FILE'] = self.app_log_path

        self.client = app.test_client()

        with app.app_context():
            db = get_db()
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()
            _run_db_migrations(db)
            db.commit()
            db.execute(
                "INSERT INTO users (username, password_hash, role, totp_enabled, is_active) VALUES (?, ?, ?, ?, ?)",
                ('admin', generate_password_hash('password123'), 'admin', 0, 1),
            )
            db.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)
        os.close(self.app_log_fd)
        if os.path.exists(self.app_log_path):
            os.unlink(self.app_log_path)
        shutil.rmtree(self.upload_dir, ignore_errors=True)
        shutil.rmtree(self.patient_logs_dir, ignore_errors=True)

    def _login(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'password123'}, follow_redirects=True)

    # ------------------------------------------------------------------
    # connect
    # ------------------------------------------------------------------

    def test_connect_post_saves_integration_selection_and_redirects(self):
        self._login()
        gcal_mock = MagicMock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock._client_secrets_available.return_value = True
        gcal_mock.get_authorization_url.return_value = ('https://accounts.google.com/auth?foo', 'test-state', None)
        gcal_mock.INTEGRATION_SCOPES = gcal_module.INTEGRATION_SCOPES

        with patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post('/admin/google-calendar/connect', data={
                'google_integration': ['calendar', 'docs'],
            }, follow_redirects=False)

        self.assertIn(rv.status_code, (301, 302, 303))
        # Verify the setting was saved
        with app.app_context():
            db = get_db()
            row = db.execute("SELECT setting_value FROM site_settings WHERE setting_key = 'google_enabled_integrations'").fetchone()
        self.assertIsNotNone(row)
        saved = json.loads(row['setting_value'])
        self.assertIn('calendar', saved)
        self.assertIn('docs', saved)
        self.assertNotIn('sheets', saved)

    def test_connect_post_passes_integrations_to_get_authorization_url(self):
        self._login()
        gcal_mock = MagicMock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock._client_secrets_available.return_value = True
        gcal_mock.get_authorization_url.return_value = ('https://accounts.google.com/auth', 'st', None)
        gcal_mock.INTEGRATION_SCOPES = gcal_module.INTEGRATION_SCOPES

        with patch.object(app_module, 'gcal', gcal_mock):
            self.client.post('/admin/google-calendar/connect', data={
                'google_integration': ['calendar'],
            }, follow_redirects=False)

        gcal_mock.get_authorization_url.assert_called_once()
        call_kwargs = gcal_mock.get_authorization_url.call_args[1]
        self.assertEqual(call_kwargs.get('integrations'), ['calendar'])

    def test_connect_get_uses_saved_integrations_setting(self):
        self._login()
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO site_settings (setting_key, setting_value) VALUES ('google_enabled_integrations', ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                (json.dumps(['docs']),),
            )
            db.commit()

        gcal_mock = MagicMock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock._client_secrets_available.return_value = True
        gcal_mock.get_authorization_url.return_value = ('https://accounts.google.com/auth', 'st', None)
        gcal_mock.INTEGRATION_SCOPES = gcal_module.INTEGRATION_SCOPES

        with patch.object(app_module, 'gcal', gcal_mock):
            self.client.get('/admin/google-calendar/connect', follow_redirects=False)

        gcal_mock.get_authorization_url.assert_called_once()
        call_kwargs = gcal_mock.get_authorization_url.call_args[1]
        self.assertEqual(call_kwargs.get('integrations'), ['docs'])

    # ------------------------------------------------------------------
    # callback state validation
    # ------------------------------------------------------------------

    def test_callback_rejects_when_no_state_in_session(self):
        """If session has no stored state the callback must reject, not proceed."""
        self._login()
        # Do NOT set gcal_oauth_state in session — simulate lost session
        rv = self.client.get('/admin/google-calendar/callback?code=abc&state=anything', follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'state mismatch', rv.data.lower())

    def test_callback_rejects_mismatched_state(self):
        self._login()
        with self.client.session_transaction() as sess:
            sess['gcal_oauth_state'] = 'correct-state'

        rv = self.client.get('/admin/google-calendar/callback?code=abc&state=wrong-state', follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'state mismatch', rv.data.lower())

    def test_callback_proceeds_with_matching_state(self):
        self._login()
        with self.client.session_transaction() as sess:
            sess['gcal_oauth_state'] = 'good-state'

        gcal_mock = MagicMock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        mock_creds = MagicMock()
        gcal_mock.exchange_code_for_tokens.return_value = mock_creds
        gcal_mock.save_credentials.return_value = None

        with patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.get(
                '/admin/google-calendar/callback?code=abc&state=good-state',
                follow_redirects=True,
            )
        self.assertEqual(rv.status_code, 200)
        gcal_mock.exchange_code_for_tokens.assert_called_once()

    # ------------------------------------------------------------------
    # disconnect
    # ------------------------------------------------------------------

    def test_disconnect_calls_delete_credentials(self):
        self._login()
        gcal_mock = MagicMock()
        gcal_mock.delete_credentials.return_value = None

        with patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post('/admin/google-calendar/disconnect', data={}, follow_redirects=True)

        self.assertEqual(rv.status_code, 200)
        gcal_mock.delete_credentials.assert_called_once()

    # ------------------------------------------------------------------
    # status endpoint
    # ------------------------------------------------------------------

    def test_status_includes_enabled_integrations(self):
        self._login()
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO site_settings (setting_key, setting_value) VALUES ('google_enabled_integrations', ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                (json.dumps(['calendar', 'sheets']),),
            )
            db.commit()

        gcal_mock = MagicMock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock._client_secrets_available.return_value = True
        gcal_mock.is_connected.return_value = False
        gcal_mock.get_calendar_id.return_value = None
        gcal_mock.list_calendars.return_value = []

        with patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.get('/admin/google-calendar/status')

        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertIn('enabled_integrations', data)
        self.assertIn('calendar', data['enabled_integrations'])
        self.assertIn('sheets', data['enabled_integrations'])
        self.assertNotIn('docs', data['enabled_integrations'])

    def test_admin_profile_server_renders_disconnect_when_connected(self):
        self._login()
        gcal_mock = MagicMock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock._client_secrets_available.return_value = True
        gcal_mock.is_connected.return_value = True
        gcal_mock.get_calendar_id.return_value = 'primary'
        gcal_mock.list_calendars.return_value = [{'id': 'primary', 'summary': 'Primary'}]

        with patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.get('/admin/profile')

        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'Disconnect Google', rv.data)

    def test_admin_profile_server_renders_connect_when_disconnected(self):
        self._login()
        gcal_mock = MagicMock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock._client_secrets_available.return_value = True
        gcal_mock.is_connected.return_value = False
        gcal_mock.get_calendar_id.return_value = None
        gcal_mock.list_calendars.return_value = []

        with patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.get('/admin/profile')

        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'Connect with Google', rv.data)


if __name__ == '__main__':
    unittest.main()
