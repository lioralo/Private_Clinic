import os
import unittest
import tempfile
import sqlite3
import json
import app as app_module
from datetime import datetime, timedelta
from flask import g
from app import app, init_db, get_db

class ClinicTestCase(unittest.TestCase):

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app.config['DATABASE'] = self.db_path
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
        self.client = app.test_client()

        # Initialize the database
        with app.app_context():
            init_db()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, username, password):
        return self.client.post('/login', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def logout(self):
        return self.client.get('/logout', follow_redirects=True)

    def next_allowed_booking_slot(self, preferred_times=None):
        allowed_by_day = {
            0: ['14:00'],
            1: ['09:00', '12:30'],
            4: ['10:00', '19:00'],
        }
        day = datetime.now().date() + timedelta(days=1)
        for _ in range(21):
            day_code = (day.weekday() + 1) % 7
            times = allowed_by_day.get(day_code, [])
            if times:
                if preferred_times:
                    for preferred in preferred_times:
                        if preferred in times:
                            return day.isoformat(), preferred
                return day.isoformat(), times[0]
            day += timedelta(days=1)
        raise AssertionError('Could not find allowed booking slot in the next 3 weeks')

    def next_allowed_day_with_two_slots(self):
        allowed_by_day = {
            1: ['09:00', '12:30'],
            4: ['10:00', '11:00'],
        }
        day = datetime.now().date() + timedelta(days=1)
        for _ in range(21):
            day_code = (day.weekday() + 1) % 7
            times = allowed_by_day.get(day_code, [])
            if len(times) >= 2:
                return day.isoformat(), times[0], times[1]
            day += timedelta(days=1)
        raise AssertionError('Could not find allowed day with two booking slots in the next 3 weeks')

    def add_vacancy(self, date_iso, time_text, duration_minutes=60):
        with app.app_context():
            db = get_db()
            db.execute('''
                INSERT INTO slots_override (slot_date, slot_time, status, duration_minutes)
                VALUES (?, ?, 'available', ?)
            ''', (date_iso, time_text, duration_minutes))
            db.commit()

    def test_login_logout(self):
        rv = self.login('admin', 'admin')
        assert b'Log out' in rv.data or b'Logout' in rv.data
        rv = self.logout()
        assert b'Login' in rv.data

    def test_add_patient(self):
        self.login('admin', 'admin')
        rv = self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing',
            email='test@example.com',
            phone='555-1234'
        ), follow_redirects=True)
        assert b'Test Patient' in rv.data
        assert b'ongoing' in rv.data

    def test_add_note(self):
        self.login('admin', 'admin')
        # Add patient first
        self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing'
        ), follow_redirects=True)

        # Add note
        rv = self.client.post('/patient/1/add_note', data=dict(
            content='This is a test note'
        ), follow_redirects=True)
        assert b'This is a test note' in rv.data

    def test_add_receipt(self):
        self.login('admin', 'admin')
        # Add patient first
        self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing'
        ), follow_redirects=True)

        # Add receipt
        rv = self.client.post('/patient/1/add_receipt', data=dict(
            amount='50.00',
            description='Test Receipt'
        ), follow_redirects=True)
        assert b'50.0' in rv.data
        assert b'Test Receipt' in rv.data

    def test_patient_access(self):
        self.login('admin', 'admin')
        # Add patient
        self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing'
        ), follow_redirects=True)

        # Create user for patient
        self.client.post('/patient/1/access', data=dict(
            username='patient',
            password='password'
        ), follow_redirects=True)

        self.logout()

        # Login as patient
        rv = self.login('patient', 'password')
        assert b'Account Balance' in rv.data or b'Financial Summary' in rv.data or b'Upcoming Appointments' in rv.data  # Should be on patient home

        # Try to access admin page
        rv = self.client.get('/add_patient', follow_redirects=True)
        assert b'Access denied' in rv.data or b'Unauthorized' in rv.data or rv.status_code == 403 or b'Welcome back' in rv.data or b'Upcoming Appointments' in rv.data  # Redirected to patient home

    def test_add_appointment(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing'
        ), follow_redirects=True)

        rv = self.client.post('/patient/1/add_appointment', data=dict(
            date='2024-01-01',
            time='10:00',
            cost='100.00'
        ), follow_redirects=True)
        assert b'Single appointment added.' in rv.data
        with app.app_context():
            db = get_db()
            appt = db.execute('SELECT appointment_date, appointment_time, cost FROM appointments WHERE patient_id = 1').fetchone()
            assert appt is not None
            assert appt['appointment_date'] == '2024-01-01'

    def test_seed_example_patients(self):
        self.login('admin', 'admin')
        rv = self.client.post('/admin/seed_data', data={}, follow_redirects=True)
        assert b'Error seeding data' not in rv.data
        with app.app_context():
            db = get_db()
            names = [row['name'] for row in db.execute(
                "SELECT name FROM patients WHERE name IN (?, ?, ?, ?)",
                ('Maya Cohen', 'Daniel Levy', 'Noa Shapiro', 'Eran Mizrahi')
            ).fetchall()]
        assert 'Maya Cohen' in names
        assert 'Daniel Levy' in names
        assert 'Noa Shapiro' in names
        assert 'Eran Mizrahi' in names

    def test_patient_detail_sections_render(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Detail Patient',
            status='ongoing',
            email='detail@example.com',
            phone='555-2222'
        ), follow_redirects=True)

        rv = self.client.get('/patient/1', follow_redirects=True)
        assert b'id="appointments-tab"' not in rv.data
        assert b'id="notes-tab"' in rv.data
        assert b'id="billing-tab"' in rv.data
        assert b'id="messages-tab"' in rv.data

    def test_import_treatment_log_json_list(self):
        import json
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Import Patient', status='ongoing'), follow_redirects=True)

        payload = [
            {'meeting_number': 2, 'date': '2025-01-20', 'content': 'Second note'},
            {'meeting_number': 1, 'date': '2025-01-10', 'content': 'First note'}
        ]

        import io
        rv = self.client.post(
            '/patient/1/import',
            data={'file': (io.BytesIO(json.dumps(payload).encode('utf-8')), 'history.json')},
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert b'History imported' in rv.data

        with app.app_context():
            db = get_db()
            notes = db.execute('SELECT session_number, note_date, content FROM notes WHERE patient_id = 1 ORDER BY note_date ASC, CAST(session_number AS INTEGER) ASC').fetchall()
            assert len(notes) == 2
            assert notes[0]['session_number'] == '1'
            assert notes[0]['note_date'] == '2025-01-10'
            assert notes[1]['session_number'] == '2'
            assert notes[1]['note_date'] == '2025-01-20'

    def test_edit_treatment_log_updates_timestamp(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Edit Note Patient', status='ongoing'), follow_redirects=True)
        self.client.post('/patient/1/add_note', data=dict(content='Original content', session_number='1', note_date='2025-01-01'), follow_redirects=True)

        rv = self.client.post('/note/1/edit', data=dict(content='Updated content', session_number='1', note_date='2025-01-02'), follow_redirects=True)
        assert b'Updated content' in rv.data

        with app.app_context():
            db = get_db()
            note = db.execute('SELECT content, note_date, updated_at FROM notes WHERE id = 1').fetchone()
            assert note['content'] == 'Updated content'
            assert note['note_date'] == '2025-01-02'
            assert note['updated_at'] is not None

    def test_treatment_log_defaults_prefilled(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Prefill Patient', status='ongoing'), follow_redirects=True)
        self.client.post('/patient/1/add_note', data=dict(content='First', session_number='1', note_date='2026-03-01'), follow_redirects=True)
        self.client.post('/patient/1/add_note', data=dict(content='Second', session_number='2', note_date='2026-03-08'), follow_redirects=True)

        rv = self.client.get('/patient/1?tab=notes', follow_redirects=True)
        today_iso = datetime.now().date().isoformat().encode('utf-8')
        assert b'name="session_number" class="form-control form-control-sm border-0 shadow-sm" value="3"' in rv.data
        assert today_iso in rv.data

    def test_behavior_questionnaire_fields_persist(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Behavior Patient', status='ongoing'), follow_redirects=True)
        self.client.post('/patient/1/add_note', data=dict(
            content='Behavior-focused note',
            session_number='3',
            note_date='2026-03-01',
            patient_appearance='Neat appearance',
            behavior_flags=['Calm', 'Engaged'],
            mood_summary='Stable mood',
            behavior_notes='Collaborative and focused'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            note = db.execute('''
                SELECT patient_appearance, behavior_checklist, mood_summary, behavior_notes
                FROM notes WHERE patient_id = 1 ORDER BY id DESC LIMIT 1
            ''').fetchone()
            assert note['patient_appearance'] == 'Neat appearance'
            assert note['behavior_checklist'] == 'Calm,Engaged'
            assert note['mood_summary'] == 'Stable mood'
            assert note['behavior_notes'] == 'Collaborative and focused'

    def test_import_static_treatment_log_example(self):
        import io
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Template Import Patient', status='ongoing'), follow_redirects=True)

        with open('static/treatment_log_example.json', 'r', encoding='utf-8') as f:
            payload = json.load(f)

        rv = self.client.post(
            '/patient/1/import',
            data={'file': (io.BytesIO(json.dumps(payload).encode('utf-8')), 'treatment_log_example.json')},
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert b'History imported' in rv.data

        with app.app_context():
            db = get_db()
            rows = db.execute('''
                SELECT session_number, note_date, behavior_checklist, mood_summary
                FROM notes WHERE patient_id = 1
                ORDER BY note_date ASC, CAST(session_number AS INTEGER) ASC
            ''').fetchall()
            assert len(rows) == 2
            assert rows[0]['session_number'] == '1'
            assert rows[0]['note_date'] == '2026-02-10'
            assert rows[1]['session_number'] == '2'
            assert rows[1]['note_date'] == '2026-02-17'

    def test_calendar_snapshot_api_admin(self):
        self.login('admin', 'admin')
        rv = self.client.get('/api/calendar/snapshot')
        assert rv.status_code == 200
        payload = rv.get_json()
        assert 'events' in payload
        assert 'available_slots' in payload
        assert 'weekend_specials' in payload

    def test_patient_self_booking_and_cancel(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Self Booking Patient',
            status='waiting'
        ), follow_redirects=True)
        self.client.post('/patient/1/access', data=dict(
            username='selfbook',
            password='password123'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            db.execute('UPDATE patients SET can_self_schedule = 1 WHERE id = 1')
            db.commit()

        self.logout()
        self.login('selfbook', 'password123')

        booking_date, booking_time = self.next_allowed_booking_slot(preferred_times=['10:00', '09:00', '14:00'])
        self.add_vacancy(booking_date, booking_time, 60)

        rv = self.client.post('/api/calendar/book', data=dict(
            date=booking_date,
            time=booking_time,
            duration_minutes='60',
            meeting_type='in-person'
        ))
        assert rv.status_code == 200
        assert rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            appt = db.execute('SELECT id FROM appointments WHERE patient_id = 1 ORDER BY id DESC LIMIT 1').fetchone()
            assert appt is not None
            appt_id = appt['id']

        rv = self.client.post(f'/api/calendar/appointment/{appt_id}/delete')
        assert rv.status_code == 200
        assert rv.get_json().get('status') == 'success'

    def test_calendar_booking_sets_ongoing_as_recurring(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Recurring Ongoing Patient',
            status='ongoing'
        ), follow_redirects=True)

        booking_date, booking_time = self.next_allowed_booking_slot(preferred_times=['10:00', '09:00', '14:00'])
        self.add_vacancy(booking_date, booking_time, 60)

        end_time = (datetime.strptime(booking_time, '%H:%M') + timedelta(hours=1)).strftime('%H:%M')
        rv = self.client.post('/api/calendar/book', data=dict(
            patient_id='1',
            date=booking_date,
            time=booking_time,
            end_time=end_time,
            meeting_type='in-person'
        ))
        assert rv.status_code == 200
        assert rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            row = db.execute('''
                SELECT is_recurring, recurrence_interval, recurrence_days
                FROM appointments
                WHERE patient_id = 1
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert row is not None
            assert int(row['is_recurring'] or 0) == 1
            assert int(row['recurrence_interval'] or 0) == 1

            booked_day = datetime.strptime(booking_date, '%Y-%m-%d').date()
            expected_day_code = str((booked_day.weekday() + 1) % 7)
            assert row['recurrence_days'] == expected_day_code

    def test_calendar_booking_sets_candidate_as_one_time(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='One Time Candidate',
            status='candidate'
        ), follow_redirects=True)

        booking_date, booking_time = self.next_allowed_booking_slot(preferred_times=['10:00', '09:00', '14:00'])
        self.add_vacancy(booking_date, booking_time, 60)

        end_time = (datetime.strptime(booking_time, '%H:%M') + timedelta(hours=1)).strftime('%H:%M')
        rv = self.client.post('/api/calendar/book', data=dict(
            patient_id='1',
            date=booking_date,
            time=booking_time,
            end_time=end_time,
            meeting_type='in-person'
        ))
        assert rv.status_code == 200
        assert rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            row = db.execute('''
                SELECT is_recurring, recurrence_interval, recurrence_days
                FROM appointments
                WHERE patient_id = 1
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert row is not None
            assert int(row['is_recurring'] or 0) == 0
            assert row['recurrence_interval'] is None
            assert row['recurrence_days'] is None

    def test_calendar_follow_up_alert_for_candidate_decision_needed(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Decision Candidate',
            status='candidate'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            past_date = (datetime.now().date() - timedelta(days=7)).isoformat()
            db.execute('''
                INSERT INTO appointments (patient_id, appointment_date, appointment_time, duration_minutes, status, is_recurring)
                VALUES (1, ?, '10:00', 60, 'scheduled', 0)
            ''', (past_date,))
            db.commit()

        rv = self.client.get('/api/calendar/snapshot')
        assert rv.status_code == 200
        payload = rv.get_json()
        alerts = payload.get('follow_up_alerts', [])
        assert any(a.get('patient_id') == 1 for a in alerts)
        alert = next(a for a in alerts if a.get('patient_id') == 1)
        assert 'Further decision is needed' in alert.get('message', '')

    def test_initial_intake_keeps_single_scheduled_meeting(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Intake Patient',
            status='candidate',
            patient_type='initial-intake',
            intake_assessment='Initial assessment text',
            intake_questionnaire='Initial questionnaire text'
        ), follow_redirects=True)

        booking_date, first_time, second_time = self.next_allowed_day_with_two_slots()
        self.add_vacancy(booking_date, first_time, 60)
        self.add_vacancy(booking_date, second_time, 60)

        def add_hour(time_text):
            dt = datetime.strptime(time_text, '%H:%M') + timedelta(hours=1)
            return dt.strftime('%H:%M')

        rv1 = self.client.post('/api/calendar/book', data=dict(
            patient_id='1',
            date=booking_date,
            time=first_time,
            end_time=add_hour(first_time),
            meeting_type='in-person'
        ))
        assert rv1.status_code == 200
        assert rv1.get_json().get('status') == 'success'

        rv2 = self.client.post('/api/calendar/book', data=dict(
            patient_id='1',
            date=booking_date,
            time=second_time,
            end_time=add_hour(second_time),
            meeting_type='in-person'
        ))
        assert rv2.status_code == 200
        assert rv2.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            rows = db.execute('''
                SELECT appointment_time, is_recurring
                FROM appointments
                WHERE patient_id = 1 AND status = 'scheduled'
                ORDER BY id ASC
            ''').fetchall()
            assert len(rows) == 1
            assert rows[0]['appointment_time'] == second_time
            assert int(rows[0]['is_recurring'] or 0) == 0

    def test_encrypted_backup_preserves_meeting_fields(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Backup Meeting Patient',
            status='ongoing'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            db.execute('''
                INSERT INTO appointments (
                    patient_id, appointment_date, appointment_time, duration_minutes,
                    is_recurring, recurrence_interval, recurrence_days, recurrence_end_date, recurrence_count,
                    meeting_type, meeting_link, meeting_platform, meeting_title, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                1,
                '2026-04-05',
                '10:30',
                60,
                1,
                1,
                '0,2',
                '2026-08-01',
                20,
                'zoom',
                'https://zoom.us/j/123',
                'zoom',
                'Weekly therapy',
                'scheduled'
            ))
            db.commit()

        with tempfile.TemporaryDirectory() as tmp_backup_dir:
            original_backup_dir = app_module.BACKUP_DIR
            app_module.BACKUP_DIR = tmp_backup_dir
            try:
                with app.app_context():
                    encrypted_path = app_module.perform_encrypted_backup(app.config['DATABASE'])
                    restored_from, _ = app_module.perform_encrypted_restore(app.config['DATABASE'], os.path.basename(encrypted_path))
                    assert restored_from.endswith('.db.enc')

                    db = get_db()
                    row = db.execute('''
                        SELECT
                            is_recurring, recurrence_interval, recurrence_days,
                            recurrence_end_date, recurrence_count,
                            meeting_type, meeting_link, meeting_platform, meeting_title
                        FROM appointments
                        WHERE patient_id = 1
                        ORDER BY id DESC
                        LIMIT 1
                    ''').fetchone()
                    assert row is not None
                    assert int(row['is_recurring'] or 0) == 1
                    assert int(row['recurrence_interval'] or 0) == 1
                    assert row['recurrence_days'] == '0,2'
                    assert row['recurrence_end_date'] == '2026-08-01'
                    assert int(row['recurrence_count'] or 0) == 20
                    assert row['meeting_type'] == 'zoom'
                    assert row['meeting_link'] == 'https://zoom.us/j/123'
                    assert row['meeting_platform'] == 'zoom'
                    assert row['meeting_title'] == 'Weekly therapy'
            finally:
                app_module.BACKUP_DIR = original_backup_dir

if __name__ == '__main__':
    unittest.main()
