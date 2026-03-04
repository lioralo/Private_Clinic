import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import pyotp
import subprocess

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = os.environ.get('SECRET_KEY', 'dev')
csrf = CSRFProtect(app)
DATABASE = 'clinic.db'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, role, patient_id=None):
        self.id = id
        self.username = username
        self.role = role
        self.patient_id = patient_id

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        return User(user['id'], user['username'], user['role'], user['patient_id'])
    return None

@app.context_processor
def inject_global_vars():
    unread_messages = 0
    if current_user.is_authenticated:
        db = get_db()
        # If admin, unread messages sent to admin (recipient_id is admin id or None? Let's assume we find admin ID or use None convention for admin inbox if we did that, but schema says recipient_id is INTEGER. In contact_admin we set recipient_id to admin user ID.)
        
        # If I am admin, I want to see messages sent TO me.
        # If I am patient, I want to see messages sent TO me.
        
        unread_messages = db.execute('SELECT COUNT(*) as count FROM messages WHERE recipient_id = ? AND is_read = 0', (current_user.id,)).fetchone()['count']
    
    return dict(unread_messages=unread_messages)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        database = app.config.get('DATABASE', DATABASE)
        db = g._database = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    database = app.config.get('DATABASE', DATABASE)
    # Always run schema to ensure tables exist
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

        # Schema migrations
        try:
            db.execute('SELECT secret_token FROM users LIMIT 1')
        except sqlite3.OperationalError:
            print("Migrating database: Adding secret_token column to users table...")
            db.execute('ALTER TABLE users ADD COLUMN secret_token TEXT')
            db.commit()

        try:
            db.execute('SELECT background FROM patients LIMIT 1')
        except sqlite3.OperationalError:
            print("Migrating database: Adding background and treatment_info columns to patients table...")
            db.execute('ALTER TABLE patients ADD COLUMN background TEXT')
            db.execute('ALTER TABLE patients ADD COLUMN treatment_info TEXT')
            db.commit()

        # Recurring Slots Table
        db.execute('''
            CREATE TABLE IF NOT EXISTS slots_recurring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                weekday INTEGER NOT NULL, -- 0 (Mon) to 6 (Sun)
                time TIME NOT NULL,
                is_blocked BOOLEAN DEFAULT 0
            )
        ''')
        db.commit()

        # Check if admin exists
        admin = db.execute("SELECT * FROM users WHERE role = 'admin'").fetchone()
        if not admin:
            print("Creating default admin user...")
            hashed_pw = generate_password_hash('admin')
            db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                       ('admin', hashed_pw, 'admin'))
            db.commit()
            print("Admin user created (username: admin, password: admin).")

        print(f"Initialized the database at {database}.")

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
        print(f"Created upload folder: {app.config['UPLOAD_FOLDER']}")

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('patients'))
        elif current_user.role == 'patient':
            return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        otp = request.form.get('otp')
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            if not user['is_active']:
                 flash('Account is disabled. Contact administrator.')
                 return render_template('login.html')

            # 2FA for Admin
            if user['role'] == 'admin':
                if not user['secret_token']:
                    # First time setup for admin 2FA
                    # Generate secret
                    secret = pyotp.random_base32()
                    db.execute('UPDATE users SET secret_token = ? WHERE id = ?', (secret, user['id']))
                    db.commit()
                    
                    # Generate provisioning URI for QR Code
                    totp = pyotp.TOTP(secret)
                    provisioning_uri = totp.provisioning_uri(name=user['username'], issuer_name="Private Clinic")
                    
                    # Show QR code setup page
                    return render_template('setup_2fa.html', secret=secret, uri=provisioning_uri, user_id=user['id'])
                
                if not otp:
                    flash('Enter 2FA Code')
                    return render_template('login.html', require_otp=True, username=username)
                
                totp = pyotp.TOTP(user['secret_token'])
                if not totp.verify(otp):
                    flash('Invalid 2FA Code')
                    return render_template('login.html', require_otp=True, username=username)

            user_obj = User(user['id'], user['username'], user['role'], user['patient_id'])
            login_user(user_obj)
            if user['role'] == 'admin':
                return redirect(url_for('patients'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')

    return render_template('login.html')

@app.route('/admin/backup', methods=('POST',))
@login_required
def backup_now():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    try:
        # Run the backup script
        subprocess.Popen(['python', 'backup_db.py'])
        flash('Backup process started.')
        log_audit("Triggered manual database backup")
    except Exception as e:
        flash(f'Error starting backup: {e}')
    
    return redirect(url_for('revenue')) # Or wherever the button is

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/patients')
@login_required
def patients():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))

    status = request.args.get('status', 'ongoing')
    db = get_db()
    patients = db.execute('SELECT * FROM patients WHERE status = ?', (status,)).fetchall()
    
    # Get reminders for admin dashboard
    reminders = send_appointment_reminders()
    
    return render_template('index.html', patients=patients, status=status, reminders=reminders)

