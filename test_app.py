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
            # Admin needs a secret token for 2FA in tests unless we bypass it or set it up.
            # To test login success, we should set it up or handle the setup flow.
            # Let's set a known secret.
            secret = pyotp.random_base32()
            self.admin_secret = secret
            db.execute("INSERT INTO users (username, password_hash, role, secret_token) VALUES (?, ?, ?, ?)",
                       ('admin', hashed_pw, 'admin', secret))
            db.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, username, password):
        # Admin requires OTP
        data = dict(username=username, password=password)
        if username == 'admin':
            totp = pyotp.TOTP(self.admin_secret)
            data['otp'] = totp.now()
        
        return self.client.post('/login', data=data, follow_redirects=True)

    def logout(self):
        return self.client.get('/logout', follow_redirects=True)

    def test_login_logout(self):
        rv = self.login('admin', 'admin')
        # Check for successful login indicators (e.g., Logout link, or admin specific content)
        assert b'Logout' in rv.data
        rv = self.logout()
        assert b'Sign In' in rv.data # updated text from Login to Sign In

    def test_add_patient(self):
        self.login('admin', 'admin')
        rv = self.client.post('/add_patient', data=dict(
            name='Test Patient',
            status='ongoing',
            email='test@example.com',
            phone='555-1234'
        ), follow_redirects=True)
        # Check if redirected to patients list and contains the patient name
        assert b'Test Patient' in rv.data
        assert b'Ongoing' in rv.data

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
        assert b'50.0' in rv.data or b'50.00' in rv.data
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
        # Check for dashboard content
        assert b'Financial Summary' in rv.data  

        # Try to access admin page
        rv = self.client.get('/add_patient', follow_redirects=True)
        # Should be redirected to dashboard or denied
        assert b'Dashboard' in rv.data or b'Access denied' in rv.data

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
        assert b'2024-01-01' in rv.data
        assert b'100.0' in rv.data or b'100.00' in rv.data

if __name__ == '__main__':
    unittest.main()
