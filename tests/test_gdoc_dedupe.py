"""Regression tests for Google Docs -> meeting-notes de-duplication.

These prove the pull is idempotent: syncing the same Google Doc more than once
(even after the text is edited in the doc) must never create duplicate rows for
the same meeting. The tests round-trip the REAL stamping logic against a mutable
in-memory document buffer so the whole chain (read -> parse -> insert -> stamp ->
re-read -> match-by-id) is exercised, with only the Google API transport faked.
"""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import app, get_db, _run_db_migrations
import app as app_module
from scripts import google_docs as gdoc_module


def _fake_doc_content(text, start=1):
    """Build a Google Docs ``body.content`` list from plain text, one paragraph
    per line, with contiguous ``startIndex`` values beginning at ``start``."""
    content = []
    idx = start
    for line in text.splitlines(keepends=True):
        content.append({'paragraph': {'elements': [{
            'startIndex': idx,
            'endIndex': idx + len(line),
            'textRun': {'content': line},
        }]}})
        idx += len(line)
    return content


class _Exec:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _FakeDocuments:
    """Simulates svc.documents() backed by a mutable text buffer. Character
    index ``d`` maps to text offset ``d - 1`` (contiguous, start=1)."""

    def __init__(self, backend):
        self._backend = backend

    def get(self, documentId=None):
        return _Exec({'body': {'content': _fake_doc_content(self._backend.text)}})

    def batchUpdate(self, documentId=None, body=None):
        for req in (body or {}).get('requests', []):
            if 'deleteContentRange' in req:
                rng = req['deleteContentRange']['range']
                start = rng['startIndex'] - 1
                end = rng['endIndex'] - 1
                self._backend.text = self._backend.text[:start] + self._backend.text[end:]
            elif 'insertText' in req:
                loc = req['insertText']['location']['index'] - 1
                self._backend.text = (
                    self._backend.text[:loc]
                    + req['insertText']['text']
                    + self._backend.text[loc:]
                )
        return _Exec({})


class _DocBackend:
    def __init__(self, text):
        self.text = text


class _FakeService:
    def __init__(self, backend):
        self._documents = _FakeDocuments(backend)

    def documents(self):
        return self._documents


class _FakeGdocs:
    """Stand-in for the ``gdocs`` module that uses the REAL parser and stamper
    but reads/writes the in-memory ``backend`` buffer instead of Google."""

    GDOCS_LIBS_AVAILABLE = True

    def __init__(self, backend):
        self.backend = backend
        self.parse_doc_into_notes = gdoc_module.parse_doc_into_notes

    def read_doc_text(self, creds, doc_id):
        return self.backend.text

    def stamp_note_id_in_doc(self, creds, doc_id, new_id, session_header=None):
        return gdoc_module.stamp_note_id_in_doc(
            creds, doc_id, new_id, session_header=session_header
        )


