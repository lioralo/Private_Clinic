import unittest
import os
import sqlite3
import tempfile
import shutil
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import backup_db
from cryptography.fernet import Fernet

class TestBackupDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_clinic.db"
        self.backup_dir = Path(self.temp_dir.name) / "secure_backups"

        # Create a dummy sqlite db with some required tables so fingerprinting doesn't fail
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE appointments (id INTEGER PRIMARY KEY, is_recurring INTEGER, meeting_link TEXT, recurrence_days TEXT, recurrence_interval INTEGER, recurrence_end_date TEXT, recurrence_count INTEGER)")
        conn.execute("INSERT INTO appointments (is_recurring) VALUES (1)")
        conn.commit()
        conn.close()

        # Patch paths in backup_db module
        self.patcher_db = patch('backup_db.DB_FILE', str(self.db_path))
        self.patcher_backup = patch('backup_db.BACKUP_DIR', str(self.backup_dir))
        self.patcher_db.start()
        self.patcher_backup.start()

    def tearDown(self):
        self.patcher_db.stop()
        self.patcher_backup.stop()
        self.temp_dir.cleanup()

    @patch('shutil.copy2')
    @patch('cryptography.fernet.Fernet.encrypt')
    @patch('cryptography.fernet.Fernet.decrypt')
    def test_backup_database_success_with_mocks(self, mock_decrypt, mock_encrypt, mock_copy2):
        """Test backup flow specifically mocking the encryption logic."""
        mock_encrypt.return_value = b'encrypted_data'
        # Provide valid sqlite header for decrypt so verification passes
        # Add some padding to make the DB readable enough for fingerprint or mock the fingerprint

        with patch('backup_db.database_backup_fingerprint') as mock_fingerprint:
            mock_fingerprint.return_value = {'table_counts': {}, 'appointment_stats': {}}
            mock_decrypt.return_value = b'SQLite format 3\x00' + b'\x00' * 100

            # Initial call to backup_database
            backup_db.backup_database()

            # Verify that an encrypted backup was created and encrypt was called
            backups = list(self.backup_dir.glob("*.db.enc"))
            self.assertEqual(len(backups), 1)
            self.assertTrue(mock_encrypt.called)
            self.assertTrue(mock_decrypt.called)

    def test_restore_database_success(self):
        # Create a backup first
        backup_db.backup_database()
        backups = list(self.backup_dir.glob("*.db.enc"))
        self.assertEqual(len(backups), 1)
        backup_path = backups[0]

        # Now try restoring it to a new location
        target_db = Path(self.temp_dir.name) / "restored.db"
        # Since target doesn't exist yet, it won't trigger safety backup, so let's create a dummy target
        target_db.write_bytes(b'dummy_old_db_content')

        with patch('shutil.copy2') as mock_copy2:
            success = backup_db.restore_database(str(backup_path), str(target_db))

            # Verify success
            self.assertTrue(success)
            self.assertTrue(target_db.exists())

            # Verify the data was restored correctly
            conn = sqlite3.connect(str(target_db))
            count = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
            self.assertEqual(count, 1)
            conn.close()

            # Verify safety backup copy was called
            self.assertTrue(mock_copy2.called)

    def test_backup_missing_db(self):
        # Remove DB file to simulate missing DB
        self.db_path.unlink()

        with patch('builtins.print') as mock_print:
            backup_db.backup_database()
            mock_print.assert_called_with(f"Error: Database file '{str(self.db_path)}' not found.")

        # Verify no backup was created
        backups = list(self.backup_dir.glob("*.db.enc"))
        self.assertEqual(len(backups), 0)

    def test_restore_missing_backup(self):
        success = backup_db.restore_database("non_existent_backup.db.enc", str(self.db_path))
        self.assertFalse(success)

    def test_get_or_create_backup_key_env_var(self):
        test_key = Fernet.generate_key()
        with patch.dict(os.environ, {'BACKUP_ENCRYPTION_KEY': test_key.decode()}):
            key = backup_db.get_or_create_backup_key()
            self.assertEqual(key, test_key)

if __name__ == '__main__':
    unittest.main()
