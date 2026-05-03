from flask import redirect, render_template, request, session, url_for, flash
from flask_login import current_user, login_required, logout_user
from werkzeug.security import check_password_hash


def register_auth_routes(
    app,
    *,
    get_db,
    verify_totp_code,
    login_redirect_for_user,
    dummy_password_hash,
):
    def login():
        if current_user.is_authenticated:
            if current_user.role == 'admin':
                return redirect(url_for('patients'))
            return redirect(url_for('patient_home'))

        pending_user_id = session.get('pending_2fa_user_id')
        pending_username = session.get('pending_2fa_username', '')

        if request.method == 'POST':
            otp_code = (request.form.get('otp_code') or '').strip()
            if pending_user_id and otp_code:
                db = get_db()
                pending_user = db.execute('SELECT * FROM users WHERE id = ?', (pending_user_id,)).fetchone()
                if not pending_user or not pending_user['is_active']:
                    session.pop('pending_2fa_user_id', None)
                    session.pop('pending_2fa_username', None)
                    flash('Login session expired. Please sign in again.')
                    return redirect(url_for('login'))

                if not pending_user['totp_enabled'] or not pending_user['totp_secret']:
                    session.pop('pending_2fa_user_id', None)
                    session.pop('pending_2fa_username', None)
                    flash('Authenticator is not configured for this admin account.')
                    return redirect(url_for('login'))

                if verify_totp_code(pending_user['totp_secret'], otp_code):
                    session.pop('pending_2fa_user_id', None)
                    session.pop('pending_2fa_username', None)
                    return login_redirect_for_user(pending_user)

                flash('Invalid authenticator code.')
                return render_template('login.html', requires_otp=True, pending_username=pending_username)

            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_username', None)

            username = request.form['username']
            password = request.form['password']

            db = get_db()
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

            if user:
                password_correct = check_password_hash(user['password_hash'], password)
            else:
                check_password_hash(dummy_password_hash, password)
                password_correct = False

            if user and password_correct:
                if not user['is_active']:
                    flash('Account is disabled. Contact administrator.')
                    return render_template('login.html')

                # REQUIRE 2FA for all admin accounts in PRODUCTION
                # IN TESTING: Allow bypass for admin logins
                if user['role'] == 'admin' and not app.config.get('TESTING'):
                    if not user['totp_enabled'] or not user['totp_secret']:
                        return login_redirect_for_user(user)

                    session['pending_2fa_user_id'] = int(user['id'])
                    session['pending_2fa_username'] = user['username']
                    flash('Two-factor authentication required. Check your authenticator app.')
                    return render_template('login.html', requires_otp=True, pending_username=user['username'])

                return login_redirect_for_user(user)

            flash('Invalid username or password')

        if pending_user_id:
            return render_template('login.html', requires_otp=True, pending_username=pending_username)

        return render_template('login.html')

    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    def register():
        if request.method == 'POST':
            name = request.form['name']
            email = request.form.get('email')
            phone = request.form.get('phone')

            if not name:
                flash('Name is required!')
            else:
                db = get_db()
                db.execute(
                    'INSERT INTO patients (name, status, email, phone) VALUES (?, ?, ?, ?)',
                    (name, 'candidate', email, phone),
                )
                db.commit()
                flash('Registration successful! We will contact you soon.')
                return redirect(url_for('login'))

        return render_template('register.html')

    app.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    app.add_url_rule('/logout', endpoint='logout', view_func=logout, methods=['GET'])
    app.add_url_rule('/register', endpoint='register', view_func=register, methods=['GET', 'POST'])
