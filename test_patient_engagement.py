import os
import shutil
import unittest
import tempfile
import sqlite3
import json
from datetime import datetime, timedelta, timezone

import app as app_module
from app import app, init_db, get_db

class PatientEngagementTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.upload_dir = tempfile.mkdtemp()
        self.patient_logs_dir = tempfile.mkdtemp()
        self.app_log_fd, self.app_log_path = tempfile.mkstemp()

        app.config['DATABASE'] = self.db_path
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['UPLOAD_FOLDER'] = self.upload_dir
        app.config['PATIENT_LOGS_FOLDER'] = self.patient_logs_dir
        app.config['APP_LOG_FILE'] = self.app_log_path
        self.client = app.test_client()

        with app.app_context():
            init_db()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)
        os.close(self.app_log_fd)
        if os.path.exists(self.app_log_path):
            os.unlink(self.app_log_path)
        shutil.rmtree(self.upload_dir, ignore_errors=True)
        shutil.rmtree(self.patient_logs_dir, ignore_errors=True)

    def login_admin(self, username, password):
        return self.client.post('/login', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def setup_patient_and_login(self):
        # Login as admin to setup a patient
        self.login_admin('lioraloni', 'Flo@tingind4')

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

        self.client.get('/logout', follow_redirects=True)

        # Login as the patient
        self.client.post('/login', data=dict(
            username='patient',
            password='password'
        ), follow_redirects=True)

    def test_patient_dashboard_redirects_admin(self):
        self.login_admin('lioraloni', 'Flo@tingind4')
        rv = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(rv.status_code, 302)
        self.assertIn('/patients', rv.headers.get('Location', ''))

    def test_patient_dashboard_renders(self):
        self.setup_patient_and_login()

        # Add some data for the dashboard to render
        with app.app_context():
            db = get_db()
            today = datetime.now().date()
            # An appointment
            db.execute('''
                INSERT INTO appointments (patient_id, appointment_date, appointment_time, meeting_type, status)
                VALUES (1, ?, '10:00', 'zoom', 'scheduled')
            ''', (today.isoformat(),))
            # A goal
            db.execute('''
                INSERT INTO goals (patient_id, description, status)
                VALUES (1, 'Improve testing', 'active')
            ''')
            # A note
            db.execute('''
                INSERT INTO notes (patient_id, note_date, content)
                VALUES (1, ?, 'Great progress')
            ''', (today.isoformat(),))
            db.commit()

        rv = self.client.get('/dashboard', follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'Test Patient', rv.data)
        # Check that engagement data properties are passed and rendered, we look for some keywords
        # Note: we don't know the exact HTML of the patient_dashboard.html, but checking 200 is good.

    def test_api_upcoming_appointments(self):
        self.setup_patient_and_login()

        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        with app.app_context():
            db = get_db()
            db.execute('''
                INSERT INTO appointments (patient_id, appointment_date, appointment_time, meeting_type, status)
                VALUES (1, ?, '10:00', 'zoom', 'scheduled')
            ''', (tomorrow.isoformat(),))
            db.commit()

        rv = self.client.get('/api/appointments/upcoming')
        self.assertEqual(rv.status_code, 200)

        data = rv.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['date'], tomorrow.isoformat())
        self.assertEqual(data[0]['meeting_type'], 'zoom')
        self.assertTrue(data[0]['is_tomorrow'])
        self.assertFalse(data[0]['is_today'])

    def test_api_engagement_stats(self):
        self.setup_patient_and_login()

        today = datetime.now().date()

        with app.app_context():
            db = get_db()
            # 1 completed in-person
            db.execute('''
                INSERT INTO appointments (patient_id, appointment_date, appointment_time, meeting_type, status)
                VALUES (1, ?, '10:00', 'in-person', 'completed')
            ''', (today.isoformat(),))
            # 1 scheduled zoom
            db.execute('''
                INSERT INTO appointments (patient_id, appointment_date, appointment_time, meeting_type, status)
                VALUES (1, ?, '11:00', 'zoom', 'scheduled')
            ''', (today.isoformat(),))
            db.commit()

        rv = self.client.get('/api/engagement/stats')
        self.assertEqual(rv.status_code, 200)

        data = rv.get_json()
        self.assertEqual(data['total_appointments'], 2)
        self.assertEqual(data['completed_appointments'], 1)
        self.assertEqual(data['online_appointments'], 1)
        # Completion rate: (1 / 2) * 100 = 50
        self.assertEqual(data['completion_rate'], 50)

if __name__ == '__main__':
    unittest.main()
