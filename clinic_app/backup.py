import os
import json
import hashlib
import shutil
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from flask import g

from clinic_app import config as _config


def _app_config(key, default=None):
    try:
        from flask import current_app
        return current_app.config.get(key, default)
    except RuntimeError:
        from app import app as _flask_app
        return _flask_app.config.get(key, default)


def _resolve_backup_artifact_sources(upload_folder_override=None):
    if upload_folder_override:
        upload_folder = Path(upload_folder_override)
    else:
        upload_folder = Path(_app_config('UPLOAD_FOLDER', 'static/uploads'))
    patient_logs_folder = Path(_app_config('PATIENT_LOGS_FOLDER', 'patients_logs'))
    app_log_file = Path(_app_config('APP_LOG_FILE', 'app_log.txt'))
    return {
        'uploads': upload_folder,
        'patients_logs': patient_logs_folder,
        'app_log.txt': app_log_file,
    }


def _snapshot_artifact_tree(path, file_label=None):
    if not path.exists():
        return {'exists': False, 'files': []}

    if path.is_file():
        payload = path.read_bytes()
        return {
            'exists': True,
            'files': [{
                'path': file_label or path.name,
                'size': len(payload),
                'sha256': hashlib.sha256(payload).hexdigest(),
            }]
        }

    files = []
    for child in sorted(path.rglob('*')):
        if not child.is_file():
            continue
        rel_path = child.relative_to(path).as_posix()
        payload = child.read_bytes()
        files.append({
            'path': rel_path,
            'size': len(payload),
            'sha256': hashlib.sha256(payload).hexdigest(),
        })
    return {'exists': True, 'files': files}


def _artifact_backup_fingerprint(base_override=None):
    base_override = Path(base_override) if base_override else None
    fingerprint = {}
    for label, source_path in _resolve_backup_artifact_sources().items():
        target_path = (base_override / label) if base_override else source_path
        fingerprint[label] = _snapshot_artifact_tree(target_path, file_label=label)
    return fingerprint


def _write_backup_bundle(bundle_path, db_path, artifact_root=None):
    db_source = Path(db_path)
    artifact_root = Path(artifact_root) if artifact_root else None
    manifest = {
        'version': 2,
        'created_at': datetime.now().isoformat(),
        'database_name': db_source.name,
        'artifacts': sorted(_resolve_backup_artifact_sources().keys()),
    }

    with zipfile.ZipFile(bundle_path, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=True, sort_keys=True))
        bundle.write(db_source, arcname=f'database/{db_source.name}')

        for label, source_path in _resolve_backup_artifact_sources().items():
            if artifact_root:
                source_path = artifact_root / label
            if not source_path.exists():
                continue
            if source_path.is_file():
                bundle.write(source_path, arcname=f'artifacts/{label}')
                continue
            child_files = [child for child in sorted(source_path.rglob('*')) if child.is_file()]
            if not child_files:
                bundle.writestr(f'artifacts/{label}/', b'')
                continue
            for child in child_files:
                rel_path = child.relative_to(source_path).as_posix()
                bundle.write(child, arcname=f'artifacts/{label}/{rel_path}')


def _is_encrypted_zip_backup(payload):
    return zipfile.is_zipfile(BytesIO(payload))


def _restore_artifact_tree(source_root, destination_path):
    source_root = Path(source_root)
    destination_path = Path(destination_path)

    if destination_path.exists():
        if destination_path.is_dir():
            shutil.rmtree(destination_path)
        else:
            destination_path.unlink()

    if not source_root.exists():
        return

    if source_root.is_file():
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root, destination_path)
        return

    destination_path.mkdir(parents=True, exist_ok=True)
    for child in sorted(source_root.rglob('*')):
        rel_path = child.relative_to(source_root)
        target = destination_path / rel_path
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _backup_live_artifacts(safety_root):
    safety_root = Path(safety_root)
    safety_root.mkdir(parents=True, exist_ok=True)
    for label, source_path in _resolve_backup_artifact_sources().items():
        if not source_path.exists():
            continue
        target = safety_root / label
        if source_path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
        else:
            shutil.copytree(source_path, target, dirs_exist_ok=True)


