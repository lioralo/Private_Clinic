import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import uuid
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import google_docs


def _fake_doc_content(text, start=1):
    """Build a Google Docs ``body.content`` list from plain text.

    One paragraph per line, with sequential ``startIndex`` values beginning at
    ``start`` (index 0 is reserved by the real API), so the character offsets in
    the reconstructed text map to ``start + offset``.
    """
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


class TestGoogleDocs(unittest.TestCase):

    def test_parse_date(self):
        # ISO
        self.assertEqual(google_docs._parse_date('2024-05-15', None), '2024-05-15')
        # DD/MM/YY
        self.assertEqual(google_docs._parse_date(None, '15/05/25'), '2025-05-15')
        # DD/MM/YYYY
        self.assertEqual(google_docs._parse_date(None, '15/05/2025'), '2025-05-15')
        # Invalid format
        self.assertIsNone(google_docs._parse_date(None, '15/05'))
        # Invalid date
        self.assertIsNone(google_docs._parse_date(None, '32/05/25'))

    def test_parse_doc_into_notes(self):
        text = (
            "SESSION #1 | 2026-04-01 [note:new]\n"
            "English text\n"
            "פגישה #2 | 2026-04-02 [note:id=10]\n"
            "Hebrew pipe text\n"
            "פגישה 3- 03/04/26\n"
            "Hebrew dash text\n"
        )
        notes = google_docs.parse_doc_into_notes(text)

        self.assertEqual(len(notes), 3)

        # English, ISO, new
        self.assertEqual(notes[0]['session_number'], 1)
        self.assertEqual(notes[0]['note_date'], '2026-04-01')
        self.assertEqual(notes[0]['content'], 'English text')
        self.assertEqual(notes[0]['note_tag'], 'new')

        # Hebrew, ISO, existing id
        self.assertEqual(notes[1]['session_number'], 2)
        self.assertEqual(notes[1]['note_date'], '2026-04-02')
        self.assertEqual(notes[1]['content'], 'Hebrew pipe text')
        self.assertEqual(notes[1]['note_tag'], 10)

        # Hebrew, Dash, no tag (defaults to new)
        self.assertEqual(notes[2]['session_number'], 3)
        self.assertEqual(notes[2]['note_date'], '2026-04-03')
        self.assertEqual(notes[2]['content'], 'Hebrew dash text')
        self.assertEqual(notes[2]['note_tag'], 'new')

    @patch('google_docs._docs_service')
    def test_create_patient_doc(self, mock_docs_service):
        # Setup mock
        mock_svc = MagicMock()
        mock_docs_service.return_value = mock_svc

        mock_create = MagicMock()
        mock_create.execute.return_value = {'documentId': 'test_doc_id'}
        mock_svc.documents().create.return_value = mock_create

        mock_batchUpdate = MagicMock()
        mock_svc.documents().batchUpdate.return_value = mock_batchUpdate

        # Call function
        doc_id = google_docs.create_patient_doc('dummy_creds', 'John Doe')

        # Assertions
        self.assertEqual(doc_id, 'test_doc_id')
        mock_docs_service.assert_called_once_with('dummy_creds')
        mock_svc.documents().create.assert_called_once()
        mock_svc.documents().batchUpdate.assert_called_once()

        create_kwargs = mock_svc.documents().create.call_args[1]
        self.assertIn('Treatment Log — John Doe', create_kwargs['body']['title'])

        update_kwargs = mock_svc.documents().batchUpdate.call_args[1]
        self.assertEqual(update_kwargs['documentId'], 'test_doc_id')

    @patch('google_docs._docs_service')
    def test_read_doc_text(self, mock_docs_service):
        mock_svc = MagicMock()
        mock_docs_service.return_value = mock_svc

        mock_get = MagicMock()
        mock_get.execute.return_value = {
            'body': {
                'content': [
                    {'paragraph': {'elements': [{'textRun': {'content': 'Hello '}}]}},
                    {'paragraph': {'elements': [{'textRun': {'content': 'World\n'}}]}}
                ]
            }
        }
        mock_svc.documents().get.return_value = mock_get

        text = google_docs.read_doc_text('dummy_creds', 'test_doc_id')

        self.assertEqual(text, 'Hello World\n')
        mock_svc.documents().get.assert_called_once_with(documentId='test_doc_id')

    def _mock_docs_service_for(self, mock_docs_service, doc_text):
        """Wire a mocked docs service whose get() returns a document body built
        from ``doc_text`` (one paragraph per line, real-style startIndex)."""
        mock_svc = MagicMock()
        mock_docs_service.return_value = mock_svc
        mock_svc.documents().get().execute.return_value = {
            'body': {'content': _fake_doc_content(doc_text)}
        }
        mock_svc.documents().batchUpdate().execute.return_value = {}
        # Reset call history created while wiring return_values above.
        mock_svc.documents().get.reset_mock()
        mock_svc.documents().batchUpdate.reset_mock()
        return mock_svc

    @patch('google_docs._docs_service')
    def test_stamp_note_id_in_doc_fallback_first_marker(self, mock_docs_service):
        # No session_header → legacy behaviour: stamp the first [note:new].
        text = "SESSION #1 | 2026-04-01 [note:new]\nBody\n"
        mock_svc = self._mock_docs_service_for(mock_docs_service, text)

        google_docs.stamp_note_id_in_doc('creds', 'doc', 42)

        mock_svc.documents().batchUpdate.assert_called_once()
        requests = mock_svc.documents().batchUpdate.call_args[1]['body']['requests']
        expected_index = 1 + text.index('[note:new]')
        self.assertEqual(requests[0]['deleteContentRange']['range']['startIndex'], expected_index)
        self.assertEqual(
            requests[0]['deleteContentRange']['range']['endIndex'],
            expected_index + len('[note:new]'),
        )
        self.assertEqual(requests[1]['insertText']['text'], '[note:id=42]')
        self.assertEqual(requests[1]['insertText']['location']['index'], expected_index)

    @patch('google_docs._docs_service')
    def test_stamp_targets_correct_session_when_multiple_markers(self, mock_docs_service):
        # Two [note:new] markers; only the one on the requested header is stamped.
        text = (
            "SESSION #1 | 2026-04-01 [note:new]\n"
            "First body\n"
            "SESSION #2 | 2026-04-02 [note:new]\n"
            "Second body\n"
        )
        mock_svc = self._mock_docs_service_for(mock_docs_service, text)

        google_docs.stamp_note_id_in_doc(
            'creds', 'doc', 77, session_header='SESSION #2 | 2026-04-02 [note:new]'
        )

        requests = mock_svc.documents().batchUpdate.call_args[1]['body']['requests']
        second_marker = text.index('[note:new]', text.index('[note:new]') + 1)
        expected_index = 1 + second_marker
        self.assertEqual(requests[0]['deleteContentRange']['range']['startIndex'], expected_index)
        self.assertEqual(requests[1]['insertText']['text'], '[note:id=77]')

    @patch('google_docs._docs_service')
    def test_stamp_appends_id_for_untagged_header(self, mock_docs_service):
        # Real-world Hebrew dash header with no [note:new] marker → append tag.
        text = "SESSION #1 | 2026-04-01 [note:new]\nBody\nפגישה 6- 23/02/26\nHebrew body\n"
        mock_svc = self._mock_docs_service_for(mock_docs_service, text)

        google_docs.stamp_note_id_in_doc(
            'creds', 'doc', 55, session_header='פגישה 6- 23/02/26'
        )

        requests = mock_svc.documents().batchUpdate.call_args[1]['body']['requests']
        self.assertEqual(len(requests), 1)  # append only, no delete
        self.assertEqual(requests[0]['insertText']['text'], ' [note:id=55]')
        header_start = text.index('פגישה 6- 23/02/26')
        line_end = text.index('\n', header_start)
        self.assertEqual(requests[0]['insertText']['location']['index'], 1 + line_end)

    @patch('google_docs._docs_service')
    def test_stamp_is_noop_when_header_already_stamped(self, mock_docs_service):
        text = "SESSION #1 | 2026-04-01 [note:id=5]\nBody\n"
        mock_svc = self._mock_docs_service_for(mock_docs_service, text)

        google_docs.stamp_note_id_in_doc(
            'creds', 'doc', 9, session_header='SESSION #1 | 2026-04-01 [note:id=5]'
        )

        mock_svc.documents().batchUpdate.assert_not_called()

    @patch('google_docs._drive_service')
    def test_register_drive_watch(self, mock_drive_service):
        mock_svc = MagicMock()
        mock_drive_service.return_value = mock_svc

        # We need to simulate expiration in ms
        # 1 day = 86400 seconds = 86400000 ms
        future_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 86400000

        mock_watch = MagicMock()
        mock_watch.execute.return_value = {
            'id': 'test_channel_id',
            'expiration': str(future_timestamp_ms)
        }
        mock_svc.files().watch.return_value = mock_watch

        channel_id, expiry_iso = google_docs.register_drive_watch('dummy_creds', 'test_doc_id', 'https://webhook.test')

        # Returns a new uuid, not necessarily the mocked channel_id from execute response
        # because the function creates the uuid itself
        self.assertIsInstance(uuid.UUID(channel_id), uuid.UUID)
        self.assertIsInstance(expiry_iso, str)

        mock_svc.files().watch.assert_called_once()
        kwargs = mock_svc.files().watch.call_args[1]
        self.assertEqual(kwargs['fileId'], 'test_doc_id')
        self.assertEqual(kwargs['body']['type'], 'web_hook')
        self.assertEqual(kwargs['body']['address'], 'https://webhook.test')
        self.assertEqual(kwargs['body']['id'], channel_id)

if __name__ == '__main__':
    unittest.main()
