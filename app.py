import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, jsonify
from werkzeug.utils import secure_filename
import datetime
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

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
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            if not user['is_active']:
                 flash('Account is disabled. Contact administrator.')
                 return render_template('login.html')

            user_obj = User(user['id'], user['username'], user['role'], user['patient_id'])
            login_user(user_obj)
            if user['role'] == 'admin':
                return redirect(url_for('patients'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')

    return render_template('login.html')

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
    return render_template('index.html', patients=patients, status=status)

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

    notes = db.execute('SELECT * FROM notes WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    files = db.execute('SELECT * FROM files WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    receipts = db.execute('SELECT * FROM receipts WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    appointments = db.execute('SELECT * FROM appointments WHERE patient_id = ? ORDER BY appointment_date DESC, appointment_time DESC', (patient_id,)).fetchall()

    # Get messages
    messages = []
    if user:
        messages = db.execute('''
            SELECT * FROM messages
            WHERE sender_id = ? OR recipient_id = ?
            ORDER BY timestamp ASC
        ''', (user['id'], user['id'])).fetchall()

    return render_template('patient_detail.html', patient=patient, notes=notes, files=files, receipts=receipts, user=user, appointments=appointments, messages=messages)

@app.route('/patient/<int:patient_id>/add_note', methods=('POST',))
@login_required
def add_note(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form['content']
    if content:
        db = get_db()
        db.execute('INSERT INTO notes (patient_id, content) VALUES (?, ?)', (patient_id, content))
        db.commit()
    return redirect(url_for('patient_detail', patient_id=patient_id))

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
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        db = get_db()
        db.execute('INSERT INTO files (patient_id, filename) VALUES (?, ?)', (patient_id, filename))
        db.commit()

        if filename.endswith('.docx'):
            # Attempt to parse document
            import re
            from docx import Document

            try:
                doc = Document(filepath)
                text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

                # Look for meeting number, date, content
                meeting_no_match = re.search(r'(?:Meeting #|פגישה מספר)[:\s]*(\w+)', text, re.IGNORECASE)
                date_match = re.search(r'(?:Date|תאריך)[:\s]*([\d\./\-]+)', text, re.IGNORECASE)
                content_match = re.search(r'(?:Content|תוכן)[:\s]*(.*)', text, re.IGNORECASE | re.DOTALL)

                meeting_no = meeting_no_match.group(1).strip() if meeting_no_match else None
                date_str = date_match.group(1).strip() if date_match else None
                content = content_match.group(1).strip() if content_match else text # default to all text

                needs_review = False
                if not meeting_no or not date_str:
                    needs_review = True

                # Check for existing appointment
                appointment_id = None
                if date_str:
                    try:
                        # Try parsing Israeli format DD/MM/YYYY or DD.MM.YYYY
                        parsed_date = None
                        if '.' in date_str or '/' in date_str:
                            parts = re.split(r'[\./]', date_str)
                            if len(parts) == 3:
                                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                                if y < 100:
                                    y += 2000
                                parsed_date = f"{y:04d}-{m:02d}-{d:02d}"
                        if not parsed_date:
                            # Try YYYY-MM-DD
                            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                                parsed_date = date_str

                        if parsed_date:
                            appt = db.execute('SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ?', (patient_id, parsed_date)).fetchone()
                            if appt:
                                appointment_id = appt['id']
                    except Exception as e:
                        print("Error parsing date:", e)
                        needs_review = True

                db.execute('INSERT INTO notes (patient_id, appointment_id, session_number, needs_review, content) VALUES (?, ?, ?, ?, ?)',
                           (patient_id, appointment_id, meeting_no, needs_review, content))
                db.commit()
                if needs_review:
                    flash('DOCX parsed, but some fields were missing. Marked for review.')
                else:
                    flash('DOCX parsed successfully. Note created.')
            except Exception as e:
                print(f"Error parsing DOCX: {e}")
                flash('Error parsing DOCX file.')

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

    # Messages
    messages = db.execute('''
        SELECT * FROM messages
        WHERE sender_id = ? OR recipient_id = ?
        ORDER BY timestamp ASC
    ''', (current_user.id, current_user.id)).fetchall()

    # Calculate debt
    total_cost = db.execute('SELECT SUM(cost) as total FROM appointments WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    total_paid = db.execute('SELECT SUM(amount) as total FROM receipts WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    balance = total_cost - total_paid

    return render_template('dashboard.html', patient=patient, appointments=appointments, receipts=receipts, files=files, balance=balance, messages=messages)

@app.route('/admin_reply_message/<int:patient_id>', methods=['POST'])
@login_required
def admin_reply_message(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form['content']
    if content:
        db = get_db()
        user = db.execute('SELECT id FROM users WHERE patient_id = ?', (patient_id,)).fetchone()
        if user:
            db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                       (current_user.id, user['id'], content))
            db.commit()
            flash('Message sent.')
        else:
            flash('Patient does not have an active user account to receive messages.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

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

@app.route('/api/slots')
@login_required
def api_slots():
    # Only return slots for authorized patients or admins
    if current_user.role == 'patient':
        db = get_db()
        patient = db.execute('SELECT status, can_self_schedule FROM patients WHERE id = ?', (current_user.patient_id,)).fetchone()
        if patient['status'] != 'waiting for scheduling' and not patient['can_self_schedule']:
            return jsonify([])

    db = get_db()
    # Get all slots and appointments to figure out availability
    # We will look ahead 8 weeks as standard.
    # In a real system, you might have slots_recurring or generate them on the fly.
    # For now, we will just pull slots_override and existing appointments.

    start_str = request.args.get('start')
    end_str = request.args.get('end')

    if not start_str or not end_str:
        return jsonify([])

    start_date = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
    end_date = datetime.datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()

    # Get overrides
    overrides = db.execute('SELECT * FROM slots_override WHERE slot_date >= ? AND slot_date <= ?', (start_date.isoformat(), end_date.isoformat())).fetchall()

    # Get existing appointments
    appointments = db.execute('SELECT * FROM appointments WHERE appointment_date >= ? AND appointment_date <= ?', (start_date.isoformat(), end_date.isoformat())).fetchall()

    events = []

    for override in overrides:
        slot_datetime = f"{override['slot_date']}T{override['slot_time']}"
        status = override['status']
        color = 'gray'
        if status == 'open':
            color = 'green'
        elif status == 'occupied':
            color = 'red'
        elif status == 'blocked':
            color = 'gray'

        events.append({
            'id': f"slot_{override['id']}",
            'title': status.capitalize(),
            'start': slot_datetime,
            'color': color,
            'extendedProps': {'status': status}
        })

    for appt in appointments:
        # Use padded time
        time_str = appt['appointment_time']
        if len(time_str) == 4: # e.g., 9:00
             time_str = "0" + time_str

        slot_datetime = f"{appt['appointment_date']}T{time_str}"
        events.append({
            'id': f"appt_{appt['id']}",
            'title': 'Occupied (Appt)',
            'start': slot_datetime,
            'color': 'red',
            'extendedProps': {'status': 'occupied'}
        })

    return jsonify(events)

@app.route('/admin/slots', methods=['GET'])
@login_required
def manage_slots():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    return render_template('manage_slots.html')

@app.route('/api/admin/slots', methods=['POST'])
@login_required
def admin_manage_slots():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    date = request.form['date']
    time = request.form['time']
    status = request.form['status']

    db = get_db()
    existing = db.execute('SELECT id FROM slots_override WHERE slot_date = ? AND slot_time = ?', (date, time)).fetchone()

    if existing:
        db.execute('UPDATE slots_override SET status = ? WHERE id = ?', (status, existing['id']))
    else:
        db.execute('INSERT INTO slots_override (slot_date, slot_time, status) VALUES (?, ?, ?)', (date, time, status))

    db.commit()
    flash('Slot updated.')
    return redirect(url_for('manage_slots'))

@app.route('/patient_book_slot', methods=['POST'])
@login_required
def patient_book_slot():
    if current_user.role != 'patient':
        return "Unauthorized", 403

    db = get_db()
    patient = db.execute('SELECT status, can_self_schedule FROM patients WHERE id = ?', (current_user.patient_id,)).fetchone()
    if patient['status'] != 'waiting for scheduling' and not patient['can_self_schedule']:
        flash('You do not have permission to self-schedule.')
        return redirect(url_for('dashboard'))

    date = request.form['date']
    time = request.form['time']

    # Check if slot is open
    slot = db.execute('SELECT id, status FROM slots_override WHERE slot_date = ? AND slot_time = ?', (date, time)).fetchone()
    if slot and slot['status'] == 'open':
        # Book it
        db.execute('INSERT INTO appointments (patient_id, appointment_date, appointment_time, status) VALUES (?, ?, ?, ?)',
                   (current_user.patient_id, date, time, 'scheduled'))
        # Mark slot as occupied
        db.execute("UPDATE slots_override SET status = 'occupied' WHERE id = ?", (slot['id'],))
        db.commit()
        flash('Session successfully scheduled.')
    else:
        flash('This slot is no longer available.')

    return redirect(url_for('dashboard'))

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

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
