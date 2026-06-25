import os
import json
import sqlite3
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from import_clinic_data import (
    is_empty_value,
    build_where_clause,
    get_tables,
    get_table_columns,
    get_primary_key_columns,
    record_exists,
    insert_record,
    update_empty_fields,
    backup_database,
    load_export,
    merge_export
)

class TestImportClinicData(unittest.TestCase):
    def test_is_empty_value(self):
        self.assertTrue(is_empty_value(None))
        self.assertTrue(is_empty_value(""))
        self.assertFalse(is_empty_value(" "))
        self.assertFalse(is_empty_value(0))
        self.assertFalse(is_empty_value("value"))

    def test_build_where_clause(self):
        self.assertEqual(build_where_clause(["id"]), '"id" = ?')
        self.assertEqual(build_where_clause(["id", "name"]), '"id" = ? AND "name" = ?')
        self.assertEqual(build_where_clause([]), "")

    def setUp(self):
        # Create an in-memory database for testing
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT,
                value TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE test_table_no_pk (
                name TEXT,
                value TEXT
            )
        """)
        self.conn.execute("INSERT INTO test_table (id, name, value) VALUES (1, 'Test', 'Value')")
        self.conn.execute("INSERT INTO test_table (id, name, value) VALUES (2, 'Test2', '')")
        self.conn.execute("INSERT INTO test_table (id, name, value) VALUES (3, 'Test3', NULL)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_get_tables(self):
        tables = get_tables(self.conn)
        self.assertEqual(tables, {"test_table", "test_table_no_pk"})

    def test_get_table_columns(self):
        columns = get_table_columns(self.conn, "test_table")
        self.assertEqual(columns, ["id", "name", "value"])

    def test_get_primary_key_columns(self):
        pk_cols = get_primary_key_columns(self.conn, "test_table")
        self.assertEqual(pk_cols, ["id"])

        pk_cols_none = get_primary_key_columns(self.conn, "test_table_no_pk")
        self.assertEqual(pk_cols_none, [])

    def test_record_exists(self):
        record = {"id": 1, "name": "Test", "value": "Value"}
        row = record_exists(self.conn, "test_table", ["id"], record)
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], 1)

        record_not_exist = {"id": 99, "name": "Test", "value": "Value"}
        row_none = record_exists(self.conn, "test_table", ["id"], record_not_exist)
        self.assertIsNone(row_none)

    def test_insert_record(self):
        record = {"id": 4, "name": "Test4", "value": "Value4"}
        insert_record(self.conn, "test_table", record)
        self.conn.commit()

        row = self.conn.execute("SELECT * FROM test_table WHERE id = 4").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Test4")

    def test_update_empty_fields(self):
        # Update empty string
        current_row = self.conn.execute("SELECT * FROM test_table WHERE id = 2").fetchone()
        incoming_record = {"id": 2, "name": "Test2-updated", "value": "NewValue"}

        updated_count = update_empty_fields(self.conn, "test_table", ["id"], current_row, incoming_record)
        self.assertEqual(updated_count, 1) # Only "value" should be updated
        self.conn.commit()

        row = self.conn.execute("SELECT * FROM test_table WHERE id = 2").fetchone()
        self.assertEqual(row["name"], "Test2") # Name should not be updated
        self.assertEqual(row["value"], "NewValue") # Value should be updated

        # Update NULL
        current_row = self.conn.execute("SELECT * FROM test_table WHERE id = 3").fetchone()
        incoming_record = {"id": 3, "name": "Test3", "value": "NewValue2"}

        updated_count = update_empty_fields(self.conn, "test_table", ["id"], current_row, incoming_record)
        self.assertEqual(updated_count, 1)
        self.conn.commit()

        row = self.conn.execute("SELECT * FROM test_table WHERE id = 3").fetchone()
        self.assertEqual(row["value"], "NewValue2")

        # Update non-empty (should not update)
        current_row = self.conn.execute("SELECT * FROM test_table WHERE id = 1").fetchone()
        incoming_record = {"id": 1, "name": "Test-updated", "value": "NewValue-updated"}

        updated_count = update_empty_fields(self.conn, "test_table", ["id"], current_row, incoming_record)
        self.assertEqual(updated_count, 0)

class TestImportClinicDataIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_clinic.db"
        self.json_path = Path(self.temp_dir.name) / "test_clinic_data.json"

        # Setup initial DB
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE patients (
                id INTEGER PRIMARY KEY,
                name TEXT,
                phone TEXT
            )
        """)
        conn.execute("INSERT INTO patients (id, name, phone) VALUES (1, 'Alice', '')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("import_clinic_data.BACKUP_DIR")
    def test_backup_database(self, mock_backup_dir):
        mock_backup_dir.mkdir.return_value = None
        mock_backup_dir.__truediv__.return_value = Path(self.temp_dir.name) / "backup.db"

        backup_path = backup_database(self.db_path)
        self.assertTrue(backup_path.exists())

    def test_load_export(self):
        data = {"test": "data"}
        with open(self.json_path, "w") as f:
            json.dump(data, f)

        loaded = load_export(self.json_path)
        self.assertEqual(loaded, data)

    @patch("import_clinic_data.backup_database")
    def test_merge_export(self, mock_backup_database):
        mock_backup_database.return_value = Path("dummy_backup.db")

        export_data = {
            "data": {
                "patients": {
                    "records": [
                        {"id": 1, "name": "Alice-updated", "phone": "123456"}, # Should update phone
                        {"id": 2, "name": "Bob", "phone": "654321"} # Should insert
                    ]
                },
                "nonexistent_table": {
                    "records": [
                        {"id": 1, "data": "test"}
                    ]
                }
            }
        }

        with open(self.json_path, "w") as f:
            json.dump(export_data, f)

        backup_path, summary = merge_export(self.db_path, self.json_path)

        self.assertEqual(summary["patients"]["inserted"], 1)
        self.assertEqual(summary["patients"]["updated_fields"], 1)
        self.assertEqual(summary["nonexistent_table"]["inserted"], 0)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Check update
        alice = conn.execute("SELECT * FROM patients WHERE id = 1").fetchone()
        self.assertEqual(alice["name"], "Alice") # Should not overwrite
        self.assertEqual(alice["phone"], "123456") # Should update empty

        # Check insert
        bob = conn.execute("SELECT * FROM patients WHERE id = 2").fetchone()
        self.assertEqual(bob["name"], "Bob")
        self.assertEqual(bob["phone"], "654321")

        conn.close()

if __name__ == "__main__":
    unittest.main()
