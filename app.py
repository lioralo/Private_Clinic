import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, jsonify, session
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

@app.template_filter('rjust')
def rjust_filter(s, width, fillchar=' '):
    return str(s).rjust(width, fillchar)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

HEBREW_TRANSLATIONS = {
    "Dashboard": "לוח בקרה",
    "Ongoing": "בטיפול",
    "Candidates": "מועמדים",
    "Waiting": "ממתינים",
    "Archived": "בארכיון",
    "Manage Slots": "ניהול יומן",
    "Add Patient": "הוספת מטופל",
    "Messages": "הודעות",
    "Logout": "התנתק",
    "Login": "התחבר",
    "Public Resources": "משאבים ציבוריים",
    "Resources": "משאבים",
    "Search": "חיפוש",
    "Summary": "סיכום",
    "Appointments": "פגישות",
    "Clinical Notes": "רשומות קליניות",
    "Billing": "חיובים",
    "Internal Chat": "צ'אט פנימי",
    "Send Email": "שלח דוא״ל",
    "WhatsApp": "וואטסאפ",
    "Edit": "ערוך",
    "Convert to Ongoing": "הפוך למטופל פעיל",
    "Email": "דוא״ל",
    "Phone": "טלפון",
    "Date": "תאריך",
    "Time": "שעה",
    "Cost": "עלות",
    "Meeting Type": "סוג פגישה",
    "Meeting Link": "קישור לפגישה",
    "Add": "הוסף",
    "In-Person": "פרונטלי",
    "Online": "מקוון",
    "Remove appointment?": "להסיר את הפגישה?",
    "Treatment Log": "יומן טיפולים",
    "Content (English)": "תוכן (אנגלית)",
    "תוכן (Hebrew)": "תוכן (עברית)",
    "Attach Files": "צרף קבצים",
    "Post Treatment Log": "שמור רשומה",
    "Needs Review": "דורש בדיקה",
    "Attached Files:": "קבצים מצורפים:",
    "No clinical history recorded.": "לא תועדה היסטוריה קלינית.",
    "Financial Receipts": "קבלות פיננסיות",
    "Amount ($)": "סכום",
    "Description": "תיאור",
    "Create New Receipt": "צור קבלה חדשה",
    "Medical Service": "שירות רפואי",
    "No financial records.": "אין רשומות פיננסיות.",
    "Type a message...": "הקלד הודעה...",
    "No messages yet.": "אין הודעות עדיין.",
    "Assign Resource": "הקצה משאב",
    "Select a Private Resource...": "בחר משאב פרטי...",
    "Assign": "הקצה",
    "Assigned Resources": "משאבים שהוקצו",
    "No resources assigned.": "לא הוקצו משאבים.",
    "Financial Summary": "סיכום פיננסי",
    "Total Outstanding": "סך חוב",
    "Credit Balance": "יתרת זכות",
    "Account Balance": "יתרת חשבון",
    "Outstanding balance for therapeutic services.": "יתרת חוב עבור שירותים טיפוליים.",
    "You have credit in your account.": "יש לך יתרת זכות בחשבון.",
    "Your account is fully settled!": "החשבון שלך מוסדר במלואו!",
    "My Appointments": "הפגישות שלי",
    "Sessions": "פגישות",
    "Scheduled at": "נקבע לשעה",
    "Join Meeting": "הצטרף לפגישה",
    "No therapy sessions scheduled.": "לא נקבעו פגישות טיפוליות.",
    "Schedule a Session": "קבע פגישה",
    "Scheduling is only available for patients currently awaiting placement.": "קביעת פגישות זמינה רק למטופלים הממתינים לשיבוץ.",
    "Receipts": "קבלות",
    "Print": "הדפס",
    "Service Receipt": "קבלת שירות",
    "No receipts.": "אין קבלות.",
    "Shared Files": "קבצים משותפים",
    "No shared files.": "אין קבצים משותפים.",
    "Open": "פתח",
    "No resources assigned to you.": "לא הוקצו לך משאבים.",
    "Contact Therapist": "צור קשר עם המטפל",
    "Direct messages with your clinical provider.": "הודעות ישירות עם המטפל שלך.",
    "Send a message to start.": "שלח הודעה כדי להתחיל.",
    "Send Securely": "שלח בצורה מאובטחת"
}

