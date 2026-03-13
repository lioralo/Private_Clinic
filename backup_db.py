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


def database_backup_fingerprint(db_file_path):
    conn = sqlite3.connect(str(db_file_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            row['name'] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]

        table_counts = {}
        for table_name in tables:
            count_row = conn.execute(f'SELECT COUNT(*) AS c FROM "{table_name}"').fetchone()
            table_counts[table_name] = int(count_row['c'] if count_row else 0)

        appointment_stats = conn.execute('''
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN COALESCE(is_recurring, 0) = 1 THEN 1 ELSE 0 END) AS recurring_total,
                SUM(CASE WHEN COALESCE(meeting_link, '') <> '' THEN 1 ELSE 0 END) AS with_meeting_link,
                SUM(CASE WHEN COALESCE(recurrence_days, '') <> '' THEN 1 ELSE 0 END) AS with_recurrence_days,
                SUM(CASE WHEN COALESCE(recurrence_interval, 0) > 0 THEN 1 ELSE 0 END) AS with_recurrence_interval,
                SUM(CASE WHEN COALESCE(recurrence_end_date, '') <> '' THEN 1 ELSE 0 END) AS with_recurrence_end_date,
                SUM(CASE WHEN COALESCE(recurrence_count, 0) > 0 THEN 1 ELSE 0 END) AS with_recurrence_count
            FROM appointments
        ''').fetchone()

        return {
            'table_counts': table_counts,
            'appointment_stats': {
                'total': int(appointment_stats['total'] or 0),
                'recurring_total': int(appointment_stats['recurring_total'] or 0),
                'with_meeting_link': int(appointment_stats['with_meeting_link'] or 0),
                'with_recurrence_days': int(appointment_stats['with_recurrence_days'] or 0),
                'with_recurrence_interval': int(appointment_stats['with_recurrence_interval'] or 0),
                'with_recurrence_end_date': int(appointment_stats['with_recurrence_end_date'] or 0),
                'with_recurrence_count': int(appointment_stats['with_recurrence_count'] or 0),
            }
        }
    finally:
        conn.close()


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
    verify_path = backup_root / f'.verify_{timestamp}.db'

    source_fingerprint = database_backup_fingerprint(db_path)

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

        verify_path.write_bytes(probe)
        backup_fingerprint = database_backup_fingerprint(verify_path)
        if backup_fingerprint != source_fingerprint:
            raise RuntimeError('verification failed: data fingerprint mismatch')

        raw_path.unlink(missing_ok=True)
        verify_path.unlink(missing_ok=True)
        print(f"Encrypted backup successful: {encrypted_path}")
    except Exception as exc:
        raw_path.unlink(missing_ok=True)
        encrypted_path.unlink(missing_ok=True)
        verify_path.unlink(missing_ok=True)
        print(f"Backup failed: {exc}")


if __name__ == '__main__':
    backup_database()
