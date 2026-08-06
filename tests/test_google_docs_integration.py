import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash

from app import app, get_db, _run_db_migrations
from db_test_support import build_test_schema
from scripts.google_docs import parse_doc_into_notes
import app as app_module


class GoogleDocsIntegrationRoutesTest(unittest.TestCase):

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
            build_test_schema(self.db_path)
            db = get_db()
            _run_db_migrations(db)
            db.commit()

            db.execute(
                "INSERT INTO users (username, password_hash, role, totp_enabled, is_active) VALUES (?, ?, ?, ?, ?)",
                ('admin', generate_password_hash('password123'), 'admin', 0, 1),
            )
            db.execute(
                "INSERT INTO patients (name, status) VALUES (?, ?)",
                ('Docs Test Patient', 'ongoing'),
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

    def _login_admin(self):
        rv = self.client.post('/login', data={'username': 'admin', 'password': 'password123'}, follow_redirects=True)
        self.assertEqual(rv.status_code, 200)

    def test_link_gdoc_success_updates_patient_doc(self):
        self._login_admin()

        gdocs_mock = Mock()
        gdocs_mock.GDOCS_LIBS_AVAILABLE = True
        gdocs_mock.create_patient_doc.return_value = 'doc_abc123'

        gcal_mock = Mock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock.load_credentials.return_value = object()
        gcal_mock._refresh_and_save.return_value = object()

        with patch.object(app_module, 'gdocs', gdocs_mock), patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post('/patient/1/link-gdoc', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertIn('docs.google.com/document/d/doc_abc123/edit', payload['doc_url'])

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT gdoc_id FROM patients WHERE id = 1').fetchone()
            self.assertEqual(row['gdoc_id'], 'doc_abc123')

    def test_link_gdoc_returns_dependency_error_when_libs_missing(self):
        self._login_admin()

        gdocs_mock = Mock()
        gdocs_mock.GDOCS_LIBS_AVAILABLE = False
        gdocs_mock.GDOCS_LIBS_ERROR = 'No module named googleapiclient'

        gcal_mock = Mock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = False
        gcal_mock.GOOGLE_LIBS_ERROR = 'No module named requests'

        with patch.object(app_module, 'gdocs', gdocs_mock), patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post('/patient/1/link-gdoc', data={})

        self.assertEqual(rv.status_code, 500)
        payload = rv.get_json()
        self.assertIn('pip install -r requirements.txt', payload['error'])

    def test_detach_gdoc_clears_patient_doc(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute("UPDATE patients SET gdoc_id = ? WHERE id = 1", ('doc-to-detach',))
            db.commit()

        rv = self.client.post('/patient/1/detach-gdoc', data={})
        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT gdoc_id FROM patients WHERE id = 1').fetchone()
            self.assertIsNone(row['gdoc_id'])

    def test_group_detach_gdoc_clears_link(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Detach Group', 'therapy', 'Group docs', 'linked-doc')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.commit()

        rv = self.client.post(f'/groups/{group_id}/detach-gdoc', data={})
        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT gdoc_id FROM groups WHERE id = ?', (group_id,)).fetchone()
            self.assertIsNone(row['gdoc_id'])

    def test_parse_doc_into_notes_splits_multiple_meetings(self):
        text = (
            'SESSION #1 | 2026-04-10 [note:new]\nFirst meeting summary\n\n'
            'SESSION #2 | 2026-04-17 [note:new]\nSecond meeting summary\n'
        )
        parsed = parse_doc_into_notes(text)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['session_number'], 1)
        self.assertEqual(parsed[0]['note_date'], '2026-04-10')
        self.assertIn('First meeting summary', parsed[0]['content'])
        self.assertEqual(parsed[1]['session_number'], 2)
        self.assertEqual(parsed[1]['note_date'], '2026-04-17')

    def test_group_pull_gdoc_returns_success_message(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Docs Group', 'therapy', 'Group docs', 'group-doc-123')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute(
                "INSERT INTO group_sessions (group_id, session_date, session_time, duration_minutes, title, status) VALUES (?, ?, ?, ?, ?, ?)",
                (group_id, '2026-04-20', '17:00', 90, 'Weekly Group', 'scheduled')
            )
            db.commit()

        docs_api = Mock()
        docs_api.get.return_value.execute.return_value = {'body': {'content': [{'endIndex': 2}]}}
        docs_api.batchUpdate.return_value.execute.return_value = {}
        docs_service = Mock()
        docs_service.documents.return_value = docs_api

        gdocs_mock = Mock()
        gdocs_mock.GDOCS_LIBS_AVAILABLE = True
        gdocs_mock.read_doc_text.return_value = 'SESSION #1 | 2026-04-20 [note:new]\nGroup process summary from doc\n'
        gdocs_mock._docs_service.return_value = docs_service
        gdocs_mock.parse_doc_into_notes.side_effect = parse_doc_into_notes

        gcal_mock = Mock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock.load_credentials.return_value = object()
        gcal_mock._refresh_and_save.return_value = object()

        with patch.object(app_module, 'gdocs', gdocs_mock), patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post(f'/groups/{group_id}/pull-gdoc', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertGreaterEqual(payload['pulled'], 1)
        self.assertIn('Replaced site meeting content from Google Docs', payload['message'])

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT session_summary FROM group_sessions WHERE group_id = ?', (group_id,)).fetchone()
            self.assertEqual(row['session_summary'], 'Group process summary from doc')

    def test_group_push_gdoc_appends_new_records_only(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Docs Group Push', 'therapy', 'Group docs', 'group-doc-push-123')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute(
                "INSERT INTO group_sessions (group_id, session_date, session_time, duration_minutes, title, status) VALUES (?, ?, ?, ?, ?, ?)",
                (group_id, '2026-04-21', '17:00', 90, 'Weekly Group Push', 'scheduled')
            )
            db.commit()

        docs_api = Mock()
        docs_api.get.return_value.execute.return_value = {'body': {'content': [{'endIndex': 2}]}}
        docs_api.batchUpdate.return_value.execute.return_value = {}
        docs_service = Mock()
        docs_service.documents.return_value = docs_api

        gdocs_mock = Mock()
        gdocs_mock.GDOCS_LIBS_AVAILABLE = True
        gdocs_mock.read_doc_text.return_value = ''
        gdocs_mock._docs_service.return_value = docs_service
        gdocs_mock.parse_doc_into_notes.side_effect = parse_doc_into_notes

        gcal_mock = Mock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock.load_credentials.return_value = object()
        gcal_mock._refresh_and_save.return_value = object()

        with patch.object(app_module, 'gdocs', gdocs_mock), patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post(f'/groups/{group_id}/push-gdoc', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertGreaterEqual(payload['pushed'], 1)
        self.assertIn('Appended', payload['message'])

    def test_parse_doc_into_notes_accepts_hebrew_group_template_with_tilde(self):
        text = (
            '~פגישה 6- 23/02/26\n'
            '|משתתפים\n'
            'משה שטרן, מיכאל שפרנוב, שי בראגין, אבינועם קאה\n'
            '|חסרים\n'
            '- אופיר לא הגיע לקבוצה ולא הודיע\n'
            '- צביקה לא הגיע לקבוצה ולא הודיע\n'
            '|תוכן\n'
            'השיח בקבוצה התחיל בשתיקה, לאחר מכן שי יזם שיח.\n'
        )

        parsed = parse_doc_into_notes(text)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['session_number'], 6)
        self.assertEqual(parsed[0]['note_date'], '2026-02-23')
        self.assertIn('משה שטרן', parsed[0]['participants'])
        self.assertIn('אופיר לא הגיע לקבוצה ולא הודיע', parsed[0]['missing'])
        self.assertIn('השיח בקבוצה התחיל בשתיקה', parsed[0]['content'])

    def test_parse_doc_into_notes_accepts_semicolon_separated_inline_entries(self):
        text = (
            'פגישה 17- 02/07/26\n'
            '* משתתפים\n'
            'משה שטרן - שיתף מעט על בדידות; אבינועם קאה - תיאר קושי במגע קרוב; שי בראגין - הביא עומס רגשי\n'
            '* חסרים\n'
            'מיכאל שפורן - הודיע שלא יוכל להגיע; אופיר כתפי - איחר ולכן לא נכח ברוב המפגש\n'
            '* תוכן\n'
            'הקבוצה עסקה במתח בין קרבה לבין הסתגרות.\n'
        )

        parsed = parse_doc_into_notes(text)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['session_number'], 17)
        self.assertEqual(parsed[0]['participants'], ['משה שטרן', 'אבינועם קאה', 'שי בראגין'])
        self.assertEqual(parsed[0]['missing'], ['מיכאל שפורן', 'אופיר כתפי'])
        self.assertEqual(parsed[0]['participant_entries'][1]['note'], 'תיאר קושי במגע קרוב')
        self.assertEqual(parsed[0]['missing_entries'][0]['note'], 'הודיע שלא יוכל להגיע')

    def test_group_sync_pulls_hebrew_group_template_into_matching_history(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Hebrew Docs Group', 'therapy', 'Group docs', 'group-doc-hebrew')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute(
                "INSERT INTO group_sessions (group_id, session_date, session_time, duration_minutes, title, status) VALUES (?, ?, ?, ?, ?, ?)",
                (group_id, '2026-02-23', '18:00', 90, 'Hebrew Group', 'scheduled')
            )
            db.commit()

        hebrew_text = (
            '~פגישה 6- 23/02/26\n'
            '|משתתפים\n'
            'משה שטרן, מיכאל שפרנוב, שי בראגין, אבינועם קאה\n'
            '|חסרים\n'
            '- אופיר לא הגיע לקבוצה ולא הודיע\n'
            '|תוכן\n'
            'השיח בקבוצה התחיל בשתיקה, לאחר מכן שי יזם שיח.\n'
        )

        docs_api = Mock()
        docs_api.get.return_value.execute.return_value = {'body': {'content': [{'endIndex': 2}]}}
        docs_api.batchUpdate.return_value.execute.return_value = {}
        docs_service = Mock()
        docs_service.documents.return_value = docs_api

        gdocs_mock = Mock()
        gdocs_mock.GDOCS_LIBS_AVAILABLE = True
        gdocs_mock.read_doc_text.return_value = hebrew_text
        gdocs_mock._docs_service.return_value = docs_service
        gdocs_mock.parse_doc_into_notes.side_effect = parse_doc_into_notes

        gcal_mock = Mock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock.load_credentials.return_value = object()
        gcal_mock._refresh_and_save.return_value = object()

        with patch.object(app_module, 'gdocs', gdocs_mock), patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post(f'/groups/{group_id}/pull-gdoc', data={})

        self.assertEqual(rv.status_code, 200)

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT session_summary FROM group_sessions WHERE group_id = ?', (group_id,)).fetchone()
            self.assertIn('השיח בקבוצה התחיל בשתיקה', row['session_summary'])
            self.assertNotIn('|משתתפים', row['session_summary'])
            self.assertNotIn('|חסרים', row['session_summary'])
            self.assertNotIn('|תוכן', row['session_summary'])

    def test_group_sync_writes_hebrew_private_notes_for_participants(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute("INSERT INTO patients (name, status, patient_type) VALUES (?, ?, ?)", ('משה שטרן', 'ongoing', 'group'))
            present_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute("INSERT INTO patients (name, status, patient_type) VALUES (?, ?, ?)", ('מיכאל שפורן', 'ongoing', 'group'))
            missed_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Hebrew Notes Group', 'therapy', 'Group docs', 'group-doc-hebrew-notes')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute(
                "INSERT INTO group_member_history (group_id, patient_id, role) VALUES (?, ?, 'member')",
                (group_id, present_id)
            )
            db.execute(
                "INSERT INTO group_member_history (group_id, patient_id, role) VALUES (?, ?, 'member')",
                (group_id, missed_id)
            )
            db.commit()

        hebrew_text = (
            'פגישה 16- 25/06/26\n'
            '* משתתפים\n'
            'משה שטרן - שיתף בתחושת בדידות חריפה\n'
            '* חסרים\n'
            'מיכאל שפורן - לא הודיע על היעדרות\n'
            '* תוכן\n'
            'השיח עסק בבדידות ובקשר.\n'
        )

        docs_api = Mock()
        docs_api.get.return_value.execute.return_value = {'body': {'content': [{'endIndex': 2}]}}
        docs_api.batchUpdate.return_value.execute.return_value = {}
        docs_service = Mock()
        docs_service.documents.return_value = docs_api

        gdocs_mock = Mock()
        gdocs_mock.GDOCS_LIBS_AVAILABLE = True
        gdocs_mock.read_doc_text.return_value = hebrew_text
        gdocs_mock._docs_service.return_value = docs_service
        gdocs_mock.parse_doc_into_notes.side_effect = parse_doc_into_notes

        gcal_mock = Mock()
        gcal_mock.GOOGLE_LIBS_AVAILABLE = True
        gcal_mock.load_credentials.return_value = object()
        gcal_mock._refresh_and_save.return_value = object()

        with patch.object(app_module, 'gdocs', gdocs_mock), patch.object(app_module, 'gcal', gcal_mock):
            rv = self.client.post(f'/groups/{group_id}/pull-gdoc', data={})

        self.assertEqual(rv.status_code, 200)

        with app.app_context():
            db = get_db()
            present_note = db.execute(
                "SELECT content FROM notes WHERE patient_id = ? ORDER BY id DESC LIMIT 1",
                (present_id,)
            ).fetchone()
            missed_note = db.execute(
                "SELECT content, missed_reason, is_missed_meeting FROM notes WHERE patient_id = ? ORDER BY id DESC LIMIT 1",
                (missed_id,)
            ).fetchone()

        self.assertIn('תיעוד מקבוצת טיפול', present_note['content'])
        self.assertIn('סטטוס: נוכח', present_note['content'])
        self.assertIn('הערה: שיתף בתחושת בדידות חריפה', present_note['content'])
        self.assertIn('סטטוס: חסר', missed_note['content'])
        self.assertIn('סיבת היעדרות: לא הודיע על היעדרות', missed_note['content'])
        self.assertEqual(missed_note['missed_reason'], 'לא הודיע על היעדרות')
        self.assertEqual(int(missed_note['is_missed_meeting'] or 0), 1)

    def test_parse_doc_into_notes_two_hebrew_meetings_with_sections(self):
        text = (
            '~פגישה 9- 30/03/26\n'
            '|משתתפים\n'
            'משה שטרן, מיכאל שפרנוב , שי בראגין , אבינועם קאה, אופיר כתפי\n'
            '|חסרים\n'
            '|תוכן\n'
            'מפגש תשע תוכן קצר.\n'
            '~פגישה 10- 13/04/26\n'
            '|משתתפים\n'
            'משה שטרן, מיכאל שפרנוב , שי בראגין , אבינועם קאה, אופיר כתפי, בטואל אוסקר\n'
            '|חסרים\n'
            '|תוכן\n'
            'מפגש עשר תוכן ארוך יותר.\n'
        )

        parsed = parse_doc_into_notes(text)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['session_number'], 9)
        self.assertEqual(parsed[0]['note_date'], '2026-03-30')
        self.assertEqual(len(parsed[0]['participants']), 5)
        self.assertEqual(parsed[1]['session_number'], 10)
        self.assertEqual(parsed[1]['note_date'], '2026-04-13')
        self.assertEqual(len(parsed[1]['participants']), 6)
        self.assertIn('מפגש עשר תוכן ארוך יותר', parsed[1]['content'])

    def test_admin_profile_saves_google_docs_auto_sync_settings(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute("UPDATE patients SET gdoc_id = ? WHERE id = 1", ('patient-doc-1',))
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Auto Sync Group', 'therapy', 'Auto sync docs', 'group-doc-1')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.commit()

        rv = self.client.post('/admin/profile', data={
            'gdocs_auto_sync_enabled': '1',
            'gdocs_auto_sync_interval': 'weekly',
            'gdoc_sync_targets': ['patient:1', f'group:{group_id}'],
        }, follow_redirects=True)

        self.assertEqual(rv.status_code, 200)

        with app.app_context():
            db = get_db()
            rows = db.execute('SELECT setting_key, setting_value FROM site_settings').fetchall()
            settings = {row['setting_key']: row['setting_value'] for row in rows}

        self.assertEqual(settings.get('gdocs_auto_sync_enabled'), '1')
        self.assertEqual(settings.get('gdocs_auto_sync_interval'), 'weekly')
        self.assertEqual(
            settings.get('gdocs_auto_sync_targets_json'),
            json.dumps(['patient:1', f'group:{group_id}'])
        )

    def test_auto_sync_now_runs_selected_targets(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute("UPDATE patients SET gdoc_id = ? WHERE id = 1", ('patient-doc-1',))
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Auto Sync Group Run', 'therapy', 'Auto sync docs', 'group-doc-2')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_enabled', '1')
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_interval', 'daily')
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_targets_json', json.dumps(['patient:1', f'group:{group_id}']))
            )
            db.commit()

        with patch.object(app_module, '_google_docs_dependency_error', return_value=None), \
             patch.object(app_module, '_pull_gdoc_notes', return_value=(2, None)), \
             patch.object(app_module, '_pull_group_gdoc_notes', return_value=(3, None)):
            rv = self.client.post('/admin/google-docs/auto-sync-now', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['synced'], 5)
        self.assertEqual(payload['patients'], 1)
        self.assertEqual(payload['groups'], 1)

    def test_auto_sync_now_without_selected_targets_syncs_all_connected_docs(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute("UPDATE patients SET gdoc_id = ? WHERE id = 1", ('patient-doc-fallback',))
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_enabled', '1')
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_targets_json', json.dumps([]))
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_targets_config_json', json.dumps([]))
            )
            db.commit()

        with patch.object(app_module, '_google_docs_dependency_error', return_value=None), \
             patch.object(app_module, '_pull_gdoc_notes', return_value=(2, None)):
            rv = self.client.post('/admin/google-docs/auto-sync-now', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['synced'], 2)
        self.assertEqual(payload['patients'], 1)

    def test_auto_sync_now_group_two_way_mode_pushes_and_writes_history(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Auto Sync Group Two Way', 'therapy', 'Auto sync docs', 'group-doc-3')
            )
            group_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_enabled', '1')
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_interval', 'daily')
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_targets_config_json', json.dumps([{'target_key': f'group:{group_id}', 'mode': 'both'}]))
            )
            db.commit()

        with patch.object(app_module, '_google_docs_dependency_error', return_value=None), \
             patch.object(app_module, '_pull_group_gdoc_notes', return_value=(2, None)), \
             patch.object(app_module, '_sync_group_gdoc_sessions', return_value=(4, None)):
            rv = self.client.post('/admin/google-docs/auto-sync-now', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['synced'], 6)
        self.assertEqual(payload['groups'], 1)
        self.assertEqual(payload['pushed_groups'], 1)

        with app.app_context():
            db = get_db()
            history = db.execute('SELECT status, synced_total, pushed_groups FROM gdocs_sync_history ORDER BY id DESC LIMIT 1').fetchone()
        self.assertIsNotNone(history)
        self.assertIn(history['status'], ('success', 'partial'))
        self.assertEqual(int(history['synced_total'] or 0), 6)
        self.assertEqual(int(history['pushed_groups'] or 0), 1)

    def test_auto_sync_all_targets_skipped_records_partial_not_success(self):
        """When all selected targets lose their gdoc_id between state load and sync, status must not be 'success'."""
        self._login_admin()

        with app.app_context():
            db = get_db()
            # Patient has NO gdoc_id — will be skipped by the sync loop's DB re-check
            db.execute("UPDATE patients SET gdoc_id = NULL WHERE id = 1")
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_enabled', '1')
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_targets_json', json.dumps(['patient:1']))
            )
            db.commit()

        with patch.object(app_module, '_google_docs_dependency_error', return_value=None), \
             patch.object(app_module, '_get_google_docs_auto_sync_state') as mock_state:
            # State resolves selected_targets so the sync loop runs, but DB has no gdoc_id
            mock_state.return_value = {
                'enabled': True,
                'interval_key': 'daily',
                'selected_target_keys': ['patient:1'],
                'selected_targets': [{'target_key': 'patient:1', 'target_type': 'patient', 'target_id': 1, 'mode': 'pull', 'label': 'Test Patient'}],
                'last_run_at': None,
                'last_run_at_raw': '',
                'connected_docs': [],
            }
            rv = self.client.post('/admin/google-docs/auto-sync-now', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')

        with app.app_context():
            db = get_db()
            history = db.execute('SELECT status, synced_total FROM gdocs_sync_history ORDER BY id DESC LIMIT 1').fetchone()
        self.assertIsNotNone(history)
        # Must NOT be 'success' when nothing was actually processed
        self.assertNotEqual(history['status'], 'success')
        self.assertEqual(int(history['synced_total'] or 0), 0)

    def test_gdocs_auto_sync_health_includes_last_synced_total(self):
        """_get_gdocs_auto_sync_health must include last_synced_total from history."""
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute("UPDATE patients SET gdoc_id = 'patient-doc-health' WHERE id = 1")
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_enabled', '1')
            )
            db.execute(
                'INSERT INTO site_settings (setting_key, setting_value) VALUES (?, ?) '
                'ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',
                ('gdocs_auto_sync_targets_json', json.dumps(['patient:1']))
            )
            # Insert a fake history row
            db.execute(
                '''INSERT INTO gdocs_sync_history
                   (trigger_source, status, interval_key, targets_total, targets_processed,
                    synced_total, synced_patients, synced_groups, pushed_groups, errors_json, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                ('manual', 'success', 'daily', 1, 1, 7, 1, 0, 0, '[]', '[]')
            )
            db.commit()

        with app.app_context():
            db = get_db()
            health = app_module._get_gdocs_auto_sync_health(db)

        self.assertIn('last_synced_total', health)
        self.assertEqual(health['last_synced_total'], 7)
        self.assertEqual(health['last_status'], 'success')

    def test_admin_questionnaire_options_returns_sheet_titles(self):
        self._login_admin()

        with patch.object(app_module, '_list_questionnaire_tabs', return_value=([
            {'sheet_id': 101, 'title': 'Initial Intake'},
            {'sheet_id': 102, 'title': 'Mood Tracker'},
        ], None)):
            rv = self.client.get('/admin/questionnaires/options')

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload.get('status'), 'ok')
        self.assertEqual(payload.get('options'), ['Initial Intake', 'Mood Tracker'])

    def test_save_questionnaires_updates_existing_linked_sheet(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute('''
                UPDATE patients
                SET has_questionnaire_tab = 1,
                    questionnaires_file_id = ?,
                    questionnaires_file_url = ?,
                    questionnaires_selected = ?
                WHERE id = 1
            ''', (
                'linked-sheet-123',
                'https://docs.google.com/spreadsheets/d/linked-sheet-123/edit',
                json.dumps(['Initial Intake'])
            ))
            db.commit()

        copy_result = {
            'copied_titles': ['Mood Tracker'],
            'skipped_existing_titles': ['Initial Intake'],
            'missing_titles': [],
        }
        with patch.object(app_module, '_copy_questionnaire_tabs_to_spreadsheet', return_value=(copy_result, None)):
            rv = self.client.post(
                '/patient/1/save_questionnaires',
                data={'questionnaire_titles': ['Initial Intake', 'Mood Tracker']},
                follow_redirects=True,
            )

        self.assertEqual(rv.status_code, 200)
        with app.app_context():
            db = get_db()
            row = db.execute(
                'SELECT questionnaires_file_id, questionnaires_selected FROM patients WHERE id = 1'
            ).fetchone()

        self.assertEqual(row['questionnaires_file_id'], 'linked-sheet-123')
        self.assertEqual(
            json.loads(row['questionnaires_selected']),
            ['Initial Intake', 'Mood Tracker']
        )

    def test_save_questionnaires_creates_and_links_new_sheet_when_missing(self):
        self._login_admin()

        with app.app_context():
            db = get_db()
            db.execute('''
                UPDATE patients
                SET has_questionnaire_tab = 1,
                    questionnaires_file_id = NULL,
                    questionnaires_file_url = NULL,
                    questionnaires_selected = NULL
                WHERE id = 1
            ''')
            db.commit()

        create_result = {
            'spreadsheet_id': 'new-sheet-456',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/new-sheet-456/edit',
            'selected_titles': ['Initial Intake', 'Mood Tracker'],
        }
        with patch.object(app_module, '_create_diagnosee_questionnaires_sheet', return_value=(create_result, None)):
            rv = self.client.post(
                '/patient/1/save_questionnaires',
                data={'questionnaire_titles': ['Initial Intake', 'Mood Tracker']},
                follow_redirects=True,
            )

        self.assertEqual(rv.status_code, 200)
        with app.app_context():
            db = get_db()
            row = db.execute(
                'SELECT questionnaires_file_id, questionnaires_file_url, questionnaires_selected FROM patients WHERE id = 1'
            ).fetchone()

        self.assertEqual(row['questionnaires_file_id'], 'new-sheet-456')
        self.assertEqual(row['questionnaires_file_url'], 'https://docs.google.com/spreadsheets/d/new-sheet-456/edit')
        self.assertEqual(
            json.loads(row['questionnaires_selected']),
            ['Initial Intake', 'Mood Tracker']
        )


if __name__ == '__main__':
    unittest.main()
