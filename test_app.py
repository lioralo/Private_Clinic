import os
import unittest
import tempfile
import sqlite3
import pyotp
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
            # Create tables
            db = get_db()
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()

            # Create admin user manually for testing if init_db logic isn't reused or to be explicit
            from werkzeug.security import generate_password_hash
            hashed_pw = generate_password_hash('admin')
            self.admin_otp_secret = 'JBSWY3DPEHPK3PXP' # Fixed secret for testing

            # Ensure otp_secret column exists
            try:
                db.execute("ALTER TABLE users ADD COLUMN otp_secret TEXT")
                db.commit()
            except sqlite3.OperationalError:
                pass # Column already exists

            db.execute("INSERT INTO users (username, password_hash, role, otp_secret) VALUES (?, ?, ?, ?)",
                       ('admin', hashed_pw, 'admin', self.admin_otp_secret))
            db.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, username, password, otp_token=None):
        data = dict(username=username, password=password)
        if otp_token is not None:
            data['otp_token'] = otp_token
        return self.client.post('/login', data=data, follow_redirects=True)

    def logout(self):
        return self.client.get('/logout', follow_redirects=True)

    def test_login_logout(self):
        totp = pyotp.TOTP(self.admin_otp_secret)
        rv = self.login('admin', 'admin', otp_token=totp.now())
        assert b'Log out' in rv.data or b'Logout' in rv.data
        rv = self.logout()
        assert b'Login' in rv.data

    def test_add_patient(self):
        totp = pyotp.TOTP(self.admin_otp_secret)
        self.login('admin', 'admin', otp_token=totp.now())
        rv = self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing',
            email='test@example.com',
            phone='555-1234'
        ), follow_redirects=True)
        assert b'Test Patient' in rv.data
        assert b'ongoing' in rv.data

    def test_add_note(self):
        totp = pyotp.TOTP(self.admin_otp_secret)
        self.login('admin', 'admin', otp_token=totp.now())
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
        totp = pyotp.TOTP(self.admin_otp_secret)
        self.login('admin', 'admin', otp_token=totp.now())
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
        totp = pyotp.TOTP(self.admin_otp_secret)
        self.login('admin', 'admin', otp_token=totp.now())
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

        # Login as patient (no OTP token needed)
        rv = self.login('patient', 'password')
        assert b'Financial Summary' in rv.data or b'Current Balance' in rv.data  # Should be on dashboard

        # Try to access admin page
        rv = self.client.get('/add_patient', follow_redirects=True)
        assert b'Access denied' in rv.data or b'Unauthorized' in rv.data or rv.status_code == 403 or b'Dashboard' in rv.data # Redirected to dashboard

    def test_add_appointment(self):
        totp = pyotp.TOTP(self.admin_otp_secret)
        self.login('admin', 'admin', otp_token=totp.now())
        self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing'
        ), follow_redirects=True)

        rv = self.client.post('/patient/1/add_appointment', data=dict(
            date='2024-01-01',
            time='10:00',
            cost='100.00'
        ), follow_redirects=True)
        assert b'2024-01-01' in rv.data
        assert b'100.0' in rv.data

if __name__ == '__main__':
    unittest.main()
