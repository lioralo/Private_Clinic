"""
Fix calendar meeting times by assigning proper time slots instead of 00:00.
"""

import os
import random
import sqlite3
import sys


MORNING_SLOTS = ['09:00', '09:30', '10:00', '10:30', '11:00', '11:30']
AFTERNOON_SLOTS = ['14:00', '14:30', '15:00', '15:30', '16:00', '16:30', '17:00']
ALL_SLOTS = MORNING_SLOTS + AFTERNOON_SLOTS


def get_db():
    db = sqlite3.connect(os.environ.get('DATABASE', 'clinic.db'))
    db.row_factory = sqlite3.Row
    return db


def find_appointments_without_times(db):
    return db.execute('''
        SELECT id, appointment_date, appointment_time
        FROM appointments
        WHERE appointment_time = '00:00'
           OR appointment_time = ''
           OR appointment_time IS NULL
        ORDER BY appointment_date, appointment_time
    ''').fetchall()


def count_untimed_appointments(db):
    row = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE appointment_time = '00:00'
           OR appointment_time = ''
           OR appointment_time IS NULL
    ''').fetchone()
    return row['count']


def fix_appointment_times():
    db = get_db()
    appointments = find_appointments_without_times(db)
    print(f"Found {len(appointments)} appointments with missing or invalid times")

    updated = 0
    for appt in appointments:
        new_time = random.choice(ALL_SLOTS)
        try:
            db.execute(
                'UPDATE appointments SET appointment_time = ? WHERE id = ?',
                (new_time, appt['id'])
            )
            updated += 1
            print(f"  Updated appointment {appt['id']}: {appt['appointment_date']} -> {new_time}")
        except Exception as e:
            print(f"  Error updating appointment {appt['id']}: {e}")

    db.commit()
    print(f"\nUpdated {updated} appointments")
    remaining = count_untimed_appointments(db)
    print(f"Remaining appointments with invalid times: {remaining}")
    db.close()
    return updated > 0


def main():
    success = fix_appointment_times()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
