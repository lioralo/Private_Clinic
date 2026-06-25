import unittest
from unittest.mock import patch, MagicMock
import sqlite3
import os
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import google_calendar

class TestGoogleCalendar(unittest.TestCase):

    @patch('google_calendar.load_credentials')
    @patch('google_calendar._refresh_and_save')
    @patch('google_calendar._build_service')
    def test_list_calendars(self, mock_build_service, mock_refresh_and_save, mock_load_credentials):
        db = MagicMock(spec=sqlite3.Connection)

        # 1. No credentials
        mock_load_credentials.return_value = None
        result = google_calendar.list_calendars(db)
        self.assertEqual(result, [])
        mock_load_credentials.assert_called_once_with(db)
        mock_refresh_and_save.assert_not_called()
        mock_build_service.assert_not_called()

        mock_load_credentials.reset_mock()
        mock_refresh_and_save.reset_mock()
        mock_build_service.reset_mock()

        # 2. Success case
        mock_creds = MagicMock()
        mock_load_credentials.return_value = mock_creds
        mock_refresh_and_save.return_value = mock_creds

        mock_service = MagicMock()
        mock_build_service.return_value = mock_service

        mock_list = MagicMock()
        mock_service.calendarList().list.return_value = mock_list
        mock_list.execute.return_value = {
            'items': [
                {'id': 'cal1', 'summary': 'Calendar 1'},
                {'id': 'cal2'} # No summary -> falls back to id
            ]
        }

        result = google_calendar.list_calendars(db)
        expected_result = [
            {'id': 'cal1', 'summary': 'Calendar 1'},
            {'id': 'cal2', 'summary': 'cal2'}
        ]

        self.assertEqual(result, expected_result)
        mock_load_credentials.assert_called_once_with(db)
        mock_refresh_and_save.assert_called_once_with(db, mock_creds)
        mock_build_service.assert_called_once_with(mock_creds)
        mock_service.calendarList().list().execute.assert_called_once()

        mock_load_credentials.reset_mock()
        mock_refresh_and_save.reset_mock()
        mock_build_service.reset_mock()

        # 3. Exception case
        mock_load_credentials.return_value = mock_creds
        mock_refresh_and_save.side_effect = Exception("Test exception")

        result = google_calendar.list_calendars(db)
        self.assertEqual(result, [])
        mock_load_credentials.assert_called_once_with(db)
        mock_refresh_and_save.assert_called_once_with(db, mock_creds)

if __name__ == '__main__':
    unittest.main()
