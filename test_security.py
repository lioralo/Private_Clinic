import unittest
import tempfile
import os
import sqlite3
import pyotp
from app import app, get_db

class SecurityTestCase(unittest.TestCase):

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app.config['DATABASE'] = self.db_path
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
        self.client = app.test_client()

        with app.app_context():
            db = get_db()
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()

            from werkzeug.security import generate_password_hash
            hashed_pw = generate_password_hash('admin')
            # Create admin without secret token first to test setup flow if needed, 
            # or with it to test 2FA enforcement.
            self.admin_secret = pyotp.random_base32()
            db.execute("INSERT INTO users (username, password_hash, role, secret_token) VALUES (?, ?, ?, ?)",
                       ('admin', hashed_pw, 'admin', self.admin_secret))
            db.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_admin_2fa_required(self):
        # Login without OTP
        rv = self.client.post('/login', data=dict(
            username='admin',
            password='admin'
        ), follow_redirects=True)
        # Should ask for OTP
        assert b'2FA Code' in rv.data
        assert b'Required for admin access' in rv.data

    def test_admin_2fa_success(self):
        # Login with OTP
        totp = pyotp.TOTP(self.admin_secret)
        otp = totp.now()
        rv = self.client.post('/login', data=dict(
            username='admin',
            password='admin',
            otp=otp
        ), follow_redirects=True)
        # Should be logged in (redirected to patients list)
        assert b'Ongoing' in rv.data 

    def test_admin_2fa_invalid(self):
        # Login with invalid OTP
        rv = self.client.post('/login', data=dict(
            username='admin',
            password='admin',
            otp='000000'
        ), follow_redirects=True)
        # Should fail
        assert b'Invalid 2FA Code' in rv.data

if __name__ == '__main__':
    unittest.main()
