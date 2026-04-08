import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory
from werkzeug.utils import secure_filename
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

    # Chart data: Session Frequency (Last 6 Months)
    from datetime import datetime
    import json

    # We will just count appointments per month for the last 6 months
    # Simple SQLite date extraction
    session_counts = db.execute('''
        SELECT strftime('%Y-%m', appointment_date) as month, COUNT(*) as count
        FROM appointments
        WHERE patient_id = ?
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
    ''', (patient_id,)).fetchall()

    session_labels = [row['month'] for row in session_counts]
    session_data = [row['count'] for row in session_counts]
    session_labels.reverse()
    session_data.reverse()

    # Chart data: Key Topics Frequency
    topics = db.execute('SELECT key_topics FROM notes WHERE patient_id = ? AND key_topics IS NOT NULL AND key_topics != ""', (patient_id,)).fetchall()
    topic_counts = {}
    for t in topics:
        # Split by comma and strip whitespace
        words = [w.strip().title() for w in t['key_topics'].split(',')]
        for word in words:
            if word:
                topic_counts[word] = topic_counts.get(word, 0) + 1

    topic_labels = list(topic_counts.keys())
    topic_data = list(topic_counts.values())

    chart_data = {
        'session_labels': json.dumps(session_labels),
        'session_data': json.dumps(session_data),
        'topic_labels': json.dumps(topic_labels),
        'topic_data': json.dumps(topic_data)
    }

    return render_template('patient_detail.html', patient=patient, notes=notes, files=files, receipts=receipts, user=user, appointments=appointments, chart_data=chart_data)

@app.route('/patient/<int:patient_id>/add_note', methods=('POST',))
@login_required
def add_note(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form['content']
    session_number = request.form.get('session_number')
    patient_appearance = request.form.get('patient_appearance')
    key_topics = request.form.get('key_topics')

    if content:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('INSERT INTO notes (patient_id, session_number, patient_appearance, key_topics, content) VALUES (?, ?, ?, ?, ?)',
                   (patient_id, session_number, patient_appearance, key_topics, content))
        note_id = cursor.lastrowid
        db.commit()

        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db.execute('INSERT INTO files (patient_id, note_id, filename) VALUES (?, ?, ?)',
                           (patient_id, note_id, filename))
                db.commit()

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/note/<int:note_id>/edit', methods=('POST',))
@login_required
def edit_note(note_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form['content']
    session_number = request.form.get('session_number')
    patient_appearance = request.form.get('patient_appearance')
    key_topics = request.form.get('key_topics')

    db = get_db()
    note = db.execute('SELECT patient_id FROM notes WHERE id = ?', (note_id,)).fetchone()
    if not note:
        return "Note not found", 404

    db.execute('''
        UPDATE notes
        SET content = ?, session_number = ?, patient_appearance = ?, key_topics = ?
        WHERE id = ?
    ''', (content, session_number, patient_appearance, key_topics, note_id))
    db.commit()

    flash('Note updated successfully.')
    return redirect(url_for('patient_detail', patient_id=note['patient_id']))

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

    messages = db.execute('''
        SELECT m.*, u.role as sender_role
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.sender_id = ? OR m.recipient_id = ?
        ORDER BY m.timestamp ASC
    ''', (current_user.id, current_user.id)).fetchall()

    # Calculate debt
    total_cost = db.execute('SELECT SUM(cost) as total FROM appointments WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    total_paid = db.execute('SELECT SUM(amount) as total FROM receipts WHERE patient_id = ?', (patient_id,)).fetchone()['total'] or 0
    balance = total_cost - total_paid

    return render_template('dashboard.html', patient=patient, appointments=appointments, receipts=receipts, files=files, balance=balance, messages=messages)

@app.route('/messages')
@login_required
def messages():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))

    db = get_db()

    # Fetch all patients who have messages
    patients_with_messages = db.execute('''
        SELECT DISTINCT p.id, p.name
        FROM patients p
        JOIN users u ON u.patient_id = p.id
        JOIN messages m ON m.sender_id = u.id OR m.recipient_id = u.id
    ''').fetchall()

    selected_patient_id = request.args.get('patient_id', type=int)
    messages = []

    if selected_patient_id:
        user = db.execute('SELECT id FROM users WHERE patient_id = ?', (selected_patient_id,)).fetchone()
        if user:
            messages = db.execute('''
                SELECT m.*, u.role as sender_role
                FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.sender_id = ? OR m.recipient_id = ?
                ORDER BY m.timestamp ASC
            ''', (user['id'], user['id'])).fetchall()

    return render_template('messages.html', patients=patients_with_messages, messages=messages, selected_patient_id=selected_patient_id)

@app.route('/contact_admin', methods=('POST',))
@login_required
def contact_admin():
    content = request.form['content']

    if current_user.role == 'patient':
        if content:
            db = get_db()
            admin = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
            recipient_id = admin['id'] if admin else None

            db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                       (current_user.id, recipient_id, content))
            db.commit()
            flash('Message sent to your therapist.')
        return redirect(url_for('dashboard'))
    elif current_user.role == 'admin':
        patient_id = request.form.get('patient_id')
        if content and patient_id:
            db = get_db()
            patient_user = db.execute("SELECT id FROM users WHERE patient_id = ?", (patient_id,)).fetchone()
            if patient_user:
                db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                           (current_user.id, patient_user['id'], content))
                db.commit()
        return redirect(url_for('messages', patient_id=patient_id))

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