def _get_or_create_backup_key():
    key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if key:
        return key.encode('utf-8')

    key_dir = Path(_config.KEY_DIR)
    key_dir.mkdir(parents=True, exist_ok=True)
    key_path = key_dir / '.backup.key'

    old_key_path = Path(_config.BACKUP_DIR) / '.backup.key'
    if not key_path.exists() and old_key_path.exists():
        key_data = old_key_path.read_bytes()
        key_path.write_bytes(key_data)
        try:
            old_key_path.unlink()
        except Exception:
            pass
        return key_data.strip()

    if key_path.exists():
        return key_path.read_bytes().strip()

    from cryptography.fernet import Fernet
    generated = Fernet.generate_key()
    key_path.write_bytes(generated)
    return generated


def _database_backup_fingerprint(db_file_path):
    conn = sqlite3.connect(str(db_file_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            row['name'] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]

        table_counts = {}
        table_counts = {table_name: 0 for table_name in tables}

        chunk_size = 200
        for i in range(0, len(tables), chunk_size):
            chunk = tables[i:i + chunk_size]
            query_parts = []
            for table_name in chunk:
                escaped_literal = table_name.replace("'", "''")
                escaped_identifier = table_name.replace('"', '""')
                query_parts.append(
                    f"SELECT '{escaped_literal}' AS t_name, COUNT(*) AS c FROM \"{escaped_identifier}\""
                )
            query = " UNION ALL ".join(query_parts)
            if query:
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


def perform_encrypted_backup(db_path):
    db_source = Path(db_path)
    if not db_source.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    src_check = sqlite3.connect(db_path)
    try:
        integrity = src_check.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f"Backup aborted, source DB integrity check failed: {integrity}")
    finally:
        src_check.close()

    backup_root = Path(_config.BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    raw_backup_path = backup_root / f'clinic_{timestamp}.bundle'
    encrypted_path = backup_root / f'clinic_{timestamp}.db.enc'
    artifact_snapshot_root = backup_root / f'.artifact_snapshot_{timestamp}'
    verify_dir = backup_root / f'.verify_{timestamp}'

    source_fingerprint = _database_backup_fingerprint(db_path)
    _backup_live_artifacts(artifact_snapshot_root)
    source_artifact_fingerprint = _artifact_backup_fingerprint(artifact_snapshot_root)

    _write_backup_bundle(raw_backup_path, db_path, artifact_snapshot_root)

    from cryptography.fernet import Fernet
    cipher = Fernet(_get_or_create_backup_key())
    raw_bytes = raw_backup_path.read_bytes()
    encrypted_bytes = cipher.encrypt(raw_bytes)
    encrypted_path.write_bytes(encrypted_bytes)

    try:
        probe = cipher.decrypt(encrypted_bytes)
        if not _is_encrypted_zip_backup(probe):
            raise RuntimeError('Encrypted backup verification failed: invalid backup bundle')

        verify_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(probe), 'r') as bundle:
            bundle.extractall(verify_dir)

        extracted_dbs = sorted(path for path in (verify_dir / 'database').iterdir() if path.is_file()) if (verify_dir / 'database').exists() else []
        if not extracted_dbs:
            raise RuntimeError('Encrypted backup verification failed: database missing from bundle')

        backup_fingerprint = _database_backup_fingerprint(extracted_dbs[0])
        if backup_fingerprint != source_fingerprint:
            raise RuntimeError('Encrypted backup verification failed: data fingerprint mismatch')

        backup_artifact_fingerprint = _artifact_backup_fingerprint(verify_dir / 'artifacts')
        if backup_artifact_fingerprint != source_artifact_fingerprint:
            raise RuntimeError('Encrypted backup verification failed: artifact fingerprint mismatch')
    except Exception as exc:
        encrypted_path.unlink(missing_ok=True)
        raw_backup_path.unlink(missing_ok=True)
        shutil.rmtree(artifact_snapshot_root, ignore_errors=True)
        shutil.rmtree(verify_dir, ignore_errors=True)
        raise RuntimeError(f'Encrypted backup verification failed: {exc}')

    raw_backup_path.unlink(missing_ok=True)
    shutil.rmtree(artifact_snapshot_root, ignore_errors=True)
    shutil.rmtree(verify_dir, ignore_errors=True)
    return str(encrypted_path)


