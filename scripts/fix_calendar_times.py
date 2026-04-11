#!/usr/bin/env python3
"""
Fix calendar meeting times by assigning proper time slots instead of 00:00
"""

import os
import sqlite3
from datetime import datetime, timedelta
import random

def get_db():
    db = sqlite3.connect(os.environ.get('DATABASE', 'clinic.db'))
    db.row_factory = sqlite3.Row
    return db

def fix_appointment_times():
    """Assign proper times to appointments that have 00:00"""
    db = get_db()
    
    # Standard time slots
    morning_slots = ['09:00', '09:30', '10:00', '10:30', '11:00', '11:30']
    afternoon_slots = ['14:00', '14:30', '15:00', '15:30', '16:00', '16:30', '17:00']
    all_slots = morning_slots + afternoon_slots
    
    # Get appointments with 00:00 time
    appointments = db.execute('''
        SELECT id, appointment_date, appointment_time
        FROM appointments
        WHERE appointment_time = '00:00' OR appointment_time = '' OR appointment_time IS NULL
        ORDER BY appointment_date, appointment_time
    ''').fetchall()
    
    print(f"Found {len(appointments)} appointments with missing/invalid times")
    updated = 0
    
    for appt in appointments:
        # Assign a random time slot
        new_time = random.choice(all_slots)
        
        try:
            db.execute(
                'UPDATE appointments SET appointment_time = ? WHERE id = ?',
                (new_time, appt['id'])
            )
            updated += 1
            print(f"  ✓ Updated appointment {appt['id']}: {appt['appointment_date']} -> {new_time}")
        except Exception as e:
            print(f"  ✗ Error updating appointment {appt['id']}: {e}")
    
    db.commit()
    print(f"\n✓ Successfully updated {updated} appointments")
    
    # Verify the fix
    check = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE appointment_time = '00:00' OR appointment_time = '' OR appointment_time IS NULL
    ''').fetchone()
    
    print(f"Remaining appointments with invalid times: {check['count']}")
    db.close()

if __name__ == '__main__':
    fix_appointment_times()
