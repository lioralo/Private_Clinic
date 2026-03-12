import os
import sqlite3
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

DB_FILE = 'clinic.db'
BACKUP_DIR = 'secure_backups'


def get_or_create_backup_key():
    env_key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if env_key:
        return env_key.encode('utf-8')

    backup_root = Path(BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    key_path = backup_root / '.backup.key'
    if key_path.exists():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    return key


def backup_database():
    db_path = Path(DB_FILE)
    if not db_path.exists():
        print(f"Error: Database file '{DB_FILE}' not found.")
        return

    src_check = sqlite3.connect(str(db_path))
    try:
        integrity = src_check.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            print(f"Backup aborted: source DB integrity check failed ({integrity}).")
            return
    finally:
        src_check.close()

    backup_root = Path(BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    raw_path = backup_root / f'clinic_{timestamp}.db'
    encrypted_path = backup_root / f'clinic_{timestamp}.db.enc'

    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(raw_path))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()

        cipher = Fernet(get_or_create_backup_key())
        raw_bytes = raw_path.read_bytes()
        encrypted_bytes = cipher.encrypt(raw_bytes)
        encrypted_path.write_bytes(encrypted_bytes)

        probe = cipher.decrypt(encrypted_bytes)
        if not probe.startswith(b'SQLite format 3'):
            raise RuntimeError('verification failed: invalid SQLite header')

        raw_path.unlink(missing_ok=True)
        print(f"Encrypted backup successful: {encrypted_path}")
    except Exception as exc:
        raw_path.unlink(missing_ok=True)
        encrypted_path.unlink(missing_ok=True)
        print(f"Backup failed: {exc}")


if __name__ == '__main__':
    backup_database()