@app.context_processor
def inject_translations():
    def t(text):
        if session.get('lang') == 'he':
            return HEBREW_TRANSLATIONS.get(text, text)
        return text
    return dict(t=t, lang=session.get('lang', 'en'))

@app.route('/set_lang/<lang>')
def set_lang(lang):
    if lang in ['en', 'he']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

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

        db.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_read BOOLEAN DEFAULT 0,
                FOREIGN KEY (sender_id) REFERENCES users (id),
                FOREIGN KEY (recipient_id) REFERENCES users (id)
            )
        ''')

        # Handle column migrations
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN duration_minutes INTEGER DEFAULT 60')
        except sqlite3.OperationalError:
            pass # Column exists
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN is_recurring BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN recurrence_interval INTEGER')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN recurrence_days TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN meeting_type TEXT DEFAULT "in-person"')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN meeting_link TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE notes ADD COLUMN content_hebrew TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE files ADD COLUMN treatment_id INTEGER')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE slots_override ADD COLUMN duration_minutes INTEGER DEFAULT 60')
        except sqlite3.OperationalError:
            pass
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

@app.route('/resources')
def public_resources():
    db = get_db()
    resources = db.execute('SELECT * FROM resources WHERE is_public = 1 ORDER BY created_at DESC').fetchall()
    return render_template('resources.html', resources=resources, is_admin=False)

@app.route('/admin/resources', methods=['GET', 'POST'])
@login_required
def manage_resources():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()

    if request.method == 'POST':
        title = request.form['title']
        description = request.form.get('description', '')
        url = request.form.get('url', '')
        is_public = 1 if request.form.get('is_public') else 0

        db.execute('INSERT INTO resources (title, description, url, is_public) VALUES (?, ?, ?, ?)',
                   (title, description, url, is_public))
        db.commit()
        flash('Resource added.')
        return redirect(url_for('manage_resources'))

    resources = db.execute('SELECT * FROM resources ORDER BY created_at DESC').fetchall()
    return render_template('manage_resources.html', resources=resources)

@app.route('/patient/<int:patient_id>/assign_resource', methods=['POST'])
@login_required
def assign_resource(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    resource_id = request.form['resource_id']
    if resource_id:
        db = get_db()
        try:
            db.execute('INSERT INTO patient_resources (patient_id, resource_id) VALUES (?, ?)', (patient_id, resource_id))
            db.commit()
            flash('Resource assigned to patient.')
        except sqlite3.IntegrityError:
            flash('Resource already assigned to this patient.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

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

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form.get('email')
        phone = request.form.get('phone')

        if not name:
            flash('Name is required!')
        else:
            db = get_db()
            db.execute('INSERT INTO patients (name, status, email, phone) VALUES (?, ?, ?, ?)',
                       (name, 'candidate', email, phone))
            db.commit()
            flash('Registration successful! We will contact you soon.')
            return redirect(url_for('login'))

    return render_template('register.html')

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

    # Get resources for assignment
    all_resources = db.execute('SELECT * FROM resources WHERE is_public = 0 ORDER BY title ASC').fetchall()

    # Get assigned resources
    assigned_resources = db.execute('''
        SELECT r.*
        FROM resources r
        JOIN patient_resources pr ON r.id = pr.resource_id
        WHERE pr.patient_id = ?
    ''', (patient_id,)).fetchall()

    return render_template('patient_detail.html', patient=patient, notes=notes, files=files, receipts=receipts, user=user, appointments=appointments, messages=messages, all_resources=all_resources, assigned_resources=assigned_resources)

@app.route('/patient/<int:patient_id>/add_note', methods=('POST',))
@login_required
def add_note(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form.get('content', '')
    content_hebrew = request.form.get('content_hebrew', '')

    if content or content_hebrew:
        db = get_db()
        cur = db.execute('INSERT INTO notes (patient_id, content, content_hebrew) VALUES (?, ?, ?)', (patient_id, content, content_hebrew))
        note_id = cur.lastrowid
        db.commit()

        files = request.files.getlist('files')
        for file in files:
            if file and file.filename != '':
                filename = secure_filename(file.filename)

                patient_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'treatments', str(patient_id))
                if not os.path.exists(patient_dir):
                    os.makedirs(patient_dir)

                filepath = os.path.join(patient_dir, filename)
                file.save(filepath)

                db.execute('INSERT INTO files (patient_id, treatment_id, filename) VALUES (?, ?, ?)', (patient_id, note_id, filename))
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
    file_record = db.execute('SELECT patient_id, treatment_id FROM files WHERE filename = ?', (name,)).fetchone()

    if not file_record:
        # Maybe it's not in DB (dummy file). Allow admin.
        if current_user.role == 'admin':
             return send_from_directory(app.config['UPLOAD_FOLDER'], name)
        else:
             return "File not found or access denied", 403

    if current_user.role == 'admin' or (current_user.role == 'patient' and current_user.patient_id == file_record['patient_id']):
        if file_record['treatment_id']:
            patient_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'treatments', str(file_record['patient_id']))
            return send_from_directory(patient_dir, name)
        return send_from_directory(app.config['UPLOAD_FOLDER'], name)

    return "Access denied", 403

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()

    if current_user.role == 'admin':
        # Admin Dashboard View
        # Get candidates without recurring appointments
        candidates = db.execute('''
            SELECT p.*
            FROM patients p
            WHERE p.status = 'candidate' AND p.id NOT IN (
                SELECT DISTINCT patient_id
                FROM appointments
                WHERE is_recurring = 1
            )
        ''').fetchall()
        return render_template('admin_dashboard.html', candidates=candidates)

    # Patient Dashboard View
    patient_id = current_user.patient_id

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

    # Get assigned resources
    assigned_resources = db.execute('''
        SELECT r.*
        FROM resources r
        JOIN patient_resources pr ON r.id = pr.resource_id
        WHERE pr.patient_id = ?
        ORDER BY pr.assigned_at DESC
    ''', (patient_id,)).fetchall()

    return render_template('dashboard.html', patient=patient, appointments=appointments, receipts=receipts, files=files, balance=balance, messages=messages, assigned_resources=assigned_resources)

@app.route('/api/messages', methods=['GET'])
@login_required
def api_get_messages():
    db = get_db()
    if current_user.role == 'admin':
        # Admin gets all messages for now, or maybe just a combined inbox.
        # Ideally, it would be per-patient, but for a simple "Messages sidebar"
        # we can show all messages sent to/from the admin or a global list.
        # If we had a selected patient in the UI, we'd filter. Here we just return all.
        messages = db.execute('''
            SELECT m.*, u.username as sender_name
            FROM messages m
            LEFT JOIN users u ON m.sender_id = u.id
            ORDER BY m.timestamp ASC
        ''').fetchall()
    else:
        # Patient gets messages to/from them
        messages = db.execute('''
            SELECT m.*, u.username as sender_name
            FROM messages m
            LEFT JOIN users u ON m.sender_id = u.id
            WHERE m.sender_id = ? OR m.recipient_id = ?
            ORDER BY m.timestamp ASC
        ''', (current_user.id, current_user.id)).fetchall()

    return jsonify([dict(m) for m in messages])

@app.route('/api/messages/send', methods=['POST'])
@login_required
def api_send_message():
    content = request.form.get('content')
    if not content:
        return jsonify({'status': 'error'})

    db = get_db()

    # Simple logic: If patient, send to admin. If admin, send as broadcast or to a specific user?
    # For a general "messages sidebar" where admin sees everything, sending a message from admin might need a recipient.
    # We will just insert it with NULL recipient for broadcast or if patient is sending.
    recipient_id = None

    if current_user.role == 'patient':
        admin = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        recipient_id = admin['id'] if admin else None

    db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
               (current_user.id, recipient_id, content))
    db.commit()
    return jsonify({'status': 'success'})

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

@app.route('/patient/<int:patient_id>/convert', methods=('POST',))
@login_required
def convert_patient(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()

    start_date = request.form.get('start_date')
    time = request.form.get('time')
    duration = request.form.get('duration', 60)
    interval = request.form.get('interval', 1)
    cost = request.form.get('cost', 0)

    # Get checked days (multiple values)
    days_list = request.form.getlist('days')
    days_str = ','.join(days_list) if days_list else None

    db.execute("UPDATE patients SET status = 'ongoing' WHERE id = ?", (patient_id,))

    meeting_type = request.form.get('meeting_type', 'in-person')
    meeting_link = request.form.get('meeting_link', '')

    if start_date and time:
        db.execute('''INSERT INTO appointments
                      (patient_id, appointment_date, appointment_time, cost, duration_minutes, is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link)
                      VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)''',
                   (patient_id, start_date, time, cost, duration, interval, days_str, meeting_type, meeting_link))

    db.commit()
    flash('Patient converted to ongoing successfully.')
    return redirect(url_for('patient_detail', patient_id=patient_id))

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
    meeting_type = request.form.get('meeting_type', 'in-person')
    meeting_link = request.form.get('meeting_link', '')

    if date and time:
        db = get_db()
        db.execute('INSERT INTO appointments (patient_id, appointment_date, appointment_time, cost, meeting_type, meeting_link) VALUES (?, ?, ?, ?, ?, ?)',
                   (patient_id, date, time, cost, meeting_type, meeting_link))
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
        slot_datetime_start = f"{override['slot_date']}T{override['slot_time']}"
        duration = override['duration_minutes'] or 60
        dt_start = datetime.datetime.fromisoformat(slot_datetime_start)
        dt_end = dt_start + datetime.timedelta(minutes=duration)
        slot_datetime_end = dt_end.isoformat()

        status = override['status']
        color = 'gray'
        if status == 'open':
            color = 'green'
        elif status == 'occupied':
            color = 'red'
        elif status == 'blocked':
            color = 'gray'

        if current_user.role == 'patient':
            if status == 'open':
                events.append({
                    'id': f"slot_{override['id']}",
                    'title': status.capitalize(),
                    'start': slot_datetime_start,
                    'end': slot_datetime_end,
                    'color': color,
                    'extendedProps': {'status': status, 'duration_minutes': duration}
                })
        else:
            events.append({
                'id': f"slot_{override['id']}",
                'title': status.capitalize(),
                'start': slot_datetime_start,
                'end': slot_datetime_end,
                'color': color,
                'extendedProps': {'status': status, 'duration_minutes': duration}
            })

    if current_user.role != 'patient':
        for appt in appointments:
            # Use padded time
            time_str = appt['appointment_time']
            if len(time_str) == 4: # e.g., 9:00
                 time_str = "0" + time_str

            slot_datetime_start = f"{appt['appointment_date']}T{time_str}"
            duration = appt['duration_minutes'] or 60
            dt_start = datetime.datetime.fromisoformat(slot_datetime_start)
            dt_end = dt_start + datetime.timedelta(minutes=duration)
            slot_datetime_end = dt_end.isoformat()

            events.append({
                'id': f"appt_{appt['id']}",
                'title': 'Occupied (Appt)',
                'start': slot_datetime_start,
                'end': slot_datetime_end,
                'color': 'red',
                'extendedProps': {'status': 'occupied', 'duration_minutes': duration}
            })

            # Project recurring appointments
            if appt['is_recurring'] and appt['recurrence_interval']:
                current_date = dt_start.date()
                interval_weeks = appt['recurrence_interval']
                # Days of week: e.g. "0,2" for Sunday, Tuesday. Python weekday() is Monday=0, Sunday=6
                # We map 0=Sunday, 1=Monday ... 6=Saturday for FullCalendar consistency
                days_str = appt['recurrence_days']
                recurrence_days = []
                if days_str:
                    recurrence_days = [int(d) for d in days_str.split(',') if d.strip().isdigit()]
                else:
                    # default to the day of the original appointment if not specified
                    # fullcalendar: sunday=0. python: monday=0. python -> fullcalendar: (weekday + 1) % 7
                    recurrence_days = [(current_date.weekday() + 1) % 7]

                # Project up to 8 weeks ahead
                for i in range(1, 8 // interval_weeks + 1):
                    base_next_date = current_date + datetime.timedelta(weeks=interval_weeks * i)
                    # Now project for each day in recurrence_days
                    for day_offset in range(7):
                        test_date = base_next_date - datetime.timedelta(days=base_next_date.weekday()) + datetime.timedelta(days=day_offset) # Start of week (Monday) + day_offset
                        # Wait, FullCalendar weeks start on Sunday usually, but Python's weekday() starts on Monday.
                        # Let's map FullCalendar day to Python weekday: 0->6, 1->0, 2->1, 3->2, 4->3, 5->4, 6->5
                        test_fc_day = (test_date.weekday() + 1) % 7

                        if test_fc_day in recurrence_days:
                            # Only project if the test_date is on or after the original appointment date (for the very first week)
                            if test_date >= current_date:
                                if start_date <= test_date <= end_date:
                                    next_dt_start = datetime.datetime.combine(test_date, dt_start.time())
                                    next_dt_end = next_dt_start + datetime.timedelta(minutes=duration)
                                    events.append({
                                        'id': f"appt_recur_{appt['id']}_{i}_{test_fc_day}",
                                        'title': 'Occupied (Recurring)',
                                        'start': next_dt_start.isoformat(),
                                        'end': next_dt_end.isoformat(),
                                        'color': 'red',
                                        'extendedProps': {'status': 'occupied', 'duration_minutes': duration}
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
    duration = int(request.form.get('duration', 60))

    db = get_db()
    existing = db.execute('SELECT id FROM slots_override WHERE slot_date = ? AND slot_time = ?', (date, time)).fetchone()

    if existing:
        db.execute('UPDATE slots_override SET status = ?, duration_minutes = ? WHERE id = ?', (status, duration, existing['id']))
    else:
        db.execute('INSERT INTO slots_override (slot_date, slot_time, status, duration_minutes) VALUES (?, ?, ?, ?)', (date, time, status, duration))

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

@app.route('/appointment/<int:appointment_id>/ical')
@login_required
def export_ical(appointment_id):
    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if not appt:
        return "Not found", 404

    # Security check: only allow admin or the patient who owns the appointment
    if current_user.role == 'patient' and appt['patient_id'] != current_user.patient_id:
        return "Unauthorized", 403

    import uuid
    from datetime import datetime, timedelta

    start_datetime = datetime.fromisoformat(f"{appt['appointment_date']}T{appt['appointment_time']}")
    end_datetime = start_datetime + timedelta(minutes=appt['duration_minutes'] or 60)

    dtstart = start_datetime.strftime("%Y%m%dT%H%M%S")
    dtend = end_datetime.strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    ical_content = f"""BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Private Clinic CRM//EN\r
BEGIN:VEVENT\r
UID:{uuid.uuid4()}@clinic\r
DTSTAMP:{dtstamp}\r
DTSTART:{dtstart}\r
DTEND:{dtend}\r
SUMMARY:Therapy Session\r
DESCRIPTION:Therapy session\r
"""
    if appt['meeting_link']:
        ical_content += f"URL:{appt['meeting_link']}\r\n"
        ical_content += f"LOCATION:{appt['meeting_link']}\r\n"
    elif appt['meeting_type'] == 'in-person':
        ical_content += f"LOCATION:Clinic\r\n"

    ical_content += """END:VEVENT\r
END:VCALENDAR\r
"""

    from flask import make_response
    response = make_response(ical_content)
    response.headers["Content-Disposition"] = f"attachment; filename=appointment_{appointment_id}.ics"
    response.headers["Content-type"] = "text/calendar"
    return response

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
