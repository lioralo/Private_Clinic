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

    def test_patient_detail_messages_tab_marks_unread_messages_read(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Unread Message Patient',
            status='ongoing'
        ), follow_redirects=True)
        self.client.post('/patient/1/access', data=dict(
            username='message_patient',
            password='password'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            patient_user = db.execute(
                'SELECT id FROM users WHERE patient_id = ? AND role = ?',
                (1, 'patient')
            ).fetchone()
            admin_user = db.execute(
                'SELECT id FROM users WHERE username = ?',
                ('admin',)
            ).fetchone()
            db.execute(
                'INSERT INTO messages (sender_id, recipient_id, content, is_read) VALUES (?, ?, ?, 0)',
                (patient_user['id'], admin_user['id'], 'Unread test message')
            )
            db.commit()

            unread_before = db.execute(
                'SELECT COUNT(*) AS c FROM messages WHERE recipient_id = ? AND sender_id = ? AND COALESCE(is_read, 0) = 0',
                (admin_user['id'], patient_user['id'])
            ).fetchone()['c']

        assert unread_before == 1

        rv = self.client.get('/patient/1?tab=messages', follow_redirects=True)
        assert b'Unread test message' in rv.data
        assert b'id="messagesUnreadBadge"' not in rv.data

        with app.app_context():
            db = get_db()
            unread_after = db.execute(
                'SELECT COUNT(*) AS c FROM messages WHERE recipient_id = ? AND sender_id = ? AND COALESCE(is_read, 0) = 0',
                (admin_user['id'], patient_user['id'])
            ).fetchone()['c']

        assert unread_after == 0

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

    def test_admin_calendar_booking_without_vacancy_allowed(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Direct Calendar Booking',
            status='ongoing'
        ), follow_redirects=True)

        booking_date = (datetime.now().date() + timedelta(days=1)).isoformat()
        rv = self.client.post('/api/calendar/book', data=dict(
            patient_id='1',
            date=booking_date,
            time='11:00',
            end_time='12:00',
            meeting_type='in-person'
        ))
        assert rv.status_code == 200
        assert rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            row = db.execute('''
                SELECT is_recurring, recurrence_end_date
                FROM appointments
                WHERE patient_id = 1
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert row is not None
            assert int(row['is_recurring'] or 0) == 1
            assert row['recurrence_end_date'] is not None

    def test_patient_page_quick_book_without_vacancy(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Sidebar Quick Book',
            status='ongoing'
        ), follow_redirects=True)

        booking_date = (datetime.now().date() + timedelta(days=2)).isoformat()
        rv = self.client.post('/patient/1/quick_book', data=dict(
            date=booking_date,
            time='13:00',
            end_time='14:00',
            meeting_type='in-person',
            meeting_title='Quick booked'
        ), follow_redirects=True)
        assert rv.status_code == 200

        with app.app_context():
            db = get_db()
            row = db.execute('''
                SELECT appointment_date, appointment_time, meeting_title, is_recurring
                FROM appointments
                WHERE patient_id = 1
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert row is not None
            assert row['appointment_date'] == booking_date
            assert row['appointment_time'] == '13:00'
            assert row['meeting_title'] == 'Quick booked'
            assert int(row['is_recurring'] or 0) == 1

    def test_patient_page_quick_book_one_time_override(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Sidebar One Time',
            status='ongoing'
        ), follow_redirects=True)

        booking_date = (datetime.now().date() + timedelta(days=3)).isoformat()
        rv = self.client.post('/patient/1/quick_book', data=dict(
            date=booking_date,
            time='10:00',
            end_time='11:00',
            meeting_type='in-person',
            recurrence_mode='one-time',
            meeting_title='One-time booking'
        ), follow_redirects=True)
        assert rv.status_code == 200

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

    def test_quick_book_recurring_rejected_for_initial_intake(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Intake Quick Book',
            status='candidate',
            patient_type='initial-intake'
        ), follow_redirects=True)

        booking_date = (datetime.now().date() + timedelta(days=4)).isoformat()
        rv = self.client.post('/patient/1/quick_book', data=dict(
            date=booking_date,
            time='12:00',
            end_time='13:00',
            meeting_type='in-person',
            recurrence_mode='recurring'
        ), follow_redirects=True)
        assert rv.status_code == 200
        assert b'Initial-intake patients can only be booked as one-time meetings.' in rv.data

        with app.app_context():
            db = get_db()
            count = db.execute('SELECT COUNT(*) AS c FROM appointments WHERE patient_id = 1').fetchone()['c']
            assert count == 0

    def test_public_self_booking_requires_phone_or_email(self):
        self.login('admin', 'admin')
        booking_date, booking_time = self.next_allowed_booking_slot(preferred_times=['09:00', '10:00', '12:30', '14:00'])
        self.add_vacancy(booking_date, booking_time, duration_minutes=60)

        link_rv = self.client.post('/api/calendar/public-link')
        assert link_rv.status_code == 200
        token = link_rv.get_json().get('token')
        assert token

        public_rv = self.client.post(f'/api/calendar/public/{token}/book', data=dict(
            name='Public Booker',
            date=booking_date,
            time=booking_time,
            duration_minutes='60'
        ))
        assert public_rv.status_code == 400
        assert public_rv.get_json().get('message') == 'Phone or email is required.'

    def test_public_self_booking_creates_pending_patient_and_notification(self):
        self.login('admin', 'admin')
        booking_date, booking_time = self.next_allowed_booking_slot(preferred_times=['09:00', '10:00', '12:30', '14:00'])
        self.add_vacancy(booking_date, booking_time, duration_minutes=60)

        link_rv = self.client.post('/api/calendar/public-link')
        assert link_rv.status_code == 200
        payload = link_rv.get_json()
        token = payload.get('token')
        assert token
        assert '/calendar/public/' in payload.get('url', '')

        public_rv = self.client.post(f'/api/calendar/public/{token}/book', data=dict(
            name='Dana Public',
            birth_date='1990-05-10',
            phone='050-1234567',
            date=booking_date,
            time=booking_time,
            duration_minutes='60'
        ))
        assert public_rv.status_code == 200
        assert public_rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            patient = db.execute('''
                SELECT id, name, status, phone, birth_date
                FROM patients
                WHERE name = ?
                ORDER BY id DESC
                LIMIT 1
            ''', ('Dana Public',)).fetchone()
            assert patient is not None
            assert patient['status'] == 'waiting'
            assert patient['phone'] == '050-1234567'
            assert patient['birth_date'] == '1990-05-10'

            appt = db.execute('''
                SELECT patient_id, appointment_date, appointment_time, is_recurring
                FROM appointments
                WHERE patient_id = ?
                ORDER BY id DESC
                LIMIT 1
            ''', (patient['id'],)).fetchone()
            assert appt is not None
            assert appt['appointment_date'] == booking_date
            assert appt['appointment_time'] == booking_time
            assert int(appt['is_recurring'] or 0) == 0

            notif = db.execute('''
                SELECT message
                FROM notifications
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert notif is not None
            assert 'New pending patient' in notif['message']
            assert 'Dana Public' in notif['message']

    def test_public_link_uses_configured_public_base_url(self):
        self.login('admin', 'admin')
        previous_base = app.config.get('PUBLIC_BASE_URL', '')
        app.config['PUBLIC_BASE_URL'] = 'https://clinic.example.com'
        try:
            rv = self.client.post('/api/calendar/public-link')
            assert rv.status_code == 200
            payload = rv.get_json()
            assert payload['url'].startswith('https://clinic.example.com/calendar/public/')
        finally:
            app.config['PUBLIC_BASE_URL'] = previous_base

    def test_public_link_uses_forwarded_proxy_headers(self):
        self.login('admin', 'admin')
        previous_base = app.config.get('PUBLIC_BASE_URL', '')
        app.config['PUBLIC_BASE_URL'] = ''
        try:
            rv = self.client.post('/api/calendar/public-link', headers={
                'X-Forwarded-Proto': 'https',
                'X-Forwarded-Host': 'booking.public.example'
            })
            assert rv.status_code == 200
            payload = rv.get_json()
            assert payload['url'].startswith('https://booking.public.example/calendar/public/')
        finally:
            app.config['PUBLIC_BASE_URL'] = previous_base

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

    def test_admin_recurring_block_creation(self):
        self.login('admin', 'admin')
        booking_date, booking_time = self.next_allowed_booking_slot(preferred_times=['10:00', '09:00', '14:00'])
        anchor = datetime.strptime(booking_date, '%Y-%m-%d').date()
        repeat_until = (anchor + timedelta(days=14)).isoformat()
        end_time = (datetime.strptime(booking_time, '%H:%M') + timedelta(hours=1)).strftime('%H:%M')

        rv = self.client.post('/api/calendar/block', data=dict(
            blocked_date=booking_date,
            blocked_time=booking_time,
            end_time=end_time,
            block_type='blocked',
            recurrence_pattern='weekly',
            repeat_until=repeat_until,
            title='Clinic Block'
        ))
        assert rv.status_code == 200
        payload = rv.get_json()
        assert payload.get('status') == 'success'
        assert int(payload.get('created') or 0) == 3

        with app.app_context():
            db = get_db()
            rows = db.execute('''
                SELECT blocked_date, blocked_time
                FROM blocked_slots
                WHERE title = 'Clinic Block'
                ORDER BY blocked_date ASC
            ''').fetchall()
            assert len(rows) == 3
            assert rows[0]['blocked_date'] == booking_date

    def test_admin_can_update_special_block(self):
        self.login('admin', 'admin')
        booking_date, booking_time = self.next_allowed_booking_slot(preferred_times=['10:00', '09:00', '14:00'])
        end_time = (datetime.strptime(booking_time, '%H:%M') + timedelta(hours=1)).strftime('%H:%M')

        create_rv = self.client.post('/api/calendar/block', data=dict(
            blocked_date=booking_date,
            blocked_time=booking_time,
            end_time=end_time,
            block_type='special',
            title='Original Special',
            is_private='1'
        ))
        assert create_rv.status_code == 200
        assert create_rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT id FROM blocked_slots ORDER BY id DESC LIMIT 1').fetchone()
            assert row is not None
            block_id = row['id']

        update_rv = self.client.post(f'/api/calendar/block/{block_id}/update', data=dict(
            blocked_date=booking_date,
            blocked_time=booking_time,
            end_time=end_time,
            block_type='blocked',
            title='Updated Block',
            is_private='0'
        ))
        assert update_rv.status_code == 200
        assert update_rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            updated = db.execute('''
                SELECT title, block_type, is_private
                FROM blocked_slots
                WHERE id = ?
            ''', (block_id,)).fetchone()
            assert updated is not None
            assert updated['title'] == 'Updated Block'
            assert updated['block_type'] == 'blocked'
            assert int(updated['is_private'] or 0) == 0

    def test_booking_management_api_upcoming_and_history(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Management Patient',
            status='ongoing'
        ), follow_redirects=True)

        today = datetime.now().date()
        past_day = (today - timedelta(days=2)).isoformat()
        future_day = (today + timedelta(days=2)).isoformat()

        with app.app_context():
            db = get_db()
            db.execute('''
                INSERT INTO appointments (patient_id, appointment_date, appointment_time, duration_minutes, status, is_recurring)
                VALUES (1, ?, '10:00', 60, 'scheduled', 0)
            ''', (future_day,))
            db.execute('''
                INSERT INTO appointments (patient_id, appointment_date, appointment_time, duration_minutes, status, is_recurring)
                VALUES (1, ?, '11:00', 60, 'scheduled', 0)
            ''', (past_day,))
            db.execute('''
                INSERT INTO blocked_slots (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
                VALUES (?, '12:00', 60, 'Future Block', 0, 'blocked', 1)
            ''', (future_day,))
            db.execute('''
                INSERT INTO blocked_slots (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
                VALUES (?, '13:00', 60, 'Past Block', 0, 'special', 1)
            ''', (past_day,))
            db.commit()

        upcoming_rv = self.client.get('/api/calendar/bookings?mode=upcoming')
        assert upcoming_rv.status_code == 200
        upcoming_items = upcoming_rv.get_json().get('items', [])
        assert any(item.get('kind') == 'appointment' and item.get('date') == future_day for item in upcoming_items)
        assert any(item.get('kind') == 'block' and item.get('date') == future_day for item in upcoming_items)

        history_rv = self.client.get('/api/calendar/bookings?mode=history')
        assert history_rv.status_code == 200
        history_items = history_rv.get_json().get('items', [])
        assert any(item.get('kind') == 'appointment' and item.get('date') == past_day for item in history_items)
        assert any(item.get('kind') == 'block' and item.get('date') == past_day for item in history_items)

    def test_ongoing_previous_week_auto_promoted_to_recurring(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Auto Recurring Ongoing',
            status='ongoing'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            today = datetime.now().date()
            current_week_start = today - timedelta(days=(today.weekday() + 1) % 7)
            prev_week_day = current_week_start - timedelta(days=2)
            db.execute('''
                INSERT INTO appointments (
                    patient_id, appointment_date, appointment_time, duration_minutes,
                    status, is_recurring
                ) VALUES (?, ?, ?, ?, 'scheduled', 0)
            ''', (1, prev_week_day.isoformat(), '10:00', 60))
            db.commit()

        rv = self.client.get('/api/calendar/snapshot')
        assert rv.status_code == 200

        with app.app_context():
            db = get_db()
            row = db.execute('''
                SELECT is_recurring, recurrence_interval, recurrence_days, recurrence_end_date
                FROM appointments
                WHERE patient_id = 1
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert row is not None
            assert int(row['is_recurring'] or 0) == 1
            assert int(row['recurrence_interval'] or 0) == 1
            assert row['recurrence_days'] is not None
            assert row['recurrence_end_date'] is not None

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

    def test_intake_form_save_edit_and_export_docx(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Intake Flow Patient',
            status='candidate',
            patient_type='initial-intake'
        ), follow_redirects=True)

        # First save should persist intake questionnaire and assessment summary.
        rv = self.client.post('/patient/1/edit_info', data=dict(
            background='',
            treatment_info='',
            active_tab='intake',
            intake_meeting_location='מרפאה',
            intake_main_complaint='Initial complaint text',
            intake_problem_history='Initial problem history'
        ), follow_redirects=False)
        assert rv.status_code == 302
        assert '/patient/1?tab=intake' in rv.headers.get('Location', '')

        with app.app_context():
            db = get_db()
            row = db.execute(
                'SELECT intake_questionnaire, intake_assessment FROM patients WHERE id = 1'
            ).fetchone()
            intake_payload = json.loads(row['intake_questionnaire'])
            assert intake_payload['main_complaint'] == 'Initial complaint text'
            assert intake_payload['problem_history'] == 'Initial problem history'
            assert 'Initial complaint text' in (row['intake_assessment'] or '')

        # Edit should overwrite the stored intake values.
        self.client.post('/patient/1/edit_info', data=dict(
            background='',
            treatment_info='',
            active_tab='intake',
            intake_meeting_location='טלפונית',
            intake_main_complaint='Edited complaint text',
            intake_problem_history='Edited problem history'
        ), follow_redirects=False)

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT intake_questionnaire FROM patients WHERE id = 1').fetchone()
            intake_payload = json.loads(row['intake_questionnaire'])
            assert intake_payload['meeting_location'] == 'טלפונית'
            assert intake_payload['main_complaint'] == 'Edited complaint text'
            assert intake_payload['problem_history'] == 'Edited problem history'

        # Export should produce a DOCX file response.
        export_rv = self.client.get('/patient/1/intake_docx', follow_redirects=False)
        assert export_rv.status_code == 200
        assert (
            export_rv.headers.get('Content-Type')
            == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        export_rv.close()

        export_he_rv = self.client.get('/patient/1/intake_docx?lang=he', follow_redirects=False)
        assert export_he_rv.status_code == 200
        assert (
            export_he_rv.headers.get('Content-Type')
            == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        export_he_rv.close()

    def test_legacy_plain_text_intake_can_be_loaded_edited_and_exported(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Legacy Intake Patient',
            status='candidate',
            patient_type='initial-intake',
            intake_assessment='Main complaint:\nLegacy complaint',
            intake_questionnaire='Main complaint:\nLegacy complaint\n\nProblem history / current illness:\nLegacy history'
        ), follow_redirects=True)

        intake_page = self.client.get('/patient/1?tab=intake', follow_redirects=True)
        assert intake_page.status_code == 200
        assert b'Legacy complaint' in intake_page.data

        self.client.post('/patient/1/edit_info', data=dict(
            background='',
            treatment_info='',
            active_tab='intake',
            intake_main_complaint='Updated legacy complaint',
            intake_problem_history='Updated legacy history'
        ), follow_redirects=False)

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT intake_questionnaire FROM patients WHERE id = 1').fetchone()
            parsed = json.loads(row['intake_questionnaire'])
            assert parsed['main_complaint'] == 'Updated legacy complaint'
            assert parsed['problem_history'] == 'Updated legacy history'

        export_rv = self.client.get('/patient/1/intake_docx', follow_redirects=False)
        assert export_rv.status_code == 200
        assert (
            export_rv.headers.get('Content-Type')
            == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        export_rv.close()

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

    def test_vacancy_create_supports_one_time_and_weekly(self):
        """Admin can create vacancy slots as one-time or weekly recurring."""
        self.login('admin', 'admin')
        future_day = (datetime.now().date() + timedelta(days=3)).isoformat()

        one_time_rv = self.client.post('/api/calendar/vacancy', data=dict(
            slot_date=future_day,
            slot_time='15:00',
            end_time='16:00',
            recurrence_pattern='one-time'
        ))
        assert one_time_rv.status_code == 200
        one_time_data = one_time_rv.get_json()
        assert one_time_data.get('status') == 'success'
        assert one_time_data.get('recurrence_pattern') == 'one-time'
        assert one_time_data.get('override_id')

        weekly_rv = self.client.post('/api/calendar/vacancy', data=dict(
            slot_date=future_day,
            slot_time='10:00',
            end_time='11:00',
            recurrence_pattern='weekly'
        ))
        assert weekly_rv.status_code == 200
        weekly_data = weekly_rv.get_json()
        assert weekly_data.get('status') == 'success'
        assert weekly_data.get('recurrence_pattern') == 'weekly'
        assert weekly_data.get('recurring_id')

        with app.app_context():
            db = get_db()
            recurring = db.execute('SELECT * FROM vacancy_recurring WHERE id = ?', (weekly_data['recurring_id'],)).fetchone()
            assert recurring is not None

    def test_weekly_vacancy_appears_in_next_week_snapshot(self):
        """Weekly recurring vacancy should appear again in the next week's snapshot."""
        self.login('admin', 'admin')
        anchor_date = datetime.now().date() + timedelta(days=2)
        anchor_iso = anchor_date.isoformat()

        create_rv = self.client.post('/api/calendar/vacancy', data=dict(
            slot_date=anchor_iso,
            slot_time='09:30',
            end_time='10:30',
            recurrence_pattern='weekly'
        ))
        assert create_rv.status_code == 200
        assert create_rv.get_json().get('status') == 'success'

        next_week_day = anchor_date + timedelta(days=7)
        next_week_start = next_week_day - timedelta(days=(next_week_day.weekday() + 1) % 7)
        snapshot_rv = self.client.get(f'/api/calendar/snapshot?week_start={next_week_start.isoformat()}')
        assert snapshot_rv.status_code == 200
        payload = snapshot_rv.get_json()
        available = payload.get('available_slots', [])
        assert any(slot['date'] == next_week_day.isoformat() and slot['time'] == '09:30' for slot in available)

    def test_admin_vacancy_occupy(self):
        """Admin can manually occupy a vacancy slot using a patient ID."""
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Occupy Patient',
            status='candidate'
        ), follow_redirects=True)

        future_day = (datetime.now().date() + timedelta(days=7)).isoformat()
        create_rv = self.client.post('/api/calendar/vacancy', data=dict(
            slot_date=future_day,
            slot_time='13:00',
            end_time='14:00',
            recurrence_pattern='one-time'
        ))
        assert create_rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            override_row = db.execute(
                "SELECT id FROM slots_override WHERE slot_date = ? AND slot_time = '13:00'",
                (future_day,)
            ).fetchone()
            override_id = override_row['id']

        rv = self.client.post(f'/api/calendar/vacancy/{override_id}/occupy', data=dict(
            patient_id='1'
        ))
        assert rv.status_code == 200
        assert rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            slot = db.execute(
                "SELECT status, booked_by_name FROM slots_override WHERE id = ?",
                (override_id,)
            ).fetchone()
            assert slot['status'] == 'booked'
            assert slot['booked_by_name'] == 'Occupy Patient'

    def test_vacancies_list_api(self):
        """Admin gets list of vacancy slots with status."""
        self.login('admin', 'admin')
        future_day = (datetime.now().date() + timedelta(days=8)).isoformat()
        self.client.post('/api/calendar/vacancy', data=dict(
            slot_date=future_day,
            slot_time='16:00',
            end_time='17:00',
            recurrence_pattern='one-time'
        ))
        self.client.post('/api/calendar/vacancy', data=dict(
            slot_date=future_day,
            slot_time='18:00',
            end_time='19:00',
            recurrence_pattern='weekly'
        ))
        rv = self.client.get('/api/calendar/vacancies')
        assert rv.status_code == 200
        items = rv.get_json().get('items', [])
        assert any(i['kind'] == 'one-time' and i['date'] == future_day and i['status'] == 'available' for i in items)
        assert any(i['kind'] == 'weekly' and i['status'] == 'active' for i in items)

    def test_admin_can_delete_weekly_vacancy(self):
        self.login('admin', 'admin')
        future_day = (datetime.now().date() + timedelta(days=10)).isoformat()
        create_rv = self.client.post('/api/calendar/vacancy', data=dict(
            slot_date=future_day,
            slot_time='10:00',
            end_time='11:00',
            recurrence_pattern='weekly'
        ))
        recurring_id = create_rv.get_json().get('recurring_id')
        assert recurring_id

        del_rv = self.client.post(f'/api/calendar/vacancy/{recurring_id}/delete', data=dict(kind='weekly'))
        assert del_rv.status_code == 200
        assert del_rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT id FROM vacancy_recurring WHERE id = ?', (recurring_id,)).fetchone()
            assert row is None

    def test_group_member_history_tracks_join_leave_cycles(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Group Member A', status='ongoing', patient_type='group'), follow_redirects=True)
        self.client.post('/groups', data=dict(name='Trauma Group', group_type='therapy', description='Weekly group'), follow_redirects=True)

        self.client.post('/groups/1/members', data=dict(patient_id='1'), follow_redirects=True)
        self.client.post('/groups/1/members/1/remove', data=dict(), follow_redirects=True)
        self.client.post('/groups/1/members', data=dict(patient_id='1'), follow_redirects=True)

        with app.app_context():
            db = get_db()
            active = db.execute('''
                SELECT left_at
                FROM group_members
                WHERE group_id = 1 AND patient_id = 1
            ''').fetchone()
            assert active is not None
            assert active['left_at'] is None

            history = db.execute('''
                SELECT joined_at, left_at
                FROM group_member_history
                WHERE group_id = 1 AND patient_id = 1
                ORDER BY id ASC
            ''').fetchall()
            assert len(history) == 2
            assert history[0]['left_at'] is not None
            assert history[1]['left_at'] is None

    def test_group_recurrence_update_future_and_attendance_missed_reason(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Group Patient One', status='ongoing', patient_type='group'), follow_redirects=True)
        self.client.post('/add_patient', data=dict(name='Group Patient Two', status='ongoing', patient_type='group'), follow_redirects=True)
        self.client.post('/groups', data=dict(name='Skills Group', group_type='skills', description='Skills training'), follow_redirects=True)
        self.client.post('/groups/1/members', data=dict(patient_id='1'), follow_redirects=True)
        self.client.post('/groups/1/members', data=dict(patient_id='2'), follow_redirects=True)

        start_date = (datetime.now().date() + timedelta(days=3)).isoformat()
        add_rv = self.client.post('/groups/1/sessions', data=dict(
            session_date=start_date,
            session_time='10:00',
            end_time='11:00',
            title='Skills Practice',
            facilitator='Dr. A',
            meeting_type='in-person',
            meeting_link='',
            recurrence_mode='weekly',
            recurrence_interval_weeks='1',
            recurrence_count='3'
        ), follow_redirects=True)
        assert add_rv.status_code == 200

        with app.app_context():
            db = get_db()
            sessions = db.execute('''
                SELECT id, series_id, session_date, session_time
                FROM group_sessions
                WHERE group_id = 1
                ORDER BY session_date ASC
            ''').fetchall()
            assert len(sessions) == 3
            assert sessions[0]['series_id'] is not None
            first_session_id = sessions[0]['id']

        update_rv = self.client.post(f'/api/groups/sessions/{first_session_id}/update', data=dict(
            session_date=(datetime.now().date() + timedelta(days=4)).isoformat(),
            session_time='11:00',
            end_time='12:00',
            title='Skills Practice Updated',
            facilitator='Dr. B',
            meeting_type='zoom',
            meeting_link='https://example.com/meeting',
            apply_scope='future'
        ))
        assert update_rv.status_code == 200
        assert update_rv.get_json().get('status') == 'success'

        with app.app_context():
            db = get_db()
            updated = db.execute('''
                SELECT session_time, title, facilitator, meeting_type, meeting_link
                FROM group_sessions
                WHERE group_id = 1
                ORDER BY session_date ASC
            ''').fetchall()
            assert len(updated) == 3
            assert all(row['session_time'] == '11:00' for row in updated)
            assert all((row['meeting_type'] or '') == 'zoom' for row in updated)

        record_rv = self.client.post(f'/groups/sessions/{first_session_id}/record', data={
            'session_status': 'completed',
            'session_summary': 'Reviewed coping strategies',
            'attendance_1': 'present',
            'attendance_2': 'missed',
            'absence_reason_2': 'Fever',
            'notified_on_time_2': 'on',
            'attendance_note_2': 'Will follow up next week'
        }, follow_redirects=True)
        assert record_rv.status_code == 200

        with app.app_context():
            db = get_db()
            attendance = db.execute('''
                SELECT attendance_status, absence_reason, notified_on_time
                FROM group_session_attendance
                WHERE session_id = ? AND patient_id = 2
            ''', (first_session_id,)).fetchone()
            assert attendance is not None
            assert attendance['attendance_status'] == 'missed'
            assert attendance['absence_reason'] == 'Fever'
            assert int(attendance['notified_on_time'] or 0) == 1

            auto_note = db.execute('''
                SELECT is_missed_meeting, missed_reason, content
                FROM notes
                WHERE patient_id = 2
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert auto_note is not None
            assert int(auto_note['is_missed_meeting'] or 0) == 1
            assert auto_note['missed_reason'] == 'Fever'
            assert 'Missed group session' in auto_note['content']

    def test_individual_treatment_note_can_record_missed_reason(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Missed Session Patient', status='ongoing'), follow_redirects=True)

        rv = self.client.post('/patient/1/add_note', data=dict(
            session_number='1',
            note_date=datetime.now().date().isoformat(),
            content='',
            is_missed_meeting='on',
            missed_reason='Family emergency'
        ), follow_redirects=True)
        assert rv.status_code == 200

        with app.app_context():
            db = get_db()
            note = db.execute('''
                SELECT content, is_missed_meeting, missed_reason
                FROM notes
                WHERE patient_id = 1
                ORDER BY id DESC
                LIMIT 1
            ''').fetchone()
            assert note is not None
            assert int(note['is_missed_meeting'] or 0) == 1
            assert note['missed_reason'] == 'Family emergency'
            assert 'Missed meeting documented' in note['content']

    def test_groups_dashboard_suggests_only_group_patients(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(
            name='Private Suggestion Patient',
            status='ongoing',
            patient_type='private'
        ), follow_redirects=True)
        self.client.post('/add_patient', data=dict(
            name='Group Suggestion Patient',
            status='ongoing',
            patient_type='group'
        ), follow_redirects=True)
        self.client.post('/groups', data=dict(name='Suggestion Group', group_type='support', description=''), follow_redirects=True)

        rv = self.client.get('/groups', follow_redirects=True)
        assert rv.status_code == 200
        assert b'Group Suggestion Patient' in rv.data
        assert b'Private Suggestion Patient' not in rv.data

    def test_edit_group_membership_dates(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Membership Date Patient', status='ongoing', patient_type='group'), follow_redirects=True)
        self.client.post('/groups', data=dict(name='Date Edit Group', group_type='support', description=''), follow_redirects=True)
        self.client.post('/groups/1/members', data=dict(patient_id='1'), follow_redirects=True)

        with app.app_context():
            db = get_db()
            history_id = db.execute('''
                SELECT id FROM group_member_history WHERE group_id = 1 AND patient_id = 1 ORDER BY id DESC LIMIT 1
            ''').fetchone()['id']

        self.client.post(f'/groups/history/{history_id}/dates', data=dict(
            joined_date='2026-01-02',
            left_date='2026-01-10'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            hist = db.execute('SELECT joined_at, left_at FROM group_member_history WHERE id = ?', (history_id,)).fetchone()
            gm = db.execute('SELECT joined_at, left_at FROM group_members WHERE group_id = 1 AND patient_id = 1').fetchone()
            assert hist is not None
            assert hist['joined_at'].startswith('2026-01-02')
            assert hist['left_at'].startswith('2026-01-10')
            assert gm is not None
            assert gm['left_at'] is not None

    def test_patient_card_can_edit_group_attendance_and_summary(self):
        self.login('admin', 'admin')
        self.client.post('/add_patient', data=dict(name='Card Edit Patient', status='ongoing', patient_type='group'), follow_redirects=True)
        self.client.post('/groups', data=dict(name='Card Edit Group', group_type='support', description=''), follow_redirects=True)
        self.client.post('/groups/1/members', data=dict(patient_id='1'), follow_redirects=True)

        session_date = (datetime.now().date() + timedelta(days=2)).isoformat()
        self.client.post('/groups/1/sessions', data=dict(
            session_date=session_date,
            session_time='09:00',
            end_time='10:00',
            title='Card Editable Session',
            facilitator='Admin',
            meeting_type='in-person',
            recurrence_mode='one-time'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            session_id = db.execute('SELECT id FROM group_sessions ORDER BY id DESC LIMIT 1').fetchone()['id']
            db.execute('''
                INSERT INTO group_session_attendance (session_id, patient_id, attendance_status, absence_reason, notified_on_time, attendance_note)
                VALUES (?, 1, 'pending', NULL, 0, NULL)
            ''', (session_id,))
            db.commit()

        rv = self.client.post(f'/patient/1/group_attendance/{session_id}/update', data=dict(
            attendance_status='missed',
            absence_reason='Transportation issue',
            notified_on_time='on',
            attendance_note='Patient called in advance',
            session_summary='Group discussed coping plans',
            active_tab='info'
        ), follow_redirects=True)
        assert rv.status_code == 200

        with app.app_context():
            db = get_db()
            att = db.execute('''
                SELECT attendance_status, absence_reason, notified_on_time, attendance_note
                FROM group_session_attendance
                WHERE session_id = ? AND patient_id = 1
            ''', (session_id,)).fetchone()
            sess = db.execute('SELECT session_summary FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
            assert att is not None
            assert att['attendance_status'] == 'missed'
            assert att['absence_reason'] == 'Transportation issue'
            assert int(att['notified_on_time'] or 0) == 1
            assert att['attendance_note'] == 'Patient called in advance'
            assert sess['session_summary'] == 'Group discussed coping plans'

if __name__ == '__main__':
    unittest.main()