def _export_json_backup(db_path):
    backup_root = Path(_config.BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_path = backup_root / f'clinic_data_export_{timestamp}.json'

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    data = {}
    for t in tables:
        rows = c.execute(f'SELECT * FROM "{t}"').fetchall()
        records = [dict(r) for r in rows]
        if records:
            clean = []
            for r in records:
                rec = {}
                for k, v in r.items():
                    if isinstance(v, datetime):
                        rec[k] = v.isoformat()
                    else:
                        rec[k] = v
                clean.append(rec)
            data[t] = {"records": clean}
    conn.close()

    output = {"exported_at": datetime.now().isoformat(), "data": data}
    export_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"JSON backup created: {export_path}")
    return str(export_path)


def _ensure_backup_key_consistency():
    key_dir = Path(_config.KEY_DIR)
    key_dir.mkdir(parents=True, exist_ok=True)
    env_key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    file_key_path = key_dir / '.backup.key'

    if env_key:
        file_key_path.write_text(env_key)
        key_info = {
            'note': 'Backup encryption key fingerprint (not the key itself). Verify against BACKUP_ENCRYPTION_KEY in .env',
            'key_fingerprint': hashlib.sha256(env_key.encode()).hexdigest()[:16],
            'generated_at': datetime.now().isoformat(),
            'instructions': 'Check .env for BACKUP_ENCRYPTION_KEY or ' + str(file_key_path)
        }
        (key_dir / 'KEY_RECOVERY.txt').write_text(json.dumps(key_info, indent=2))
        return

    if file_key_path.exists():
        file_key = file_key_path.read_bytes().strip()
        key_info = {
            'note': 'Backup encryption key fingerprint (not the key itself).',
            'key_fingerprint': hashlib.sha256(file_key).hexdigest()[:16],
            'generated_at': datetime.now().isoformat(),
            'instructions': 'The key is stored in ' + str(file_key_path)
        }
        (key_dir / 'KEY_RECOVERY.txt').write_text(json.dumps(key_info, indent=2))
        print("Warning: BACKUP_ENCRYPTION_KEY not set in environment. Using file key only.")


def perform_routine_encrypted_backup(db_path):
    backup_root = Path(_config.BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    marker = backup_root / '.last_backup_at'

    now = datetime.now()
    if marker.exists():
        try:
            last_run = datetime.fromisoformat(marker.read_text().strip())
            if now - last_run < timedelta(hours=_config.BACKUP_INTERVAL_HOURS):
                return None
        except ValueError:
            pass

    _ensure_backup_key_consistency()
    encrypted_path = perform_encrypted_backup(db_path)
    _export_json_backup(db_path)
    marker.write_text(now.isoformat())
    return encrypted_path


def list_encrypted_backups():
    if not os.path.exists(_config.BACKUP_DIR):
        return []
    all_files = os.listdir(_config.BACKUP_DIR)
    backup_files = [f for f in all_files if (f.startswith('clinic_') and f.endswith('.db.enc')) or (f.endswith('.json') and (f.startswith('clinic_data_backup') or f.startswith('clinic_data_export')))]
    backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(_config.BACKUP_DIR, f)), reverse=True)
    return [
        {
            'name': f,
            'path': os.path.join(_config.BACKUP_DIR, f),
            'size': os.path.getsize(os.path.join(_config.BACKUP_DIR, f)),
        }
        for f in backup_files
    ]


