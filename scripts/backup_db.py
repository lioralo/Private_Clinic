#!/usr/bin/env python3
"""
Encrypted database backup and restore for Private Clinic.

Supports:
  - backup:  python backup_db.py
  - restore: python backup_db.py restore <file.db.enc> [target_path]
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

DB_FILE = 'clinic.db'
BACKUP_DIR = 'secure_backups'


def get_or_create_backup_key():
    env_key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if env_key:
        return env_key.encode('utf-8')

    key_dir = Path('.clinic_keys')
    key_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(key_dir, 0o700)
    except Exception:
        pass

    key_path = key_dir / '.backup.key'

    # Migrate key from old location inside backup dir if it exists
    old_key_path = Path(BACKUP_DIR) / '.backup.key'
    if not key_path.exists() and old_key_path.exists():
        key_data = old_key_path.read_bytes()
        key_path.write_bytes(key_data)
        try:
            os.chmod(key_path, 0o600)
        except Exception:
            pass
        try:
            old_key_path.unlink()
        except Exception:
            pass
        return key_data.strip()

    if key_path.exists():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass
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

        table_counts = {table_name: 0 for table_name in tables}

        # SQLite defaults to a max of 500 compound selects. Chunk to avoid OperationalError.
        chunk_size = 200
        for i in range(0, len(tables), chunk_size):
            chunk = tables[i:i + chunk_size]
            query = " UNION ALL ".join(
                [f"SELECT '{table_name}' AS t_name, COUNT(*) AS c FROM \"{table_name}\"" for table_name in chunk]
            )
            for row in conn.execute(query).fetchall():
                table_counts[row['t_name']] = int(row['c'] if row['c'] is not None else 0)

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


def rotate_old_backups(backup_root: Path, keep: int = 30) -> None:
    """Delete oldest encrypted backups, keeping the most recent *keep* files."""
    enc_files = sorted(backup_root.glob('clinic_*.db.enc'), key=lambda p: p.stat().st_mtime)
    to_delete = enc_files[:-keep] if len(enc_files) > keep else []
    for old_file in to_delete:
        old_file.unlink(missing_ok=True)
        print(f"Rotated old backup: {old_file.name}")


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
        rotate_old_backups(backup_root)
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


def main():
    args = sys.argv[1:]
    if args and args[0] == 'restore':
        if len(args) < 2:
            print("Usage: python backup_db.py restore <encrypted_backup.db.enc> [target_db_path]")
            sys.exit(1)
        enc_file = args[1]
        target_file = args[2] if len(args) >= 3 else None
        success = restore_database(enc_file, target_file)
        sys.exit(0 if success else 1)
    else:
        backup_database()

if __name__ == '__main__':
    main()
