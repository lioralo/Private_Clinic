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
        return True
    except Exception as exc:
        raw_path.unlink(missing_ok=True)
        encrypted_path.unlink(missing_ok=True)
        verify_path.unlink(missing_ok=True)
        print(f"Backup failed: {exc}")
        return False


def restore_database(encrypted_backup_path: str, target_db_path: str = None):
    """Decrypt an encrypted backup and restore it to the clinic database."""
    enc_path = Path(encrypted_backup_path)
    if not enc_path.exists():
        print(f"Error: Encrypted backup file '{encrypted_backup_path}' not found.")
        return False

    target = Path(target_db_path or DB_FILE)
    temp_restore = target.parent / f'.restore_tmp_{enc_path.stem}.db'

    try:
        cipher = Fernet(get_or_create_backup_key())
        encrypted_bytes = enc_path.read_bytes()
        decrypted_bytes = cipher.decrypt(encrypted_bytes)

        if not decrypted_bytes.startswith(b'SQLite format 3'):
            print("Error: Decrypted content is not a valid SQLite database.")
            return False

        temp_restore.write_bytes(decrypted_bytes)

        # Verify decrypted database is readable
        conn = sqlite3.connect(str(temp_restore))
        try:
            result = conn.execute('PRAGMA integrity_check').fetchone()[0]
            if result != 'ok':
                print(f"Error: Restored database failed integrity check: {result}")
                return False
            fingerprint = database_backup_fingerprint(temp_restore)
        finally:
            conn.close()

        # Take a safety snapshot of the current database before overwriting
        if target.exists():
            safety_path = target.parent / f'secure_backups/{target.stem}.pre_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.bak'
            safety_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(target), str(safety_path))
            print(f"Safety backup of current DB saved to: {safety_path}")

        temp_restore.replace(target)
        print(f"Restore successful: {target}")
        print(f"Restored tables: {list(fingerprint['table_counts'].keys())}")
        for t, c in fingerprint['table_counts'].items():
            print(f"  {t}: {c} rows")
        return True

    except Exception as exc:
        temp_restore.unlink(missing_ok=True)
        print(f"Restore failed: {exc}")
        return False


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == 'restore':
        if len(sys.argv) < 3:
            print("Usage: python backup_db.py restore <encrypted_backup.db.enc> [target_db_path]")
            sys.exit(1)
        enc_file = sys.argv[2]
        target_file = sys.argv[3] if len(sys.argv) >= 4 else None
        success = restore_database(enc_file, target_file)
        sys.exit(0 if success else 1)
    else:
        backup_database()
