import json
import time
from app import app, get_db

def run_benchmark():
    with app.app_context():
        db = get_db()
        db.execute('INSERT INTO patients (name, status) VALUES ("Perf Test2", "ongoing")')
        patient_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Pre-populate some appointments
        for i in range(10000):
            db.execute('''INSERT INTO appointments
                (patient_id, appointment_date, appointment_time)
                VALUES (?, ?, ?)''',
                (patient_id, f'2022-01-{i%30+1:02d}', f'{10 + (i//30)%10:02d}:00'))
        db.commit()

        # Generate large dataset mixing existing and new appointments
        appointments = []
        for i in range(5000):
            if i % 2 == 0:
                # new appointment
                date = f'2023-10-{i%30+1:02d}'
            else:
                # existing appointment
                date = f'2022-01-{i%30+1:02d}'
            appointments.append({
                'id': i,
                'appointment_date': date,
                'appointment_time': f'{10 + (i//30)%10:02d}:00',
                'cost': 100,
                'status': 'completed',
                'duration_minutes': 50
            })

        data = {'appointments': appointments}

        start_time = time.time()

        # --- Simulating the original code logic ---
        appt_id_map = {}
        sorted_appts = sorted(data.get('appointments', []), key=lambda x: (x.get('appointment_date', ''), x.get('appointment_time', '')))
        for appt in sorted_appts:
            existing = db.execute('SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ? AND appointment_time = ?',
                (patient_id, appt.get('appointment_date'), appt.get('appointment_time'))).fetchone()
            if not existing:
                cursor = db.execute('''INSERT INTO appointments
                    (patient_id, appointment_date, appointment_time, cost, duration_minutes, is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link, status, recurrence_end_date, recurrence_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (patient_id, appt.get('appointment_date'), appt.get('appointment_time'), appt.get('cost'), appt.get('duration_minutes'),
                     appt.get('is_recurring'), appt.get('recurrence_interval'), appt.get('recurrence_days'), appt.get('meeting_type'),
                     appt.get('meeting_link'), appt.get('status'), appt.get('recurrence_end_date'), appt.get('recurrence_count')))
                appt_id_map[appt.get('id')] = cursor.lastrowid
            else:
                appt_id_map[appt.get('id')] = existing['id']

        db.commit()
        end_time = time.time()

        print(f"Original Time taken: {end_time - start_time:.4f} seconds")

def run_optimized_benchmark():
    with app.app_context():
        db = get_db()
        db.execute('INSERT INTO patients (name, status) VALUES ("Perf Test Opt2", "ongoing")')
        patient_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Pre-populate some appointments
        for i in range(10000):
            db.execute('''INSERT INTO appointments
                (patient_id, appointment_date, appointment_time)
                VALUES (?, ?, ?)''',
                (patient_id, f'2022-01-{i%30+1:02d}', f'{10 + (i//30)%10:02d}:00'))
        db.commit()

        # Generate large dataset mixing existing and new appointments
        appointments = []
        for i in range(5000):
            if i % 2 == 0:
                # new appointment
                date = f'2023-10-{i%30+1:02d}'
            else:
                # existing appointment
                date = f'2022-01-{i%30+1:02d}'
            appointments.append({
                'id': i,
                'appointment_date': date,
                'appointment_time': f'{10 + (i//30)%10:02d}:00',
                'cost': 100,
                'status': 'completed',
                'duration_minutes': 50
            })

        data = {'appointments': appointments}

        start_time = time.time()

        # --- Simulating optimized code logic ---
        appt_id_map = {}
        sorted_appts = sorted(data.get('appointments', []), key=lambda x: (x.get('appointment_date', ''), x.get('appointment_time', '')))

        # Pre-fetch existing appointments for this patient
        existing_appts_query = db.execute(
            'SELECT id, appointment_date, appointment_time FROM appointments WHERE patient_id = ?',
            (patient_id,)
        ).fetchall()

        # Create a dictionary for O(1) lookups: {(date, time): id}
        existing_appts = {
            (row['appointment_date'], row['appointment_time']): row['id']
            for row in existing_appts_query
        }

        for appt in sorted_appts:
            appt_date = appt.get('appointment_date')
            appt_time = appt.get('appointment_time')

            existing_id = existing_appts.get((appt_date, appt_time))

            if not existing_id:
                cursor = db.execute('''INSERT INTO appointments
                    (patient_id, appointment_date, appointment_time, cost, duration_minutes, is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link, status, recurrence_end_date, recurrence_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (patient_id, appt_date, appt_time, appt.get('cost'), appt.get('duration_minutes'),
                     appt.get('is_recurring'), appt.get('recurrence_interval'), appt.get('recurrence_days'), appt.get('meeting_type'),
                     appt.get('meeting_link'), appt.get('status'), appt.get('recurrence_end_date'), appt.get('recurrence_count')))
                appt_id_map[appt.get('id')] = cursor.lastrowid
                existing_appts[(appt_date, appt_time)] = cursor.lastrowid
            else:
                appt_id_map[appt.get('id')] = existing_id

        db.commit()
        end_time = time.time()

        print(f"Optimized Time taken: {end_time - start_time:.4f} seconds")

if __name__ == '__main__':
    run_benchmark()
    run_optimized_benchmark()
