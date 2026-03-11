import unittest
import tempfile
import os
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
                "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
                ('admin', generate_password_hash('admin'), 'admin', 1)
            )
            db.execute(
                "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
                ('disabled_admin', generate_password_hash('admin'), 'admin', 0)
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
        self.assertIn('/patients', rv.headers.get('Location', ''))

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

if __name__ == '__main__':
    unittest.main()