@app.route('/api/slots', methods=['GET'])
@login_required
def get_slots():
    db = get_db()

    if current_user.role == 'admin':
        # Admin sees all slots, with patient names
        slots = db.execute('''
            SELECT s.id, s.start_time, s.end_time, s.status, s.patient_id, p.name as patient_name
            FROM slots s
            LEFT JOIN patients p ON s.patient_id = p.id
        ''').fetchall()
    else:
        # Patient sees open slots and their own booked slots
        slots = db.execute('''
            SELECT id, start_time, end_time, status, patient_id
            FROM slots
            WHERE status = 'open' OR patient_id = ?
        ''', (current_user.patient_id,)).fetchall()

    events = []
    for slot in slots:
        event = {
            'id': slot['id'],
            'start': slot['start_time'],
            'end': slot['end_time']
        }

        if current_user.role == 'admin':
            if slot['status'] == 'booked':
                event['title'] = f"Booked: {slot['patient_name']}"
                event['color'] = '#dc3545' # Red for booked
            else:
                event['title'] = 'Open'
                event['color'] = '#28a745' # Green for open
        else:
            if slot['status'] == 'booked' and slot['patient_id'] == current_user.patient_id:
                event['title'] = 'My Appointment'
                event['color'] = '#007bff' # Blue for their own
            else:
                event['title'] = 'Open'
                event['color'] = '#28a745'

        events.append(event)

    import json
    return json.dumps(events), 200, {'Content-Type': 'application/json'}

@app.route('/api/slots', methods=['POST'])
@login_required
def create_slot():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    data = request.json
    start_time = data.get('start')
    end_time = data.get('end')

    db = get_db()
    db.execute('INSERT INTO slots (start_time, end_time) VALUES (?, ?)', (start_time, end_time))
    db.commit()
    return "Slot created", 201

@app.route('/api/slots/<int:slot_id>/book', methods=['POST'])
@login_required
def book_slot(slot_id):
    if current_user.role != 'patient':
        return "Unauthorized", 403

    db = get_db()
    slot = db.execute('SELECT * FROM slots WHERE id = ?', (slot_id,)).fetchone()

    if not slot or slot['status'] != 'open':
        return "Slot not available", 400

    db.execute('UPDATE slots SET status = ?, patient_id = ? WHERE id = ?',
               ('booked', current_user.patient_id, slot_id))
    db.commit()
    return "Slot booked", 200

@app.route('/api/slots/<int:slot_id>', methods=['DELETE'])
@login_required
def delete_slot(slot_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    db.execute('DELETE FROM slots WHERE id = ?', (slot_id,))
    db.commit()
    return "Slot deleted", 200

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
