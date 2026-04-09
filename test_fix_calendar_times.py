import unittest
import tempfile
import os
import sqlite3
from app import init_db, app
import fix_calendar_times

class FixCalendarTimesTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app.config['DATABASE'] = self.db_path

        # Set environment variable so get_db in fix_calendar_times uses this db
        os.environ['DATABASE'] = self.db_path

        with app.app_context():
            init_db()

        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row

    def tearDown(self):
        self.db.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        if 'DATABASE' in os.environ:
            del os.environ['DATABASE']

    def test_fix_appointment_times(self):
        # Insert a patient
        self.db.execute("INSERT INTO patients (name, status) VALUES ('Test Patient', 'ongoing')")
        patient_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert appointments with invalid or missing times
        self.db.execute('''
            INSERT INTO appointments (patient_id, appointment_date, appointment_time, status)
            VALUES (?, '2023-10-01', '00:00', 'scheduled')
        ''', (patient_id,))
        appt_00 = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.db.execute('''
            INSERT INTO appointments (patient_id, appointment_date, appointment_time, status)
            VALUES (?, '2023-10-02', '', 'scheduled')
        ''', (patient_id,))
        appt_empty = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert an appointment with a valid time to ensure it is untouched
        self.db.execute('''
            INSERT INTO appointments (patient_id, appointment_date, appointment_time, status)
            VALUES (?, '2023-10-04', '14:00', 'scheduled')
        ''', (patient_id,))
        appt_valid = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.db.commit()

        # Run fix
        fix_calendar_times.fix_appointment_times()

        # Verify
        all_slots = ['09:00', '09:30', '10:00', '10:30', '11:00', '11:30',
                     '14:00', '14:30', '15:00', '15:30', '16:00', '16:30', '17:00']

        appt_00_row = self.db.execute("SELECT appointment_time FROM appointments WHERE id = ?", (appt_00,)).fetchone()
        self.assertIn(appt_00_row['appointment_time'], all_slots)

        appt_empty_row = self.db.execute("SELECT appointment_time FROM appointments WHERE id = ?", (appt_empty,)).fetchone()
        self.assertIn(appt_empty_row['appointment_time'], all_slots)

        appt_valid_row = self.db.execute("SELECT appointment_time FROM appointments WHERE id = ?", (appt_valid,)).fetchone()
        self.assertEqual(appt_valid_row['appointment_time'], '14:00')

if __name__ == '__main__':
    unittest.main()
