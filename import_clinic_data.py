#!/usr/bin/env python3
"""
Safely merge clinic_data.json into clinic.db.

This importer is intentionally conservative:
- it inserts records that are missing from the database
- it only backfills existing rows when the current DB value is empty
- it never deletes rows or overwrites populated values
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path


DB_PATH = Path("clinic.db")
JSON_PATH = Path("clinic_data.json")
BACKUP_DIR = Path("secure_backups")


def is_empty_value(value):
    return value is None or value == ""


def get_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


@lru_cache(maxsize=None)
def get_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return [row[1] for row in rows]


@lru_cache(maxsize=None)
def get_primary_key_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    pk_rows = sorted((row for row in rows if row[5] > 0), key=lambda row: row[5])
    return [row[1] for row in pk_rows]


def build_where_clause(columns: Iterable[str]) -> str:
    return " AND ".join(f'"{column}" = ?' for column in columns)


def record_exists(conn: sqlite3.Connection, table: str, pk_columns: list[str], record: dict) -> sqlite3.Row | None:
    where_clause = build_where_clause(pk_columns)
    params = tuple(record[column] for column in pk_columns)
    conn.row_factory = sqlite3.Row
    return conn.execute(f'SELECT * FROM "{table}" WHERE {where_clause}', params).fetchone()


def insert_record(conn: sqlite3.Connection, table: str, record: dict):
    columns = list(record.keys())
    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(f'"{column}"' for column in columns)
    values = [record[column] for column in columns]
    conn.execute(
        f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})',
        values,
    )


def update_empty_fields(conn: sqlite3.Connection, table: str, pk_columns: list[str], current_row: sqlite3.Row, incoming_row: dict) -> int:
    updates = {}
    for column, value in incoming_row.items():
        if column in pk_columns or is_empty_value(value):
            continue
        if is_empty_value(current_row[column]):
            updates[column] = value

    if not updates:
        return 0

    assignments = ", ".join(f'"{column}" = ?' for column in updates)
    where_clause = build_where_clause(pk_columns)
    params = list(updates.values()) + [incoming_row[column] for column in pk_columns]
    conn.execute(
        f'UPDATE "{table}" SET {assignments} WHERE {where_clause}',
        params,
    )
    return len(updates)


def backup_database(db_path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"clinic_pre_json_merge_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def load_export(json_path: Path) -> dict:
    with json_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def merge_export(db_path: Path, json_path: Path):
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not json_path.exists():
        raise FileNotFoundError(f"Export not found: {json_path}")

    backup_path = backup_database(db_path)
    export_payload = load_export(json_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    available_tables = get_tables(conn)
    merge_summary = {}

    try:
        for table, table_payload in export_payload["data"].items():
            if table not in available_tables:
                merge_summary[table] = {"inserted": 0, "updated_fields": 0, "skipped": table_payload.get("row_count", 0)}
                continue

            table_columns = set(get_table_columns(conn, table))
            pk_columns = get_primary_key_columns(conn, table)
            inserted = 0
            updated_fields = 0
            skipped = 0

            for raw_record in table_payload["records"]:
                record = {key: value for key, value in raw_record.items() if key in table_columns}

                if not record:
                    skipped += 1
                    continue

                if not pk_columns or any(column not in record for column in pk_columns):
                    skipped += 1
                    continue

                current_row = record_exists(conn, table, pk_columns, record)
                if current_row is None:
                    insert_record(conn, table, record)
                    inserted += 1
                    continue

                updated_fields += update_empty_fields(conn, table, pk_columns, current_row, record)

            merge_summary[table] = {
                "inserted": inserted,
                "updated_fields": updated_fields,
                "skipped": skipped,
            }

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

    return backup_path, merge_summary


def main():
    backup_path, merge_summary = merge_export(DB_PATH, JSON_PATH)
    print(f"Created DB backup: {backup_path}")
    print("Merge summary:")
    total_inserted = 0
    total_updated_fields = 0
    for table in sorted(merge_summary):
        stats = merge_summary[table]
        total_inserted += stats["inserted"]
        total_updated_fields += stats["updated_fields"]
        print(
            f"  {table}: inserted={stats['inserted']}, "
            f"updated_fields={stats['updated_fields']}, skipped={stats['skipped']}"
        )
    print(f"Totals: inserted={total_inserted}, updated_fields={total_updated_fields}")


if __name__ == "__main__":
    main()
