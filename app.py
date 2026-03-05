import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import docx
import re

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

    return render_template('patient_detail.html', patient=patient, notes=notes, files=files, receipts=receipts, user=user, appointments=appointments)

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

        # Parse docx if uploaded
        if filename.endswith('.docx'):
            try:
                doc = docx.Document(filepath)
                full_text = []
                for para in doc.paragraphs:
                    full_text.append(para.text)
                text = '\n'.join(full_text)

                # Basic extraction logic
                date_match = re.search(r'\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}', text)
                meeting_match = re.search(r'(פגישה מס|meeting number|session number)[\'"]?\s*:?\s*(\d+)', text, re.IGNORECASE)

                date = date_match.group(0) if date_match else None
                meeting_num = meeting_match.group(2) if meeting_match else None

                content = f"Parsed from {filename}:\n"
                if meeting_num:
                    content += f"Meeting Number: {meeting_num}\n"
                content += f"\nContent:\n{text}"

                db.execute('INSERT INTO notes (patient_id, content) VALUES (?, ?)', (patient_id, content))

                if date:
                    # Optional: Add appointment if not exists or update.
                    # We'll just add an appointment for the parsed date at 00:00.
                    # Standardize date format to YYYY-MM-DD for consistency
                    if '/' in date:
                        parts = date.split('/')
                        if len(parts[2]) == 4: # DD/MM/YYYY
                           date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    db.execute('INSERT INTO appointments (patient_id, appointment_date, appointment_time, status) VALUES (?, ?, ?, ?)',
                               (patient_id, date, '00:00', 'completed'))

                    patient = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
                    msg = f"New Booking: Appointment created for {patient['name']} from parsed document on {date} at 00:00"
                    db.execute('INSERT INTO notifications (message) VALUES (?)', (msg,))

                flash('File uploaded and parsed successfully.')
            except Exception as e:
                flash(f'File uploaded, but parsing failed: {str(e)}')
        else:
            flash('File uploaded successfully.')

        db.commit()
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

    # Calculate debt
    total_cost = db.execute('SELECT SUM(cost) as total FROM appointments WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    total_paid = db.execute('SELECT SUM(amount) as total FROM receipts WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    balance = total_cost - total_paid

    return render_template('dashboard.html', patient=patient, appointments=appointments, receipts=receipts, files=files, balance=balance)

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

        patient = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
        msg = f"New Booking: Appointment manually created for {patient['name']} on {date} at {time}"
        db.execute('INSERT INTO notifications (message) VALUES (?)', (msg,))

        db.commit()
        flash('Appointment added.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/manage_slots')
@login_required
def manage_slots():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    return render_template('manage_slots.html')

@app.route('/api/slots')
@login_required
def api_slots():
    db = get_db()
    events = []

    # Free and Occupied slots
    slots = db.execute('SELECT * FROM slots').fetchall()
    for s in slots:
        start_datetime = f"{s['slot_date']}T{s['start_time']}"
        end_datetime = f"{s['slot_date']}T{s['end_time']}"
        color = 'green' if s['status'] == 'free' else 'red'
        events.append({
            'id': f"slot_{s['id']}",
            'title': s['status'].capitalize(),
            'start': start_datetime,
            'end': end_datetime,
            'color': color,
            'type': 'slot'
        })

    # Blocked slots
    blocked = db.execute('SELECT * FROM blocked_slots').fetchall()
    for b in blocked:
        start_datetime = f"{b['slot_date']}T{b['start_time']}"
        end_datetime = f"{b['slot_date']}T{b['end_time']}"
        events.append({
            'id': f"blocked_{b['id']}",
            'title': b['reason'] or 'Blocked',
            'start': start_datetime,
            'end': end_datetime,
            'color': 'gray',
            'type': 'blocked'
        })

    # Patient's own appointments if requested from dashboard
    if current_user.role == 'patient':
        appts = db.execute('SELECT * FROM appointments WHERE patient_id = ?', (current_user.patient_id,)).fetchall()
        for a in appts:
            start_datetime = f"{a['appointment_date']}T{a['appointment_time']}"
            events.append({
                'id': a['id'],
                'title': 'My Appointment',
                'start': start_datetime,
                'color': 'blue',
                'type': 'appointment'
            })
    elif current_user.role == 'admin':
        # Admin sees all appointments mapped to occupied slots, but maybe we want them distinct
        # For this requirement, color coding green/red/gray is enough. Occupied handles it.
        pass

    return jsonify(events)

@app.route('/api/appointments/<int:appt_id>/reschedule', methods=['POST'])
@login_required
def reschedule_appointment(appt_id):
    if current_user.role != 'patient':
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    new_date = data.get('date')
    new_time = data.get('time')

    if not new_date or not new_time:
        return jsonify({'error': 'Missing date or time'}), 400

    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ? AND patient_id = ?', (appt_id, current_user.patient_id)).fetchone()

    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404

    # Free the old slot
    old_slot_time = appt['appointment_time']
    # If the database returns HH:MM:SS, we need to handle it.
    # The frontend sends HH:MM. Let's try matching exactly or with :00
    old_slot = db.execute('SELECT * FROM slots WHERE slot_date = ? AND (start_time = ? OR start_time = ?) AND status = "occupied"',
                          (appt['appointment_date'], old_slot_time, old_slot_time[:5] + ':00' if len(old_slot_time) == 5 else old_slot_time[:5])).fetchone()
    if old_slot:
        db.execute('UPDATE slots SET status = "free" WHERE id = ?', (old_slot['id'],))

    # Occupy the new slot
    new_slot = db.execute('SELECT * FROM slots WHERE slot_date = ? AND (start_time = ? OR start_time = ?) AND status = "free"',
                          (new_date, new_time, new_time[:5] + ':00' if len(new_time) == 5 else new_time[:5])).fetchone()
    if new_slot:
        db.execute('UPDATE slots SET status = "occupied" WHERE id = ?', (new_slot['id'],))

    # Update appointment
    db.execute('UPDATE appointments SET appointment_date = ?, appointment_time = ? WHERE id = ?', (new_date, new_time, appt_id))

    # Log notification for admin
    patient = db.execute('SELECT name FROM patients WHERE id = ?', (current_user.patient_id,)).fetchone()
    msg = f"Appointment rescheduled by {patient['name']} to {new_date} {new_time}"
    db.execute('INSERT INTO notifications (message) VALUES (?)', (msg,))

    db.commit()
    return jsonify({'success': True})

@app.route('/api/slots', methods=['POST'])
@login_required
def add_slot():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    slot_date = data.get('date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    status = data.get('status', 'free')

    if not slot_date or not start_time or not end_time:
        return jsonify({'error': 'Missing date or times'}), 400

    db = get_db()

    if status in ['free', 'occupied']:
        db.execute('INSERT INTO slots (slot_date, start_time, end_time, status) VALUES (?, ?, ?, ?)',
                   (slot_date, start_time, end_time, status))
    elif status == 'blocked':
        db.execute('INSERT INTO blocked_slots (slot_date, start_time, end_time, reason) VALUES (?, ?, ?, ?)',
                   (slot_date, start_time, end_time, 'Blocked'))

    db.commit()
    return jsonify({'success': True})

@app.route('/api/slots/<string:slot_type>/<int:slot_id>', methods=['DELETE'])
@login_required
def delete_slot(slot_type, slot_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    db = get_db()
    if slot_type == 'slot':
        db.execute('DELETE FROM slots WHERE id = ?', (slot_id,))
    elif slot_type == 'blocked':
        db.execute('DELETE FROM blocked_slots WHERE id = ?', (slot_id,))
    else:
        return jsonify({'error': 'Invalid slot type'}), 400

    db.commit()
    return jsonify({'success': True})

@app.route('/api/notifications')
@login_required
def api_notifications():
    if current_user.role != 'admin':
        return jsonify([])

    db = get_db()
    nots = db.execute('SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at DESC').fetchall()

    # Mark as read (simple approach: clear them once fetched)
    if nots:
        ids = [n['id'] for n in nots]
        placeholders = ','.join('?' * len(ids))
        db.execute(f'UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})', ids)
        db.commit()

    return jsonify([dict(n) for n in nots])

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
