import unittest
import tempfile
import os
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
            db.execute(
                "INSERT INTO users (username, password_hash, role, is_active, force_password_change) VALUES (?, ?, ?, ?, ?)",
                ('admin', generate_password_hash('admin'), 'admin', 1, 0)
            )
            db.execute(
                "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
                ('disabled_admin', generate_password_hash('admin'), 'admin', 0)
            )
            db.execute(
                "INSERT INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled, force_password_change) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('totp_admin', generate_password_hash('admin'), 'admin', 1, pyotp.random_base32(), 1, 0)
            )
            db.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_admin_login_success_redirects(self):
        rv = self.client.post('/login', data=dict(
            username='admin',
            password='admin'
        ), follow_redirects=False)
        self.assertEqual(rv.status_code, 302)
        self.assertIn('/admin/profile', rv.headers.get('Location', ''))

    def test_login_invalid_credentials(self):
        rv = self.client.post('/login', data=dict(
            username='admin',
            password='wrong-password'
        ), follow_redirects=True)
        self.assertIn(b'Invalid username or password', rv.data)

    def test_disabled_account_cannot_login(self):
        rv = self.client.post('/login', data=dict(
            username='disabled_admin',
            password='admin'
        ), follow_redirects=True)
        self.assertIn(b'Account is disabled. Contact administrator.', rv.data)

    def test_admin_totp_login_prompts_second_step(self):
        app.config['TESTING'] = False
        try:
            rv = self.client.post('/login', data=dict(
                username='totp_admin',
                password='admin'
            ), follow_redirects=True)
        finally:
            app.config['TESTING'] = True
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'name="otp_code"', rv.data)
        self.assertIn(b'totp_admin', rv.data)

    def test_admin_without_totp_is_redirected_to_profile_setup(self):
        app.config['TESTING'] = False
        try:
            rv = self.client.post('/login', data=dict(
                username='admin',
                password='admin'
            ), follow_redirects=False)
        finally:
            app.config['TESTING'] = True

        self.assertEqual(rv.status_code, 302)
        self.assertIn('/admin/profile', rv.headers.get('Location', ''))

    def test_admin_totp_login_with_valid_code_redirects(self):
        with app.app_context():
            db = get_db()
            row = db.execute('SELECT totp_secret FROM users WHERE username = ?', ('totp_admin',)).fetchone()
        self.assertIsNotNone(row)
        code = pyotp.TOTP(row['totp_secret']).now()

        app.config['TESTING'] = False
        try:
            first = self.client.post('/login', data=dict(
                username='totp_admin',
                password='admin'
            ), follow_redirects=False)
        finally:
            app.config['TESTING'] = True
        self.assertEqual(first.status_code, 200)

        second = self.client.post('/login', data=dict(
            otp_code=code
        ), follow_redirects=False)
        self.assertEqual(second.status_code, 302)
        self.assertIn('/patients', second.headers.get('Location', ''))

    def test_path_traversal_in_download_file(self):
        app.config['TESTING'] = True
        self.client.post('/login', data=dict(username='admin', password='admin'), follow_redirects=True)

        # Test basic traversal attempt
        rv = self.client.get('/uploads/..%2F..%2F..%2F..%2F..%2F..%2F..%2Fetc%2Fpasswd')
        self.assertEqual(rv.status_code, 404)

        # Test the DB bypass / file mapping mechanism safely resolving the file instead of allowing traversal
        rv = self.client.get('/uploads/../../../../../../../etc/passwd')
        self.assertEqual(rv.status_code, 404)

if __name__ == '__main__':
    unittest.main()