@app.route('/add_patient', methods=('GET', 'POST'))
@login_required
def add_patient():
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form['name']
        status = request.form['status']
        email = request.form.get('email')
        phone = request.form.get('phone')

        if not name:
            flash('Name is required!')
        else:
            db = get_db()
            db.execute('INSERT INTO patients (name, status, email, phone) VALUES (?, ?, ?, ?)',
                       (name, status, email, phone))
            db.commit()
            return redirect(url_for('patients', status=status))

    return render_template('add_patient.html')

@app.route('/patient/<int:patient_id>')
@login_required
def patient_detail(patient_id):
    if current_user.role != 'admin':
         # Patients can only see their own profile? No, this view is the Admin view of the patient.
         # The patient dashboard is separate.
         flash('Access denied.')
         return redirect(url_for('dashboard'))

    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if patient is None:
        return "Patient not found", 404

    # Fetch user account if exists
    user = db.execute('SELECT * FROM users WHERE patient_id = ?', (patient_id,)).fetchone()

    notes_raw = db.execute('SELECT * FROM notes WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    notes = [dict(row) for row in notes_raw]
    
    files = db.execute('SELECT * FROM files WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    receipts = db.execute('SELECT * FROM receipts WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    appointments = db.execute('SELECT * FROM appointments WHERE patient_id = ? ORDER BY appointment_date DESC, appointment_time DESC', (patient_id,)).fetchall()
    goals = db.execute('SELECT * FROM goals WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()

    return render_template('patient_detail.html', patient=patient, notes=notes, files=files, receipts=receipts, user=user, appointments=appointments, goals=goals)

@app.route('/patient/<int:patient_id>/add_note', methods=('POST',))
@login_required
def add_note(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form.get('content')
    session_number = request.form.get('session_number')
    patient_appearance = request.form.get('patient_appearance')
    key_topics = request.form.get('key_topics')
    
    db = get_db()
    
    if content:
        # 1. Insert Note
        cursor = db.execute(
            'INSERT INTO notes (patient_id, content, session_number, patient_appearance, key_topics) VALUES (?, ?, ?, ?, ?)', 
            (patient_id, content, session_number, patient_appearance, key_topics)
        )
        note_id = cursor.lastrowid
        db.commit()
        log_audit(f"Created note #{session_number} for patient ID {patient_id}")

        # 2. Handle File Upload within Note
        file = request.files.get('note_file')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Add to files table (linked to note)
            db.execute('INSERT INTO files (patient_id, filename, note_id) VALUES (?, ?, ?)', 
                       (patient_id, filename, note_id))
            db.commit()
            log_audit(f"Uploaded file {filename} attached to note {note_id}")

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/note/<int:note_id>/edit', methods=('POST',))
@login_required
def edit_note(note_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form.get('content')
    session_number = request.form.get('session_number')
    patient_appearance = request.form.get('patient_appearance')
    key_topics = request.form.get('key_topics')
    
    db = get_db()
    note = db.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
    
    if note:
        db.execute(
            'UPDATE notes SET content = ?, session_number = ?, patient_appearance = ?, key_topics = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (content, session_number, patient_appearance, key_topics, note_id)
        )
        db.commit()
        log_audit(f"Edited note ID {note_id}")
        return redirect(url_for('patient_detail', patient_id=note['patient_id']))
    
    return "Note not found", 404

@app.route('/patient/<int:patient_id>/add_goal', methods=('POST',))
@login_required
def add_goal(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    
    description = request.form['description']
    if description:
        db = get_db()
        db.execute('INSERT INTO goals (patient_id, description) VALUES (?, ?)', (patient_id, description))
        db.commit()
        log_audit(f"Added goal for patient ID {patient_id}: {description}")
    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/goal/<int:goal_id>/toggle_status', methods=('POST',))
@login_required
def toggle_goal_status(goal_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    goal = db.execute('SELECT * FROM goals WHERE id = ?', (goal_id,)).fetchone()
    if goal:
        new_status = 'achieved' if goal['status'] == 'active' else 'active'
        db.execute('UPDATE goals SET status = ? WHERE id = ?', (new_status, goal_id))
        db.commit()
        log_audit(f"Updated goal ID {goal_id} status to {new_status}")
        return redirect(url_for('patient_detail', patient_id=goal['patient_id']))
    return "Goal not found", 404

@app.route('/patient/<int:patient_id>/add_file', methods=('POST',))
@login_required
def add_file(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('patient_detail', patient_id=patient_id))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('patient_detail', patient_id=patient_id))
    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        db = get_db()
        db.execute('INSERT INTO files (patient_id, filename) VALUES (?, ?)', (patient_id, filename))
        db.commit()
        log_audit(f"Uploaded file for patient ID {patient_id}: {filename}")
    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/patient/<int:patient_id>/add_receipt', methods=('POST',))
@login_required
def add_receipt(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    amount = request.form['amount']
    description = request.form['description']
    if amount:
        db = get_db()
        db.execute('INSERT INTO receipts (patient_id, amount, description) VALUES (?, ?, ?)', (patient_id, amount, description))
        db.commit()
    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/uploads/<name>')
@login_required
def download_file(name):
    # Check if user has access to this file.
    # For now, allow admin and the patient who owns the file.
    # But finding the owner of a file from filename is hard if filenames aren't unique or mapped.
    # The 'files' table maps filename to patient_id.

    db = get_db()
    file_record = db.execute('SELECT patient_id FROM files WHERE filename = ?', (name,)).fetchone()

    if not file_record:
        # Maybe it's not in DB (dummy file). Allow admin.
        if current_user.role == 'admin':
             return send_from_directory(app.config['UPLOAD_FOLDER'], name)
        else:
             return "File not found or access denied", 403

    if current_user.role == 'admin' or (current_user.role == 'patient' and current_user.patient_id == file_record['patient_id']):
        log_audit(f"Downloaded file: {name}")
        return send_from_directory(app.config['UPLOAD_FOLDER'], name)

    return "Access denied", 403

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'patient':
        return redirect(url_for('patients'))

    patient_id = current_user.patient_id
    db = get_db()

    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    appointments = db.execute('SELECT * FROM appointments WHERE patient_id = ? ORDER BY appointment_date DESC, appointment_time DESC', (patient_id,)).fetchall()
    receipts = db.execute('SELECT * FROM receipts WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    files = db.execute('SELECT * FROM files WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()

    # Calculate debt
    total_cost = db.execute('SELECT SUM(cost) as total FROM appointments WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    total_paid = db.execute('SELECT SUM(amount) as total FROM receipts WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    balance = total_cost - total_paid

    # Resources (Global or assigned to patient)
    resources = db.execute('SELECT * FROM resources WHERE is_global = 1 OR patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()

    return render_template('dashboard.html', patient=patient, appointments=appointments, receipts=receipts, files=files, balance=balance, resources=resources)

@app.route('/contact_admin', methods=('POST',))
@login_required
def contact_admin():
    if current_user.role != 'patient':
        return "Unauthorized", 403

    content = request.form['content']
    if content:
        db = get_db()
        # For now, we'll store messages in a 'messages' table or just notes if simpler?
        # The schema has a 'messages' table.
        # sender_id is current_user.id. Recipient? Let's say Admin (which we don't have a specific ID for easily, unless we look it up).
        # Or we can just use NULL for recipient to mean "System/Admin".

        # Check if admin user exists to get ID?
        admin = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        recipient_id = admin['id'] if admin else None

        db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                   (current_user.id, recipient_id, content))
        db.commit()
        flash('Message sent to your therapist.')

    return redirect(url_for('dashboard'))

@app.route('/patient/<int:patient_id>/edit', methods=('GET', 'POST'))
@login_required
def edit_patient(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if patient is None:
        return "Patient not found", 404

    if request.method == 'POST':
        name = request.form['name']
        status = request.form['status']
        email = request.form.get('email')
        phone = request.form.get('phone')

        if not name:
            flash('Name is required!')
        else:
            db.execute('UPDATE patients SET name = ?, status = ?, email = ?, phone = ? WHERE id = ?',
                       (name, status, email, phone, patient_id))
            db.commit()
            flash('Patient updated successfully.')
            return redirect(url_for('patient_detail', patient_id=patient_id))

    return render_template('edit_patient.html', patient=patient)

@app.route('/patient/<int:patient_id>/access', methods=('POST',))
@login_required
def manage_access(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    username = request.form['username']
    password = request.form['password']

    if not username or not password:
        flash('Username and password are required.')
        return redirect(url_for('patient_detail', patient_id=patient_id))

    db = get_db()

    # Check if user exists for this patient
    existing_user = db.execute('SELECT * FROM users WHERE patient_id = ?', (patient_id,)).fetchone()

    hashed_pw = generate_password_hash(password)

    if existing_user:
        try:
            db.execute('UPDATE users SET username = ?, password_hash = ? WHERE id = ?',
                       (username, hashed_pw, existing_user['id']))
            db.commit()
            flash('User access updated.')
        except sqlite3.IntegrityError:
             flash('Username already taken.')
    else:
        try:
            db.execute('INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, ?, ?)',
                       (username, hashed_pw, 'patient', patient_id))
            db.commit()
            flash('User access granted.')
        except sqlite3.IntegrityError:
            flash('Username already taken.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/patient/<int:patient_id>/toggle_access', methods=('POST',))
@login_required
def toggle_access(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE patient_id = ?', (patient_id,)).fetchone()
    if user:
        new_status = not user['is_active']
        db.execute('UPDATE users SET is_active = ? WHERE id = ?', (new_status, user['id']))
        db.commit()
        flash(f"Access {'enabled' if new_status else 'disabled'}.")
    else:
        flash('No user account found for this patient.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/patient/<int:patient_id>/add_appointment', methods=('POST',))
@login_required
def add_appointment(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    date = request.form['date']
    time = request.form['time']
    cost = request.form.get('cost', 0)

    if date and time:
        db = get_db()
        db.execute('INSERT INTO appointments (patient_id, appointment_date, appointment_time, cost) VALUES (?, ?, ?, ?)',
                   (patient_id, date, time, cost))
        db.commit()
        flash('Appointment added.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/appointment/<int:appointment_id>/delete', methods=('POST',))
@login_required
def delete_appointment(appointment_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    appt = db.execute('SELECT patient_id FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if appt:
        db.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))
        db.commit()
        flash('Appointment deleted.')
        return redirect(url_for('patient_detail', patient_id=appt['patient_id']))

    return "Appointment not found", 404

@app.route('/admin/revenue')
@login_required
def revenue():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))

    db = get_db()
    
    # Total revenue from receipts
    total_revenue = db.execute('SELECT SUM(amount) as total FROM receipts').fetchone()['total'] or 0
    
    # Pending debt: sum(appointments.cost) - sum(receipts.amount)
    total_cost = db.execute('SELECT SUM(cost) as total FROM appointments').fetchone()['total'] or 0
    pending_debt = total_cost - total_revenue
    
    # Monthly growth trend (last 6 months for example, or all)
    # Simple aggregation by month
    monthly_data = db.execute('''
        SELECT strftime('%Y-%m', created_at) as month, SUM(amount) as total
        FROM receipts
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    ''').fetchall()
    
    monthly_growth = [(row['month'], row['total']) for row in monthly_data]

    # Current month revenue
    current_month_str = datetime.now().strftime('%Y-%m')
    monthly_revenue = next((amount for month, amount in monthly_growth if month == current_month_str), 0)

    current_month_name = datetime.now().strftime('%B %Y')

    return render_template('admin_revenue.html', 
                           total_revenue=total_revenue, 
                           pending_debt=pending_debt, 
                           monthly_growth=monthly_growth,
                           monthly_revenue=monthly_revenue,
                           current_month=current_month_name)

@app.route('/patient/<int:patient_id>/update_info', methods=('POST',))
@login_required
def update_patient_info(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    
    background = request.form.get('background')
    treatment_info = request.form.get('treatment_info')
    
    db = get_db()
    db.execute('UPDATE patients SET background = ?, treatment_info = ? WHERE id = ?',
               (background, treatment_info, patient_id))
    db.commit()
    flash('Patient information updated.')
    return redirect(url_for('patient_detail', patient_id=patient_id))

# Recurring Slots Management
@app.route('/admin/slots', methods=('GET', 'POST'))
@login_required
def manage_slots():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))

    db = get_db()
    slots = db.execute('SELECT * FROM slots_recurring ORDER BY weekday ASC, time ASC').fetchall()
    return render_template('manage_slots.html', slots=slots)

@app.route('/api/slots')
@login_required
def get_slots():
    db = get_db()
    
    # Define time range: current week and next 3 weeks
    start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=28)
    
    # 1. Fetch recurring slots
    recurring = db.execute('SELECT * FROM slots_recurring').fetchall()
    
    # 2. Fetch all appointments in this range to mark booked
    appts = db.execute('SELECT * FROM appointments WHERE appointment_date >= ? AND appointment_date <= ?',
                       (start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'))).fetchall()
    booked_set = set()
    for a in appts:
        # Match format with generated slot: YYYY-MM-DDTHH:MM
        booked_set.add(f"{a['appointment_date']}T{a['appointment_time'][:5]}")
        
    events = []
    curr = start_dt
    while curr < end_dt:
        # curr.weekday() returns 0 for Monday, 6 for Sunday
        weekday = curr.weekday()
        day_slots = [s for s in recurring if s['weekday'] == weekday]
        
        for s in day_slots:
            # s['time'] is 'HH:MM'
            start_iso = f"{curr.strftime('%Y-%m-%d')}T{s['time']}"
            is_booked = start_iso in booked_set
            
            # For end time, assume 50 min session if not specified, or just add 1 hour
            dt_start = datetime.strptime(start_iso, '%Y-%m-%dT%H:%M')
            dt_end = dt_start + timedelta(hours=1)
            end_iso = dt_end.strftime('%Y-%m-%dT%H:%M')
            
            title = "Open Slot"
            color = "#28a745" # Green
            is_blocked = bool(s['is_blocked'])
            
            if is_blocked:
                title = "Blocked"
                color = "#6c757d" # Gray
            elif is_booked:
                # Find the patient name for admin
                appt = next((a for a in appts if f"{a['appointment_date']}T{a['appointment_time'][:5]}" == start_iso), None)
                if current_user.role == 'admin':
                    patient = db.execute('SELECT name FROM patients WHERE id = ?', (appt['patient_id'],)).fetchone() if appt else None
                    title = f"Booked: {patient['name'] if patient else 'Patient'}"
                    color = "#dc3545" # Red
                else:
                    if appt and appt['patient_id'] == current_user.patient_id:
                        title = "My Appointment"
                        color = "#007bff" # Blue
                    else:
                        # For other patients, hide booked slots or show as unavailable
                        continue
            
            events.append({
                'id': f"rec_{s['id']}_{curr.strftime('%Y%m%d')}",
                'title': title,
                'start': start_iso,
                'end': end_iso,
                'backgroundColor': color,
                'borderColor': color,
                'textColor': '#ffffff',
                'extendedProps': {
                    'is_booked': is_booked,
                    'is_blocked': is_blocked,
                    'recurring_id': s['id']
                }
            })
            
        curr += timedelta(days=1)
        
    return jsonify(events)

@app.route('/admin/add_slot', methods=('POST',))
@login_required
def add_slot():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    weekday = int(request.form['weekday'])
    time = request.form['time']
    is_blocked = 1 if 'is_blocked' in request.form else 0
    
    if time:
        db = get_db()
        db.execute('INSERT INTO slots_recurring (weekday, time, is_blocked) VALUES (?, ?, ?)', (weekday, time, is_blocked))
        db.commit()
        log_audit(f"Created recurring slot: Day {weekday} at {time}")
        flash('Recurring slot created.')
    
    return redirect(url_for('manage_slots'))

@app.route('/admin/delete_slot/<int:slot_id>', methods=('POST',))
@login_required
def delete_slot(slot_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    
    db = get_db()
    db.execute('DELETE FROM slots_recurring WHERE id = ?', (slot_id,))
    db.commit()
    log_audit(f"Deleted recurring slot ID {slot_id}")
    flash('Recurring slot deleted.')
    return redirect(url_for('manage_slots'))

@app.route('/request_slot', methods=('POST',))
@login_required
def request_slot():
    if current_user.role != 'patient':
        return "Unauthorized", 403

    start_iso = request.form.get('start') # 'YYYY-MM-DDTHH:MM'
    if not start_iso:
        flash('Invalid slot selection.')
        return redirect(url_for('dashboard'))

    try:
        dt = datetime.strptime(start_iso, '%Y-%m-%dT%H:%M')
        date_str = dt.strftime('%Y-%m-%d')
        time_str = dt.strftime('%H:%M')
        
        db = get_db()
        # Check if already booked
        existing = db.execute('SELECT id FROM appointments WHERE appointment_date = ? AND appointment_time = ?', (date_str, time_str)).fetchone()
        if existing:
            flash('This slot was just booked by someone else.')
        else:
            db.execute('INSERT INTO appointments (patient_id, appointment_date, appointment_time, status) VALUES (?, ?, ?, ?)',
                       (current_user.patient_id, date_str, time_str, 'scheduled'))
            db.commit()
            log_audit(f"Patient {current_user.patient_id} booked slot at {start_iso}")
            flash('Appointment booked successfully.')
    except ValueError:
         flash('Error processing date time format.')

    return redirect(url_for('dashboard'))

# Resources Management
@app.route('/admin/resources', methods=('GET',))
@login_required
def manage_resources():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))

    db = get_db()
    resources = db.execute('SELECT * FROM resources ORDER BY created_at DESC').fetchall()
    patients = db.execute('SELECT id, name FROM patients WHERE status = "ongoing"').fetchall()
    return render_template('manage_resources.html', resources=resources, patients=patients)

@app.route('/admin/add_resource', methods=('POST',))
@login_required
def add_resource():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    title = request.form['title']
    file_path = request.form['file_path']
    patient_id = request.form.get('patient_id') # Can be empty string
    
    is_global = True if not patient_id else False
    pid = int(patient_id) if patient_id else None

    if title and file_path:
        db = get_db()
        db.execute('INSERT INTO resources (title, file_path, is_global, patient_id) VALUES (?, ?, ?, ?)',
                   (title, file_path, is_global, pid))
        db.commit()
        log_audit(f"Added resource: {title}")
        flash('Resource added.')

    return redirect(url_for('manage_resources'))

@app.route('/admin/delete_resource/<int:resource_id>', methods=('POST',))
@login_required
def delete_resource(resource_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    db.execute('DELETE FROM resources WHERE id = ?', (resource_id,))
    db.commit()
    log_audit(f"Deleted resource ID {resource_id}")
    flash('Resource deleted.')
    return redirect(url_for('manage_resources'))

@app.route('/messages')
@login_required
def messages():
    db = get_db()
    
    # Clustering logic:
    # If admin: show all conversations grouped by user
    # If patient: show their own conversation thread with admin
    
    if current_user.role == 'admin':
        # Get all users who have exchanged messages with admin
        conversations = db.execute('''
            SELECT u.id as user_id, u.username, u.role, 
            MAX(m.timestamp) as last_message_time,
            (SELECT COUNT(*) FROM messages WHERE sender_id = u.id AND recipient_id = ? AND is_read = 0) as unread_count
            FROM users u
            JOIN messages m ON (m.sender_id = u.id OR m.recipient_id = u.id)
            WHERE u.id != ?
            GROUP BY u.id
            ORDER BY last_message_time DESC
        ''', (current_user.id, current_user.id)).fetchall()
        
        selected_user_id = request.args.get('user_id', type=int)
        thread_messages = []
        if selected_user_id:
            thread_messages = db.execute('''
                SELECT m.*, u.username as sender_name 
                FROM messages m 
                JOIN users u ON m.sender_id = u.id 
                WHERE (m.sender_id = ? AND m.recipient_id = ?) 
                   OR (m.sender_id = ? AND m.recipient_id = ?)
                ORDER BY m.timestamp ASC
            ''', (selected_user_id, current_user.id, current_user.id, selected_user_id)).fetchall()
            
            # Mark as read
            db.execute('UPDATE messages SET is_read = 1 WHERE sender_id = ? AND recipient_id = ?', (selected_user_id, current_user.id))
            db.commit()

        return render_template('messages.html', conversations=conversations, thread_messages=thread_messages, selected_user_id=selected_user_id)
    
    else:
        # Patient view: just their thread with admin
        admin = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        thread_messages = []
        if admin:
            thread_messages = db.execute('''
                SELECT m.*, u.username as sender_name 
                FROM messages m 
                JOIN users u ON m.sender_id = u.id 
                WHERE (m.sender_id = ? AND m.recipient_id = ?) 
                   OR (m.sender_id = ? AND m.recipient_id = ?)
                ORDER BY m.timestamp ASC
            ''', (current_user.id, admin['id'], admin['id'], current_user.id)).fetchall()
            
            # Mark as read
            db.execute('UPDATE messages SET is_read = 1 WHERE sender_id = ? AND recipient_id = ?', (admin['id'], current_user.id))
            db.commit()

        return render_template('messages.html', thread_messages=thread_messages)

@app.route('/messages/send', methods=('POST',))
@login_required
def send_message():
    recipient_id = request.form.get('recipient_id', type=int)
    content = request.form.get('content')
    thread_id = request.form.get('thread_id', type=int)
    
    if not recipient_id and current_user.role != 'admin':
        # Patients always send to admin
        db = get_db()
        admin = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        recipient_id = admin['id'] if admin else None

    if recipient_id and content:
        db = get_db()
        db.execute('INSERT INTO messages (sender_id, recipient_id, content, thread_id) VALUES (?, ?, ?, ?)',
                   (current_user.id, recipient_id, content, thread_id))
        db.commit()
        
    return redirect(url_for('messages', user_id=recipient_id if current_user.role == 'admin' else None))

@app.route('/api/patient/<int:patient_id>/progress')
@login_required
def patient_progress_data(patient_id):
    if current_user.role != 'admin' and current_user.patient_id != patient_id:
        return "Unauthorized", 403
    
    db = get_db()
    # 1. Attendance over last 6 months
    attendance = db.execute('''
        SELECT strftime('%Y-%m', appointment_date) as month, COUNT(*) as count 
        FROM appointments 
        WHERE patient_id = ? AND status = 'completed'
        GROUP BY month ORDER BY month DESC LIMIT 6
    ''', (patient_id,)).fetchall()
    
    # 2. Key topics frequency (simple extraction from notes)
    notes = db.execute('SELECT key_topics FROM notes WHERE patient_id = ?', (patient_id,)).fetchall()
    topic_counts = {}
    for n in notes:
        if n['key_topics']:
            for topic in n['key_topics'].split(','):
                t = topic.strip().capitalize()
                topic_counts[t] = topic_counts.get(t, 0) + 1
    
    return jsonify({
        'attendance': [{'month': r['month'], 'count': r['count']} for r in reversed(attendance)],
        'topics': [{'topic': k, 'count': v} for k, v in topic_counts.items()]
    })

def send_appointment_reminders():
    db = get_db()
    # Find appointments in next 24 hours
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    
    reminders = db.execute('''
        SELECT a.*, p.name as patient_name, p.phone, p.email 
        FROM appointments a 
        JOIN patients p ON a.patient_id = p.id 
        WHERE a.appointment_date IN (?, ?) AND a.status = 'scheduled'
    ''', (today, tomorrow)).fetchall()
    
    return reminders

def log_audit(action, user_id=None):
    if user_id is None and current_user.is_authenticated:
        user_id = current_user.id
    
    db = get_db()
    db.execute('INSERT INTO audit_logs (user_id, action) VALUES (?, ?)', (user_id, action))
    db.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=False)
