import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash

from app import app, get_db, _run_db_migrations
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

    def test_group_sync_gdoc_returns_success_message(self):
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
            rv = self.client.post(f'/groups/{group_id}/sync-gdoc', data={})

        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertGreaterEqual(payload['synced'], 1)
        self.assertIn('group meeting record', payload['message'])

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT session_summary FROM group_sessions WHERE group_id = ?', (group_id,)).fetchone()
            self.assertEqual(row['session_summary'], 'Group process summary from doc')


if __name__ == '__main__':
    unittest.main()