class GoogleDocsDedupeTest(unittest.TestCase):

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app.config['DATABASE'] = self.db_path
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        with app.app_context():
            db = get_db()
            with app.open_resource('clinic_app/schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()
            _run_db_migrations(db)
            db.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _fake_gcal(self):
        gcal = Mock()
        gcal.GOOGLE_LIBS_AVAILABLE = True
        gcal.load_credentials.return_value = object()
        gcal._refresh_and_save.return_value = object()
        return gcal

    def test_patient_pull_is_idempotent_across_repeats_and_edits(self):
        backend = _DocBackend('פגישה 6- 23/02/26\nHebrew session notes\n')
        fake_gdocs = _FakeGdocs(backend)
        fake_gcal = self._fake_gcal()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO patients (name, status, gdoc_id) VALUES (?, ?, ?)",
                ('Dedupe Patient', 'ongoing', 'patient-doc-1'),
            )
            db.commit()
            patient = db.execute("SELECT * FROM patients WHERE gdoc_id = 'patient-doc-1'").fetchone()

            with patch.object(app_module, 'gdocs', fake_gdocs), \
                 patch.object(app_module, 'gcal', fake_gcal), \
                 patch.object(gdoc_module, '_docs_service', lambda creds: _FakeService(backend)):
                count1, err1 = app_module._pull_gdoc_notes(db, patient)
                # After the first pull the doc header should carry an id tag.
                self.assertIn('[note:id=', backend.text)
                count2, err2 = app_module._pull_gdoc_notes(db, patient)
                # Edit the session text in the doc and pull a third time.
                backend.text = backend.text.replace('Hebrew session notes', 'Edited session notes')
                count3, err3 = app_module._pull_gdoc_notes(db, patient)

            rows = db.execute(
                "SELECT session_number, content FROM notes WHERE patient_id = ?",
                (patient['id'],),
            ).fetchall()

        self.assertIsNone(err1)
        self.assertIsNone(err2)
        self.assertIsNone(err3)
        self.assertEqual(len(rows), 1, 'expected exactly one note row per meeting after repeated pulls')
        self.assertEqual(rows[0]['session_number'], 6)
        self.assertEqual(rows[0]['content'], 'Edited session notes')

    def test_patient_pull_untagged_without_stamping_still_dedupes(self):
        # Even if the doc is never stamped (e.g. stamping fails), the identity
        # dedupe on (patient, session_number) must prevent duplicate rows.
        backend = _DocBackend('פגישה 3- 01/03/26\nSome session notes\n')
        fake_gdocs = _FakeGdocs(backend)
        fake_gdocs.stamp_note_id_in_doc = lambda *a, **k: None  # no-op stamping
        fake_gcal = self._fake_gcal()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO patients (name, status, gdoc_id) VALUES (?, ?, ?)",
                ('No Stamp Patient', 'ongoing', 'patient-doc-2'),
            )
            db.commit()
            patient = db.execute("SELECT * FROM patients WHERE gdoc_id = 'patient-doc-2'").fetchone()

            with patch.object(app_module, 'gdocs', fake_gdocs), \
                 patch.object(app_module, 'gcal', fake_gcal):
                app_module._pull_gdoc_notes(db, patient)
                app_module._pull_gdoc_notes(db, patient)

            rows = db.execute(
                "SELECT id FROM notes WHERE patient_id = ?", (patient['id'],)
            ).fetchall()

        self.assertEqual(len(rows), 1)

    def test_group_pull_is_idempotent(self):
        backend = _DocBackend('SESSION #1 | 2026-05-01 [note:new]\nGroup process summary\n')
        fake_gdocs = _FakeGdocs(backend)
        fake_gcal = self._fake_gcal()

        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO groups (name, group_type, description, gdoc_id) VALUES (?, ?, ?, ?)",
                ('Dedupe Group', 'therapy', 'desc', 'group-doc-1'),
            )
            db.commit()
            group = db.execute("SELECT * FROM groups WHERE gdoc_id = 'group-doc-1'").fetchone()

            with patch.object(app_module, 'gdocs', fake_gdocs), \
                 patch.object(app_module, 'gcal', fake_gcal), \
                 patch.object(gdoc_module, '_docs_service', lambda creds: _FakeService(backend)):
                _, err1 = app_module._pull_group_gdoc_notes(db, group)
                self.assertIn('[note:id=', backend.text)
                _, err2 = app_module._pull_group_gdoc_notes(db, group)
                _, err3 = app_module._pull_group_gdoc_notes(db, group)

            sessions = db.execute(
                "SELECT id, session_summary FROM group_sessions WHERE group_id = ?",
                (group['id'],),
            ).fetchall()

        self.assertIsNone(err1)
        self.assertIsNone(err2)
        self.assertIsNone(err3)
        self.assertEqual(len(sessions), 1, 'expected exactly one group session row after repeated pulls')
        self.assertEqual(sessions[0]['session_summary'], 'Group process summary')


if __name__ == '__main__':
    unittest.main()
