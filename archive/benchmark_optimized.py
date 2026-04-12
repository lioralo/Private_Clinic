import time
from app import app, get_db, build_week_calendar_snapshot
from datetime import datetime, timedelta
import json
import sqlite3
from app import combine_dt, parse_date_safe, recurring_occurrences_for_week

class MockUser:
    def __init__(self):
        self.role = 'admin'
        self.patient_id = None

def build_week_calendar_snapshot_optimized(db, week_start, user):
    week_end = week_start + timedelta(days=6)
    today = datetime.now().date()

    patients = {
        row['id']: row for row in db.execute('SELECT id, name, status, can_self_schedule FROM patients').fetchall()
    }

    appointment_rows = db.execute('''
        SELECT a.*, p.name AS patient_name, p.status AS patient_status, p.patient_type AS patient_type
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE (a.is_recurring = 0 AND a.appointment_date BETWEEN ? AND ?)
           OR (a.is_recurring = 1 AND a.appointment_date <= ?)
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    ''', (week_start.isoformat(), week_end.isoformat(), week_end.isoformat())).fetchall()

    blocks = db.execute('''
        SELECT * FROM blocked_slots
        WHERE blocked_date BETWEEN ? AND ?
        ORDER BY blocked_date ASC, blocked_time ASC
    ''', (week_start.isoformat(), week_end.isoformat())).fetchall()

    group_sessions = db.execute('''
        SELECT gs.*, g.name AS group_name
        FROM group_sessions gs
        JOIN groups g ON g.id = gs.group_id
        WHERE gs.session_date BETWEEN ? AND ?
          AND COALESCE(g.is_active, 1) = 1
          AND COALESCE(gs.status, 'scheduled') = 'scheduled'
        ORDER BY gs.session_date ASC, gs.session_time ASC
    ''', (week_start.isoformat(), week_end.isoformat())).fetchall()

    events = []
    occupied = []
    emitted_appointment_keys = set()
    weekend_specials = {'friday': [], 'saturday': []}
    follow_up_alerts = []

    # Candidate with a past one-time session and no future booking needs a decision.
    follow_up_rows = db.execute('''
        SELECT p.id AS patient_id, p.name, p.status, MAX(a.appointment_date) AS last_date
        FROM patients p
        JOIN appointments a ON a.patient_id = p.id
        WHERE p.status = 'candidate'
          AND a.is_recurring = 0
          AND COALESCE(a.status, 'scheduled') = 'scheduled'
          AND a.appointment_date < ?
          AND NOT EXISTS (
              SELECT 1 FROM appointments a2
              WHERE a2.patient_id = p.id
                AND a2.appointment_date >= ?
                AND COALESCE(a2.status, 'scheduled') = 'scheduled'
          )
        GROUP BY p.id, p.name, p.status
    ''', (today.isoformat(), today.isoformat())).fetchall()

    for row in follow_up_rows:
        follow_up_alerts.append({
            'patient_id': row['patient_id'],
            'patient_name': row['name'],
            'status': row['status'],
            'last_meeting_date': row['last_date'],
            'message': 'Initial one-time meeting has passed with no next booking. Further decision is needed.'
        })

    for appt in appointment_rows:
        is_recurring = int(appt['is_recurring'] or 0) == 1
        occ_dates = recurring_occurrences_for_week(appt, week_start, week_end) if is_recurring else [parse_date_safe(appt['appointment_date'])]
        occ_dates = [d for d in occ_dates if d is not None]

        for occ_date in occ_dates:
            start_dt = combine_dt(occ_date, appt['appointment_time'])
            duration = int(appt['duration_minutes'] or 60)
            end_dt = start_dt + timedelta(minutes=duration)

            # Patients should not see other patients' bookings, only their own.
            if user.role == 'patient' and appt['patient_id'] != user.patient_id:
                occupied.append((start_dt, end_dt))
                continue

            # Skip blocked slots for recurring appts
            is_blocked = False
            if is_recurring:
                for b in blocks:
                    b_date = parse_date_safe(b['blocked_date'])
                    b_dt = combine_dt(b_date, b['blocked_time']) if b_date else None
                    if b_dt and b_dt == start_dt:
                        is_blocked = True
                        break
            if is_blocked:
                continue

            event_key = f"{appt['id']}_{start_dt.isoformat()}"
            if event_key in emitted_appointment_keys:
                continue
            emitted_appointment_keys.add(event_key)

            events.append({
                'id': appt['id'],
                'patient_id': appt['patient_id'],
                'patient_name': appt['patient_name'],
                'patient_status': appt['patient_status'],
                'patient_type': appt['patient_type'],
                'start_dt': start_dt,
                'end_dt': end_dt,
                'is_recurring': is_recurring,
                'meeting_type': appt['meeting_type'] or 'in-person'
            })
            occupied.append((start_dt, end_dt))

            if start_dt.weekday() in (4, 5):
                day_key = 'friday' if start_dt.weekday() == 4 else 'saturday'
                weekend_specials[day_key].append(start_dt.strftime('%H:%M'))

    for gs in group_sessions:
        s_date = parse_date_safe(gs['session_date'])
        if s_date:
            start_dt = combine_dt(s_date, gs['session_time'])
            duration = int(gs['duration_minutes'] or 60)
            end_dt = start_dt + timedelta(minutes=duration)
            events.append({
                'id': f"gs_{gs['id']}",
                'group_id': gs['group_id'],
                'group_name': gs['group_name'],
                'start_dt': start_dt,
                'end_dt': end_dt,
                'is_group': True
            })
            occupied.append((start_dt, end_dt))

    return {
        'events': events,
        'occupied': occupied,
        'weekend_specials': weekend_specials,
        'follow_up_alerts': follow_up_alerts
    }

with app.app_context():
    db = get_db()
    week_start = datetime.now().date()
    user = MockUser()

    # warm up cache
    build_week_calendar_snapshot_optimized(db, week_start, user)

    start_time = time.time()
    snapshot = build_week_calendar_snapshot_optimized(db, week_start, user)
    end_time = time.time()

    print(f"Optimized Time taken: {end_time - start_time} seconds")

    # ensure functionality is same
    start_time2 = time.time()
    snapshot_orig = build_week_calendar_snapshot(db, week_start, user)
    end_time2 = time.time()

    print(f"Original Time taken: {end_time2 - start_time2} seconds")

    assert snapshot['follow_up_alerts'] == snapshot_orig['follow_up_alerts'], "Alerts do not match"
    print("Alerts matched successfully!")
