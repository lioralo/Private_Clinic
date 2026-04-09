import unittest
from unittest.mock import patch, MagicMock

import google_docs

class TestGoogleDocsParser(unittest.TestCase):
    def test_parse_date(self):
        # Valid ISO date
        self.assertEqual(google_docs._parse_date('2026-04-01', None), '2026-04-01')

        # Valid slash format (DD/MM/YY)
        self.assertEqual(google_docs._parse_date(None, '05/08/25'), '2025-08-05')

        # Valid slash format (DD/MM/YYYY)
        self.assertEqual(google_docs._parse_date(None, '05/08/2025'), '2025-08-05')

        # Invalid slash formats
        self.assertIsNone(google_docs._parse_date(None, 'invalid/date'))
        self.assertIsNone(google_docs._parse_date(None, '05/35/2025'))

    def test_parse_doc_into_notes(self):
        # English, ISO date, pipe
        text1 = "SESSION #1 | 2026-04-01 [note:new]\nFree text content..."
        notes1 = google_docs.parse_doc_into_notes(text1)
        self.assertEqual(len(notes1), 1)
        self.assertEqual(notes1[0]['session_number'], 1)
        self.assertEqual(notes1[0]['note_date'], '2026-04-01')
        self.assertEqual(notes1[0]['content'], 'Free text content...')
        self.assertEqual(notes1[0]['note_tag'], 'new')

        # Hebrew, ISO date, pipe, existing id
        text2 = "פגישה #3 | 2026-04-01 [note:id=7]\nתוכן חופשי..."
        notes2 = google_docs.parse_doc_into_notes(text2)
        self.assertEqual(len(notes2), 1)
        self.assertEqual(notes2[0]['session_number'], 3)
        self.assertEqual(notes2[0]['note_date'], '2026-04-01')
        self.assertEqual(notes2[0]['content'], 'תוכן חופשי...')
        self.assertEqual(notes2[0]['note_tag'], 7)

        # Hebrew, dash style, DD/MM/YY, no tag
        text3 = "פגישה 1- 05/08/25\nתוכן\nעוד תוכן"
        notes3 = google_docs.parse_doc_into_notes(text3)
        self.assertEqual(len(notes3), 1)
        self.assertEqual(notes3[0]['session_number'], 1)
        self.assertEqual(notes3[0]['note_date'], '2025-08-05')
        self.assertEqual(notes3[0]['content'], 'תוכן\nעוד תוכן')
        self.assertEqual(notes3[0]['note_tag'], 'new')

        # Multiple sessions
        text4 = (
            "SESSION #1 | 2026-04-01 [note:id=1]\nFirst session\n"
            "פגישה 2- 15/04/2026 [note:new]\nSecond session"
        )
        notes4 = google_docs.parse_doc_into_notes(text4)
        self.assertEqual(len(notes4), 2)
        self.assertEqual(notes4[0]['session_number'], 1)
        self.assertEqual(notes4[0]['note_date'], '2026-04-01')
        self.assertEqual(notes4[0]['content'], 'First session')
        self.assertEqual(notes4[0]['note_tag'], 1)

        self.assertEqual(notes4[1]['session_number'], 2)
        self.assertEqual(notes4[1]['note_date'], '2026-04-15')
        self.assertEqual(notes4[1]['content'], 'Second session')
        self.assertEqual(notes4[1]['note_tag'], 'new')