def perform_encrypted_restore(db_path, backup_filename=None):
    backup_root = Path(_config.BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)

    backups = sorted(backup_root.glob('clinic_*.db.enc'))
    if not backups:
        raise FileNotFoundError('No encrypted backups found.')

    if backup_filename:
        safe_name = Path(backup_filename).name
        target = backup_root / safe_name
        if target not in backups or not target.exists():
            raise FileNotFoundError('Selected backup file was not found.')
    else:
        target = backups[-1]

    from cryptography.fernet import Fernet
    cipher = Fernet(_get_or_create_backup_key())
    decrypted = cipher.decrypt(target.read_bytes())

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_restore = backup_root / f'.restore_tmp_{timestamp}'
    safety_copy = backup_root / f'clinic_pre_restore_{timestamp}'

    temp_restore.mkdir(parents=True, exist_ok=True)

    if _is_encrypted_zip_backup(decrypted):
        with zipfile.ZipFile(BytesIO(decrypted), 'r') as bundle:
            bundle.extractall(temp_restore)
        extracted_dbs = sorted(path for path in (temp_restore / 'database').iterdir() if path.is_file()) if (temp_restore / 'database').exists() else []
        if not extracted_dbs:
            raise RuntimeError('Backup restore failed: database missing from bundle.')
        restore_db = extracted_dbs[0]
    else:
        restore_db = temp_restore / Path(db_path).name
        restore_db.write_bytes(decrypted)
        if not decrypted.startswith(b'SQLite format 3'):
            raise RuntimeError('Backup decrypt succeeded but SQLite header is invalid.')

    temp_conn = sqlite3.connect(str(restore_db))
    try:
        integrity = temp_conn.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f'Restored backup integrity check failed: {integrity}')
    finally:
        temp_conn.close()

    live_db = Path(db_path)
    _backup_live_artifacts(safety_copy)
    if live_db.exists():
        shutil.copy2(live_db, safety_copy / live_db.name)

    existing = getattr(g, '_database', None)
    if existing is not None:
        existing.close()
        g._database = None

    shutil.copy2(restore_db, live_db)

    artifacts_root = temp_restore / 'artifacts'
    if artifacts_root.exists():
        for label, destination_path in _resolve_backup_artifact_sources().items():
            _restore_artifact_tree(artifacts_root / label, destination_path)

    shutil.rmtree(temp_restore, ignore_errors=True)

    verify_conn = sqlite3.connect(str(live_db))
    try:
        verify_integrity = verify_conn.execute('PRAGMA integrity_check').fetchone()[0]
        if verify_integrity != 'ok':
            raise RuntimeError(f'Post-restore database integrity check failed: {verify_integrity}')
    finally:
        verify_conn.close()

    return str(target), str(safety_copy)


def _perform_restore(backup_path):
    path = Path(backup_path)
    if not path.exists():
        raise FileNotFoundError(f'Backup file not found: {backup_path}')

    if path.suffix == '.enc':
        result = perform_encrypted_restore(str(_app_config('DATABASE', _config.DATABASE)), backup_filename=path.name)
        return {'tables_restored': 0, 'path': str(result[0])}

    if path.suffix == '.json':
        import json as _json
        data = _json.loads(path.read_text(encoding='utf-8'))
        raw = data.get('data') or data
        conn = sqlite3.connect(str(_app_config('DATABASE', _config.DATABASE)))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        total = 0
        for table, content in raw.items():
            if isinstance(content, dict) and 'records' in content:
                records = content['records']
            elif isinstance(content, list):
                records = content
            else:
                continue
            if not records:
                continue
            col_info = c.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = [r['name'] for r in col_info]
            has_id = 'id' in columns
            pk_cols = [r['name'] for r in col_info if r['pk'] > 0]
            pk_col = pk_cols[0] if pk_cols and has_id else None
            for record in records:
                existing = None
                if pk_col:
                    pk_val = record.get(pk_col)
                    if pk_val is not None:
                        existing = c.execute(f'SELECT id FROM "{table}" WHERE "{pk_col}" = ?', (pk_val,)).fetchone()
                if existing:
                    present_cols = [col for col in record if col in columns and col != pk_col]
                    if present_cols:
                        set_clause = ', '.join(f'"{col}" = ?' for col in present_cols)
                        vals = [record[col] for col in present_cols]
                        c.execute(f'UPDATE "{table}" SET {set_clause} WHERE id = ?', vals + [existing['id']])
                else:
                    insert_cols = [col for col in record if col in columns]
                    placeholders = ', '.join('?' for _ in insert_cols)
                    col_list = ', '.join(f'"{col}"' for col in insert_cols)
                    c.execute(f'INSERT OR IGNORE INTO "{table}" ({col_list}) VALUES ({placeholders})', [record[col] for col in insert_cols])
                total += 1
        conn.commit()
        conn.close()
        return {'tables_restored': total}

    if path.suffix in ('.db', '.bak'):
        live_db = Path(str(_app_config('DATABASE', _config.DATABASE)))
        live_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, live_db)
        return {'tables_restored': 0}
