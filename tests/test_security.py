import unittest
import tempfile
import os
import re
import pyotp
from app import app, get_db, _run_db_migrations

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
            with app.open_resource('clinic_app/schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()
            _run_db_migrations(db)

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

    def test_login_rate_limit_blocks_after_repeated_failures(self):
        prev_enable = app.config.get('ENABLE_RATE_LIMIT_IN_TESTS')
        prev_max = app.config.get('LOGIN_RATE_LIMIT_MAX_ATTEMPTS')
        prev_window = app.config.get('LOGIN_RATE_LIMIT_WINDOW_SECONDS')
        prev_lockout = app.config.get('LOGIN_RATE_LIMIT_LOCKOUT_SECONDS')

        app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = True
        app.config['LOGIN_RATE_LIMIT_MAX_ATTEMPTS'] = 2
        app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = 60
        app.config['LOGIN_RATE_LIMIT_LOCKOUT_SECONDS'] = 120

        try:
            first = self.client.post('/login', data=dict(
                username='admin',
                password='wrong-password'
            ), follow_redirects=True)
            self.assertIn(b'Invalid username or password', first.data)

            second = self.client.post('/login', data=dict(
                username='admin',
                password='wrong-password'
            ), follow_redirects=True)
            self.assertIn(b'Too many failed login attempts', second.data)

            blocked = self.client.post('/login', data=dict(
                username='admin',
                password='admin'
            ), follow_redirects=True)
            self.assertIn(b'Too many failed login attempts', blocked.data)
            self.assertNotIn(b'Set up two-factor authentication from the admin profile before continuing.', blocked.data)
        finally:
            app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = prev_enable
            app.config['LOGIN_RATE_LIMIT_MAX_ATTEMPTS'] = prev_max
            app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = prev_window
            app.config['LOGIN_RATE_LIMIT_LOCKOUT_SECONDS'] = prev_lockout

    def test_login_rate_limit_resets_after_successful_login(self):
        prev_enable = app.config.get('ENABLE_RATE_LIMIT_IN_TESTS')
        prev_max = app.config.get('LOGIN_RATE_LIMIT_MAX_ATTEMPTS')
        prev_window = app.config.get('LOGIN_RATE_LIMIT_WINDOW_SECONDS')
        prev_lockout = app.config.get('LOGIN_RATE_LIMIT_LOCKOUT_SECONDS')

        app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = True
        app.config['LOGIN_RATE_LIMIT_MAX_ATTEMPTS'] = 2
        app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = 60
        app.config['LOGIN_RATE_LIMIT_LOCKOUT_SECONDS'] = 120

        try:
            fail_once = self.client.post('/login', data=dict(
                username='admin',
                password='wrong-password'
            ), follow_redirects=True)
            self.assertIn(b'Invalid username or password', fail_once.data)

            success = self.client.post('/login', data=dict(
                username='admin',
                password='admin'
            ), follow_redirects=True)
            self.assertIn(b'Set up two-factor authentication from the admin profile before continuing.', success.data)

            self.client.get('/logout', follow_redirects=True)

            fail_after_success = self.client.post('/login', data=dict(
                username='admin',
                password='wrong-password'
            ), follow_redirects=True)
            self.assertIn(b'Invalid username or password', fail_after_success.data)
            self.assertNotIn(b'Too many failed login attempts', fail_after_success.data)
        finally:
            app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = prev_enable
            app.config['LOGIN_RATE_LIMIT_MAX_ATTEMPTS'] = prev_max
            app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = prev_window
            app.config['LOGIN_RATE_LIMIT_LOCKOUT_SECONDS'] = prev_lockout

    def test_disabled_account_cannot_login(self):
        rv = self.client.post('/login', data=dict(
            username='disabled_admin',
            password='admin'
        ), follow_redirects=True)
        self.assertIn(b'Account is disabled. Contact administrator.', rv.data)

    def test_password_reset_request_generates_token_for_admin(self):
        rv = self.client.post('/forgot-password', data={
            'username_or_email': 'admin'
        }, follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'If the account exists and is eligible, a password reset link has been generated.', rv.data)
        self.assertIn(b'Reset link:', rv.data)

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT user_id, token_hash FROM password_reset_tokens ORDER BY id DESC LIMIT 1').fetchone()
            self.assertIsNotNone(row)

    def test_password_reset_token_updates_password(self):
        requested = self.client.post('/forgot-password', data={
            'username_or_email': 'admin'
        }, follow_redirects=True)
        self.assertEqual(requested.status_code, 200)

        html = requested.data.decode('utf-8')
        match = re.search(r'/reset-password/[A-Za-z0-9_\-]+', html)
        self.assertIsNotNone(match)
        reset_path = match.group(0)

        posted = self.client.post(reset_path, data={
            'new_password': 'Secure!XyZ7q',
            'confirm_password': 'Secure!XyZ7q',
        }, follow_redirects=True)
        self.assertEqual(posted.status_code, 200)
        self.assertIn(b'Password updated successfully. Please sign in.', posted.data)

        login = self.client.post('/login', data={
            'username': 'admin',
            'password': 'Secure!XyZ7q',
        }, follow_redirects=False)
        self.assertEqual(login.status_code, 302)
        self.assertIn('/admin/profile', login.headers.get('Location', ''))

        with app.app_context():
            db = get_db()
            used = db.execute(
                'SELECT COUNT(*) AS count FROM password_reset_tokens WHERE used_at IS NOT NULL'
            ).fetchone()
            self.assertGreaterEqual(int(used['count'] or 0), 1)

    def test_password_reset_rejects_invalid_token(self):
        rv = self.client.get('/reset-password/not-a-real-token', follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'Password reset link is invalid or expired.', rv.data)

    def test_password_reset_rejects_weak_password(self):
        requested = self.client.post('/forgot-password', data={
            'username_or_email': 'admin'
        }, follow_redirects=True)
        html = requested.data.decode('utf-8')
        match = re.search(r'/reset-password/[A-Za-z0-9_\-]+', html)
        self.assertIsNotNone(match)

        weak = self.client.post(match.group(0), data={
            'new_password': 'short',
            'confirm_password': 'short',
        }, follow_redirects=True)
        self.assertEqual(weak.status_code, 200)
        self.assertIn(b'Password must include at least 10 characters.', weak.data)

    def test_password_reset_request_rate_limit(self):
        prev_enable = app.config.get('ENABLE_RATE_LIMIT_IN_TESTS')
        prev_max = app.config.get('PASSWORD_RESET_RATE_LIMIT_MAX')
        prev_window = app.config.get('PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS')

        app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = True
        app.config['PASSWORD_RESET_RATE_LIMIT_MAX'] = 1
        app.config['PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS'] = 120

        try:
            first = self.client.post('/forgot-password', data={
                'username_or_email': 'admin'
            }, follow_redirects=True)
            self.assertIn(b'If the account exists and is eligible, a password reset link has been generated.', first.data)

            second = self.client.post('/forgot-password', data={
                'username_or_email': 'admin'
            }, follow_redirects=True)
            self.assertIn(b'Too many reset attempts. Please try again in', second.data)
        finally:
            app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = prev_enable
            app.config['PASSWORD_RESET_RATE_LIMIT_MAX'] = prev_max
            app.config['PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS'] = prev_window

    def test_password_reset_does_not_expose_link_when_not_testing(self):
        previous_testing = app.config.get('TESTING')
        app.config['TESTING'] = False

        try:
            rv = self.client.post('/forgot-password', data={
                'username_or_email': 'admin'
            }, follow_redirects=True)
        finally:
            app.config['TESTING'] = previous_testing

        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'If the account exists and is eligible, a password reset link has been generated.', rv.data)
        self.assertNotIn(b'Reset link:', rv.data)

    def test_session_invalidated_after_session_version_change(self):
        self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin',
        }, follow_redirects=True)

        with app.app_context():
            db = get_db()
            db.execute(
                'UPDATE users SET session_version = COALESCE(session_version, 0) + 1 WHERE username = ?',
                ('admin',),
            )
            db.commit()

        rv = self.client.get('/patients', follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'Your session was invalidated after a security change. Please sign in again.', rv.data)

    def test_admin_smtp_health_endpoint_reports_not_configured(self):
        prev_host = app.config.get('SMTP_HOST')
        prev_email = app.config.get('SMTP_FROM_EMAIL')
        app.config['SMTP_HOST'] = ''
        app.config['SMTP_FROM_EMAIL'] = ''
        try:
            self.client.post('/login', data=dict(
                username='admin',
                password='admin'
            ), follow_redirects=True)

            rv = self.client.get('/admin/smtp/health')
            self.assertEqual(rv.status_code, 200)
            data = rv.get_json()
            self.assertEqual(data['status'], 'error')
            self.assertFalse(bool(data['configured']))
        finally:
            app.config['SMTP_HOST'] = prev_host
            app.config['SMTP_FROM_EMAIL'] = prev_email


    def test_admin_change_password_enforces_strong_policy(self):
        self.client.post('/login', data=dict(
            username='totp_admin',
            password='admin'
        ), follow_redirects=True)

        with app.app_context():
            db = get_db()
            row = db.execute('SELECT totp_secret FROM users WHERE username = ?', ('totp_admin',)).fetchone()
        self.assertIsNotNone(row)
        code = pyotp.TOTP(row['totp_secret']).now()

        rv = self.client.post('/admin/change_password', data={
            'current_password': 'admin',
            'new_password': 'weakpass',
            'confirm_password': 'weakpass',
            'otp_code': code,
        }, follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'Password must include at least 10 characters.', rv.data)

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

    def test_admin_pages_do_not_ship_clipboard_blocker(self):
        rv = self.client.post('/login', data=dict(
            username='admin',
            password='admin'
        ), follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'data-user-role="admin"', rv.data)
        self.assertNotIn(b"document.addEventListener('copy', blockClipboard, true);", rv.data)

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

    def test_admin_totp_login_with_recovery_code(self):
        import json
        from werkzeug.security import generate_password_hash
        
        # Inject recovery codes for totp_admin user
        with app.app_context():
            db = get_db()
            raw_codes = ["testrec1", "testrec2"]
            hashed_codes = [generate_password_hash(c) for c in raw_codes]
            db.execute(
                'UPDATE users SET totp_recovery_codes = ? WHERE username = ?',
                (json.dumps(hashed_codes), 'totp_admin')
            )
            db.commit()

        # Step 1: Submit username/password to get to step 2 (requires OTP)
        app.config['TESTING'] = False
        try:
            first = self.client.post('/login', data=dict(
                username='totp_admin',
                password='admin'
            ), follow_redirects=False)
        finally:
            app.config['TESTING'] = True
        self.assertEqual(first.status_code, 200)

        # Step 2: Login using first recovery code
        second = self.client.post('/login', data=dict(
            otp_code="testrec1"
        ), follow_redirects=False)
        self.assertEqual(second.status_code, 302)
        self.assertIn('/patients', second.headers.get('Location', ''))

        # Verify that the recovery code was single-use and has been popped
        with app.app_context():
            db = get_db()
            row = db.execute('SELECT totp_recovery_codes FROM users WHERE username = ?', ('totp_admin',)).fetchone()
            current_codes = json.loads(row['totp_recovery_codes'])
            self.assertEqual(len(current_codes), 1)

    def test_inactivity_timeout_updates_last_activity(self):
        # Login
        self.client.post('/login', data=dict(
            username='admin',
            password='admin'
        ), follow_redirects=True)

        # Make a request
        with self.client as c:
            c.get('/patients')
            from flask import session
            self.assertIn('last_activity_at', session)
            self.assertIsNotNone(session['last_activity_at'])

    def test_inactivity_timeout_logs_out_user(self):
        # Login
        self.client.post('/login', data=dict(
            username='admin',
            password='admin'
        ), follow_redirects=True)

        # Simulate time passing by modifying the session
        with self.client.session_transaction() as sess:
            # Set to 10 minutes ago
            import datetime
            sess['last_activity_at'] = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - 600

        # Make a request
        with self.client as c:
            rv = c.get('/patients', follow_redirects=True)

            # Should be redirected to login and flashed message
            self.assertIn(b'Session expired due to inactivity. Please log in again.', rv.data)

            from flask import session
            # last_activity_at should be popped during logout process or next request unauthenticated
            self.assertNotIn('last_activity_at', session)

    def test_inactivity_timeout_ignored_for_static_files(self):
        # Login
        self.client.post('/login', data=dict(
            username='admin',
            password='admin'
        ), follow_redirects=True)

        # Simulate time passing by modifying the session
        with self.client.session_transaction() as sess:
            import datetime
            sess['last_activity_at'] = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - 600

        # Make a request to a static file (which shouldn't trigger timeout)
        # Even if the file doesn't exist, the before_request logic runs before the 404
        rv = self.client.get('/static/nonexistent.css', follow_redirects=False)

        # Should not redirect to login, should probably 404
        self.assertEqual(rv.status_code, 404)

        # Verify last_activity_at was NOT modified and user is not logged out
        with self.client as c:
            c.get('/static/nonexistent.css')
            from flask import session
            self.assertIn('last_activity_at', session)
            self.assertLess(session['last_activity_at'], int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - 500)

    def test_inactivity_timeout_unauthenticated(self):
        # Set a last_activity_at without being logged in
        with self.client.session_transaction() as sess:
            sess['last_activity_at'] = 12345

        with self.client as c:
            c.get('/login')
            from flask import session
            self.assertNotIn('last_activity_at', session)

    def test_path_traversal_in_download_file(self):
        app.config['TESTING'] = True
        self.client.post('/login', data=dict(username='admin', password='admin'), follow_redirects=True)

        # Test basic traversal attempt
        rv = self.client.get('/uploads/..%2F..%2F..%2F..%2F..%2F..%2F..%2Fetc%2Fpasswd')
        self.assertEqual(rv.status_code, 404)

        # Test the DB bypass / file mapping mechanism safely resolving the file instead of allowing traversal
        rv = self.client.get('/uploads/../../../../../../../etc/passwd')
        self.assertEqual(rv.status_code, 404)

    def test_public_booking_rate_limit(self):
        prev_enable = app.config.get('ENABLE_RATE_LIMIT_IN_TESTS')
        prev_max = app.config.get('PUBLIC_BOOKING_RATE_LIMIT_MAX')
        prev_window = app.config.get('PUBLIC_BOOKING_RATE_LIMIT_WINDOW_SECONDS')

        app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = True
        app.config['PUBLIC_BOOKING_RATE_LIMIT_MAX'] = 2
        app.config['PUBLIC_BOOKING_RATE_LIMIT_WINDOW_SECONDS'] = 60

        with app.app_context():
            db = get_db()
            db.execute('''
                CREATE TABLE IF NOT EXISTS availability (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    share_token TEXT,
                    status TEXT,
                    slot_date DATE,
                    slot_time TIME,
                    duration_minutes INTEGER
                )
            ''')
            db.commit()

        try:
            rv1 = self.client.post('/api/calendar/open/test-token/book', data={'name': 'A'})
            rv2 = self.client.post('/api/calendar/open/test-token/book', data={'name': 'A'})
            rv3 = self.client.post('/api/calendar/open/test-token/book', data={'name': 'A'})

            self.assertEqual(rv1.status_code, 409)
            self.assertEqual(rv2.status_code, 409)
            self.assertEqual(rv3.status_code, 429)
            self.assertIn('Retry-After', rv3.headers)
        finally:
            app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = prev_enable
            app.config['PUBLIC_BOOKING_RATE_LIMIT_MAX'] = prev_max
            app.config['PUBLIC_BOOKING_RATE_LIMIT_WINDOW_SECONDS'] = prev_window

    def test_security_headers_present(self):
        rv = self.client.get('/login')
        self.assertEqual(rv.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(rv.headers.get('X-Frame-Options'), 'SAMEORIGIN')
        self.assertEqual(rv.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
        self.assertIsNotNone(rv.headers.get('Content-Security-Policy'))


    def _seed_webhook_channel(self, channel_id='abc'):
        """Insert a patient with the given gdoc_watch_channel so webhook lookups succeed."""
        with app.app_context():
            db = get_db()
            try:
                db.execute(
                    "INSERT OR IGNORE INTO patients (name, status, gdoc_watch_channel) VALUES ('Test Patient', 'active', ?)",
                    (channel_id,)
                )
                db.commit()
            except Exception:
                pass

    def test_gdoc_webhook_requires_required_headers(self):
        self._seed_webhook_channel('abc')

        rv = self.client.post('/api/gdoc/webhook', headers={'X-Goog-Channel-ID': 'abc'})
        self.assertEqual(rv.status_code, 403)

        rv_ok = self.client.post('/api/gdoc/webhook', headers={
            'X-Goog-Channel-ID': 'abc',
            'X-Goog-Resource-State': 'sync'
        })
        self.assertEqual(rv_ok.status_code, 200)

    def test_gdoc_webhook_secret_when_configured(self):
        self._seed_webhook_channel('abc')

        prev_secret = app.config.get('GOOGLE_DOCS_WEBHOOK_SECRET')
        app.config['GOOGLE_DOCS_WEBHOOK_SECRET'] = 'test-secret'
        try:
            rv_bad = self.client.post('/api/gdoc/webhook', headers={
                'X-Goog-Channel-ID': 'abc',
                'X-Goog-Resource-State': 'sync'
            })
            self.assertEqual(rv_bad.status_code, 403)

            rv_ok = self.client.post('/api/gdoc/webhook', headers={
                'X-Goog-Channel-ID': 'abc',
                'X-Goog-Resource-State': 'sync',
                'X-Webhook-Secret': 'test-secret'
            })
            self.assertEqual(rv_ok.status_code, 200)
        finally:
            app.config['GOOGLE_DOCS_WEBHOOK_SECRET'] = prev_secret

    def test_admin_security_log_accessible_by_admin(self):
        rv = self.client.get('/admin/security-log')
        self.assertIn(rv.status_code, (200, 302))
        if rv.status_code == 200:
            self.assertIn(b'Security', rv.data)

    def test_admin_security_log_redirects_non_admin(self):
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT OR IGNORE INTO patients (id, name, status) VALUES (9991, 'TestPatient', 'ongoing')"
            )
            existing_user = db.execute(
                "SELECT id FROM users WHERE username = 'patient_sec_log_test'"
            ).fetchone()
            if not existing_user:
                from werkzeug.security import generate_password_hash
                db.execute(
                    "INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', 9991)",
                    ('patient_sec_log_test', generate_password_hash('TestPass123!')),
                )
            db.commit()

        with app.test_client() as client:
            client.post('/login', data={'username': 'patient_sec_log_test', 'password': 'TestPass123!'})
            rv = client.get('/admin/security-log')
            self.assertNotEqual(rv.status_code, 200)

    def test_registration_rate_limit_blocks_excess_registrations(self):
        prev_enable = app.config.get('ENABLE_RATE_LIMIT_IN_TESTS')
        prev_max = app.config.get('REGISTER_RATE_LIMIT_MAX')
        prev_window = app.config.get('REGISTER_RATE_LIMIT_WINDOW_SECONDS')
        app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = True
        app.config['REGISTER_RATE_LIMIT_MAX'] = 2
        app.config['REGISTER_RATE_LIMIT_WINDOW_SECONDS'] = 3600

        try:
            for _ in range(2):
                self.client.post('/register', data={'name': 'Rate Limit Test'})
            rv = self.client.post('/register', data={'name': 'Rate Limit Test'})
            self.assertEqual(rv.status_code, 429)
        finally:
            app.config['ENABLE_RATE_LIMIT_IN_TESTS'] = prev_enable
            app.config['REGISTER_RATE_LIMIT_MAX'] = prev_max
            app.config['REGISTER_RATE_LIMIT_WINDOW_SECONDS'] = prev_window

    def test_validate_patient_fields_rejects_bad_phone(self):
        from app import _validate_patient_fields
        errors = _validate_patient_fields('Test Patient', phone='not-a-phone')
        self.assertTrue(any('Phone' in e or 'phone' in e for e in errors))

    def test_validate_patient_fields_rejects_bad_email(self):
        from app import _validate_patient_fields
        errors = _validate_patient_fields('Test Patient', email='not-an-email')
        self.assertTrue(any('Email' in e or 'email' in e for e in errors))

    def test_validate_patient_fields_rejects_bad_birth_date(self):
        from app import _validate_patient_fields
        errors = _validate_patient_fields('Test Patient', birth_date='15/03/1990')
        self.assertTrue(any('Birth date' in e or 'date' in e.lower() for e in errors))

    def test_validate_patient_fields_accepts_valid_data(self):
        from app import _validate_patient_fields
        errors = _validate_patient_fields(
            'Test Patient', phone='+972-50-123-4567',
            birth_date='1990-03-15', email='test@example.com'
        )
        self.assertEqual(errors, [])

    # ── TOTP disable bumps session_version ──────────────────────────────
    def test_totp_disable_bumps_session_version(self):
        """Disabling TOTP must increment session_version to force re-login."""
        import pyotp
        with app.app_context():
            db = get_db()
            secret = pyotp.random_base32()
            db.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled, force_password_change) VALUES (?, ?, 'admin', 1, ?, 1, 0)",
                ('totp_disable_test', __import__('werkzeug.security', fromlist=['generate_password_hash']).generate_password_hash('admin'), secret),
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE username = 'totp_disable_test'").fetchone()
            original_version = user['session_version'] or 0

        with app.test_client() as client:
            # Authenticate admin (TESTING mode skips 2FA)
            client.post('/login', data={'username': 'totp_disable_test', 'password': 'admin'},
                        follow_redirects=True)
            rv = client.post('/admin/setup_authenticator',
                             data={'csrf_token': 'test', 'action': 'disable'},
                             follow_redirects=True)
            self.assertIn(rv.status_code, (200, 302))

        with app.app_context():
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE username = 'totp_disable_test'").fetchone()
            new_version = user['session_version'] or 0
            self.assertGreater(new_version, original_version,
                               'session_version must increment when TOTP is disabled')
            self.assertEqual(user['totp_enabled'], 0)
            self.assertIsNone(user['totp_secret'])

    # ── CSV export ──────────────────────────────────────────────────────
    def test_security_log_export_requires_admin(self):
        """Non-admin users must not access the CSV export."""
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT OR IGNORE INTO patients (id, name, status) VALUES (9992, 'ExportTestPatient', 'ongoing')"
            )
            db.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, role, is_active, patient_id) VALUES (?, ?, 'patient', 1, 9992)",
                ('export_test_patient', __import__('werkzeug.security', fromlist=['generate_password_hash']).generate_password_hash('TestPass123!')),
            )
            db.commit()

        with app.test_client() as client:
            client.post('/login', data={'username': 'export_test_patient', 'password': 'TestPass123!'},
                        follow_redirects=True)
            rv = client.get('/admin/security-log/export')
            self.assertNotEqual(rv.status_code, 200,
                                'Patient role must not access security log export')

    def test_security_log_export_returns_csv_for_admin(self):
        """Admin accessing CSV export gets text/csv content-type."""
        # Seed one auth event so output is non-empty
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO audit_logs (patient_id, action, details) VALUES (NULL, 'auth_login_password_failed', 'username=test')"
            )
            db.commit()

        # Log in as admin (TESTING=True bypasses 2FA)
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'},
                         follow_redirects=True)
        rv = self.client.get('/admin/security-log/export')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('text/csv', rv.content_type)
        self.assertIn(b'action', rv.data)   # header row
        self.assertIn(b'auth_login_password_failed', rv.data)

if __name__ == '__main__':
    unittest.main()