class TestGoogleDocsAPI(unittest.TestCase):
    @patch('google_docs.build', create=True)
    def test_create_patient_doc(self, mock_build):
        mock_svc = MagicMock()
        mock_build.return_value = mock_svc

        # Mock create response
        mock_create = MagicMock()
        mock_create.execute.return_value = {'documentId': 'fake_doc_id'}
        mock_svc.documents().create.return_value = mock_create

        # Mock batchUpdate
        mock_batch_update = MagicMock()
        mock_svc.documents().batchUpdate.return_value = mock_batch_update

        creds = MagicMock()
        doc_id = google_docs.create_patient_doc(creds, 'John Doe')

        self.assertEqual(doc_id, 'fake_doc_id')
        mock_build.assert_called_with('docs', 'v1', credentials=creds, cache_discovery=False)
        mock_svc.documents().create.assert_called_once()
        create_args, create_kwargs = mock_svc.documents().create.call_args
        self.assertEqual(create_kwargs['body']['title'], 'Treatment Log — John Doe')

        mock_svc.documents().batchUpdate.assert_called_once()
        batch_args, batch_kwargs = mock_svc.documents().batchUpdate.call_args
        self.assertEqual(batch_kwargs['documentId'], 'fake_doc_id')
        self.assertTrue('insertText' in batch_kwargs['body']['requests'][0])

    @patch('google_docs.build', create=True)
    def test_read_doc_text(self, mock_build):
        mock_svc = MagicMock()
        mock_build.return_value = mock_svc

        mock_get = MagicMock()
        mock_get.execute.return_value = {
            'body': {
                'content': [
                    {'paragraph': {'elements': [{'textRun': {'content': 'Hello '}}]}},
                    {'paragraph': {'elements': [{'textRun': {'content': 'World!'}}]}}
                ]
            }
        }
        mock_svc.documents().get.return_value = mock_get

        creds = MagicMock()
        text = google_docs.read_doc_text(creds, 'fake_doc_id')

        self.assertEqual(text, 'Hello World!')
        mock_build.assert_called_with('docs', 'v1', credentials=creds, cache_discovery=False)
        mock_svc.documents().get.assert_called_once_with(documentId='fake_doc_id')

    @patch('google_docs.build', create=True)
    def test_stamp_note_id_in_doc(self, mock_build):
        mock_svc = MagicMock()
        mock_build.return_value = mock_svc

        mock_batch_update = MagicMock()
        mock_svc.documents().batchUpdate.return_value = mock_batch_update

        creds = MagicMock()
        google_docs.stamp_note_id_in_doc(creds, 'fake_doc_id', 42)

        mock_build.assert_called_with('docs', 'v1', credentials=creds, cache_discovery=False)
        mock_svc.documents().batchUpdate.assert_called_once()
        batch_args, batch_kwargs = mock_svc.documents().batchUpdate.call_args
        self.assertEqual(batch_kwargs['documentId'], 'fake_doc_id')
        reqs = batch_kwargs['body']['requests']
        self.assertEqual(len(reqs), 1)
        self.assertTrue('replaceAllText' in reqs[0])
        self.assertEqual(reqs[0]['replaceAllText']['replaceText'], '[note:id=42]')
        self.assertEqual(reqs[0]['replaceAllText']['containsText']['text'], '[note:new]')

    @patch('google_docs.build', create=True)
    def test_register_drive_watch(self, mock_build):
        mock_svc = MagicMock()
        mock_build.return_value = mock_svc

        mock_watch = MagicMock()
        # Fake expiration 1000 seconds from epoch
        mock_watch.execute.return_value = {'expiration': '1000000'}
        mock_svc.files().watch.return_value = mock_watch

        creds = MagicMock()
        channel_id, expiry_iso = google_docs.register_drive_watch(creds, 'fake_doc_id', 'https://webhook.url')

        self.assertTrue(isinstance(channel_id, str))
        self.assertTrue(len(channel_id) > 0)
        self.assertEqual(expiry_iso, '1970-01-01T00:16:40+00:00')

        mock_build.assert_called_with('drive', 'v3', credentials=creds, cache_discovery=False)
        mock_svc.files().watch.assert_called_once()
        watch_args, watch_kwargs = mock_svc.files().watch.call_args
        self.assertEqual(watch_kwargs['fileId'], 'fake_doc_id')
        self.assertEqual(watch_kwargs['body']['address'], 'https://webhook.url')
        self.assertEqual(watch_kwargs['body']['type'], 'web_hook')

if __name__ == '__main__':
    unittest.main()
