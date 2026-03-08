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
    "Send Securely": "שלח בצורה מאובטחת",
    "Export History": "יצא היסטוריה",
    "Import": "ייבא",
    "Import Patient History (JSON)": "ייבוא היסטוריית מטופל (JSON)",
    "Upload File or DOCX Treatment Log": "העלאת קובץ או יומן טיפולים DOCX",
    "Calendar Actions": "פעולות יומן",
    "Export Calendar to JSON": "ייצא יומן ל-JSON",
    "Import Calendar from JSON": "ייבא יומן מ-JSON",
    "Import Calendar": "ייבא יומן",
    "Repeat until specific date:": "חזור עד תאריך מסוים:",
    "Repeat for X meetings:": "חזור עבור X פגישות:",
    "Number of meetings": "מספר פגישות",
    "First Appointment Date": "תאריך פגישה ראשון",
    "Duration (Minutes)": "משך (דקות)",
    "Recurrence Interval (Weeks)": "תדירות חזרה (שבועות)",
    "Every Week": "כל שבוע",
    "Every 2 Weeks": "כל שבועיים",
    "Recurrence End Limit": "גבול סיום חזרה",
    "Days of Week": "ימי השבוע",
    "Sun": "א'",
    "Mon": "ב'",
    "Tue": "ג'",
    "Wed": "ד'",
    "Thu": "ה'",
    "Check the days that apply. If none checked, defaults to the day of the first appointment.": "סמן את הימים הרלוונטיים. אם לא סומן, יקבע לפי יום הפגישה הראשון.",
    "Cost per Session ($)": "עלות לפגישה ($)",
    "Meeting Link (if Online)": "קישור לפגישה (אם מקוון)",
    "Cancel": "ביטול",
    "Save & Convert": "שמור והמר",
    "Welcome Back": "ברוכים השבים",
    "Please sign in to access the clinic CRM": "אנא היכנס כדי לגשת למערכת הניהול",
    "Username": "שם משתמש",
    "Password": "ססמה",
    "Forgot?": "שכחת?",
    "New patient?": "מטופל חדש?",
    "Register here": "הירשם כאן",
    "Book Session": "קבע פגישה",
    "Would you like to schedule a session for": "האם תרצה לקבוע פגישה ל-",
    "Confirm Booking": "אשר קביעה",
    "Add New Resource": "הוסף משאב חדש",
    "Title": "כותרת",
    "URL": "קישור",
    "Public (visible to everyone)": "פומבי (גלוי לכולם)",
    "Add Resource": "הוסף משאב",
    "Manage Resources": "נהל משאבים",
    "Access": "גישה",
    "Date Added": "תאריך הוספה",
    "Actions": "פעולות",
    "Public": "פומבי",
    "Private": "פרטי",
    "No resources found.": "לא נמצאו משאבים.",
    "Edit Patient": "ערוך מטופל",
    "Update patient information": "עדכן פרטי מטופל",
    "Full Name": "שם מלא",
    "Status": "סטטוס",
    "Email Address": "כתובת דוא״ל",
    "Phone Number": "מספר טלפון",
    "Save Changes": "שמור שינויים",
    "Add New Patient": "הוסף מטופל חדש",
    "Initial Status": "סטטוס התחלתי",
    "Add Patient": "הוסף מטופל",
    "Manage Slot": "נהל משבצת הזמן",
    "Manage slot for": "נהל משבצת זמן עבור",
    "Duration": "משך זמן",
    "Slot Status": "סטטוס משבצת הזמן",
    "Open (Clickable for patients)": "פתוח (זמין למטופלים)",
    "Occupied (Busy)": "תפוס (עסוק)",
    "Blocked (Unavailable)": "חסום (לא זמין)",
    "Save": "שמור",
    "Enter username": "הכנס שם משתמש",
    "Sign In": "התחבר",
    "Register": "הירשם"
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
            db.execute('ALTER TABLE appointments ADD COLUMN recurrence_end_date DATE')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN recurrence_count INTEGER')
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
            db.execute('''CREATE TABLE IF NOT EXISTS slots_override (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_date DATE NOT NULL,
                slot_time TIME NOT NULL,
                status TEXT NOT NULL,
                duration_minutes INTEGER DEFAULT 60
            )''')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE slots_override ADD COLUMN duration_minutes INTEGER DEFAULT 60')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('''CREATE TABLE IF NOT EXISTS blocked_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocked_date DATE NOT NULL,
                blocked_time TIME NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
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

                # Split the text by meeting header to support multiple entries
                # Look for "Meeting #" or "פגישה מספר" and split, keeping the delimiter if needed or just finditer
                # A good way is to use finditer to find the start of each section

                # Match start of meeting section
                meeting_pattern = re.compile(r'(?:Meeting #|פגישה מספר)[:\s]*\w+', re.IGNORECASE)
                matches = list(meeting_pattern.finditer(text))

                if not matches:
                    # Fallback to the whole text if no explicit meeting markers
                    blocks = [text]
                else:
                    blocks = []
                    for i, match in enumerate(matches):
                        start_idx = match.start()
                        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(text)
                        blocks.append(text[start_idx:end_idx])

                notes_created = 0
                notes_review = 0

                for block in blocks:
                    meeting_no_match = re.search(r'(?:Meeting #|פגישה מספר)[:\s]*(\w+)', block, re.IGNORECASE)
                    date_match = re.search(r'(?:Date|תאריך)[:\s]*([\d\./\-]+)', block, re.IGNORECASE)
                    content_match = re.search(r'(?:Content|תוכן)[:\s]*(.*)', block, re.IGNORECASE | re.DOTALL)

                    meeting_no = meeting_no_match.group(1).strip() if meeting_no_match else None
                    date_str = date_match.group(1).strip() if date_match else None
                    content = content_match.group(1).strip() if content_match else block.strip() # default to all text if no content marker

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
                    if needs_review:
                        notes_review += 1
                    else:
                        notes_created += 1

                db.commit()
                if notes_review > 0:
                    flash(f'DOCX parsed. {notes_created} notes created, {notes_review} marked for review.')
                else:
                    flash(f'DOCX parsed successfully. {notes_created} notes created.')
            except Exception as e:
                print(f"Error parsing DOCX: {e}")
                flash('Error parsing DOCX file.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/patient/<int:patient_id>/export', methods=('GET',))
@login_required
def export_patient_history(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if patient is None:
        return "Patient not found", 404

    appointments = [dict(row) for row in db.execute('SELECT * FROM appointments WHERE patient_id = ? ORDER BY appointment_date ASC, appointment_time ASC', (patient_id,)).fetchall()]
    notes = [dict(row) for row in db.execute('SELECT * FROM notes WHERE patient_id = ? ORDER BY created_at ASC', (patient_id,)).fetchall()]
    receipts = [dict(row) for row in db.execute('SELECT * FROM receipts WHERE patient_id = ? ORDER BY created_at ASC', (patient_id,)).fetchall()]

    data = {
        'patient': dict(patient),
        'appointments': appointments,
        'notes': notes,
        'receipts': receipts
    }

    import json
    from flask import Response
    response = Response(json.dumps(data, indent=4), mimetype='application/json')
    response.headers['Content-Disposition'] = f'attachment; filename=patient_{patient_id}_history.json'
    return response

@app.route('/api/admin/export_calendar')
@login_required
def export_calendar():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    appointments = db.execute('''
        SELECT appointment_date, appointment_time, meeting_type, meeting_link,
               is_recurring, recurrence_interval, recurrence_days, recurrence_end_date, recurrence_count,
               duration_minutes, cost
        FROM appointments
        ORDER BY appointment_date ASC, appointment_time ASC
    ''').fetchall()

    import json
    from flask import Response

    data = [dict(row) for row in appointments]
    response = Response(json.dumps(data, indent=4), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename=calendar_export.json'
    return response

@app.route('/admin/seed_data', methods=('POST',))
@login_required
def seed_data():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()

    # 1 Ongoing patient
    db.execute("INSERT INTO patients (name, status, email, phone) VALUES ('John Doe (Ongoing)', 'ongoing', 'john.doe@example.com', '555-0101')")
    ongoing_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    past_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    db.execute('''INSERT INTO appointments (patient_id, appointment_date, appointment_time, cost, duration_minutes, status, meeting_type)
                  VALUES (?, ?, '10:00', 150, 60, 'completed', 'in-person')''', (ongoing_id, past_date))
    appt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    db.execute('''INSERT INTO notes (patient_id, appointment_id, session_number, content)
                  VALUES (?, ?, '1', 'Initial session. Patient presented with anxiety.')''', (ongoing_id, appt_id))

    # 1 Candidate patient
    db.execute("INSERT INTO patients (name, status, email, phone) VALUES ('Jane Smith (Candidate)', 'candidate', 'jane.smith@example.com', '555-0102')")

    # 1 Waiting for scheduling patient
    db.execute("INSERT INTO patients (name, status, email, phone, can_self_schedule) VALUES ('Alice Johnson (Waiting)', 'waiting for scheduling', 'alice.j@example.com', '555-0103', 1)")
    waiting_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', ?)",
               ('alice', generate_password_hash('password123'), waiting_id))

    # 1 Archived patient
    db.execute("INSERT INTO patients (name, status, email, phone) VALUES ('Bob Brown (Archived)', 'archived', 'bob.b@example.com', '555-0104')")

    db.commit()
    flash('Sample data seeded successfully.')
    return redirect(url_for('dashboard'))

@app.route('/api/admin/import_calendar', methods=('POST',))
@login_required
def import_calendar():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('dashboard'))

    if file and file.filename.endswith('.json'):
        import json
        try:
            data = json.load(file)
            # Sort by date and time
            data.sort(key=lambda x: (x.get('appointment_date', ''), x.get('appointment_time', '')))

            db = get_db()

            # For simplicity we import these under a "dummy" patient or the first ongoing patient
            # In a real app we'd map them, but we need a patient_id. We'll find any ongoing.
            patient = db.execute("SELECT id FROM patients WHERE status='ongoing' LIMIT 1").fetchone()
            if not patient:
                # create one
                db.execute("INSERT INTO patients (name, status) VALUES ('Imported Patient', 'ongoing')")
                patient_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                patient_id = patient['id']

            count = 0
            for appt in data:
                db.execute('''INSERT INTO appointments
                    (patient_id, appointment_date, appointment_time, meeting_type, meeting_link,
                     is_recurring, recurrence_interval, recurrence_days, recurrence_end_date, recurrence_count,
                     cost, duration_minutes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (patient_id, appt.get('appointment_date'), appt.get('appointment_time'),
                     appt.get('meeting_type', 'in-person'), appt.get('meeting_link'),
                     appt.get('is_recurring', 0), appt.get('recurrence_interval'), appt.get('recurrence_days'),
                     appt.get('recurrence_end_date'), appt.get('recurrence_count'),
                     appt.get('cost', 0), appt.get('duration_minutes', 60)))
                count += 1
            db.commit()
            flash(f'Successfully imported {count} appointments.')
        except Exception as e:
            print("Import error:", e)
            flash('Error parsing JSON file.')
    else:
        flash('Please upload a JSON file.')

    return redirect(url_for('dashboard'))

@app.route('/patient/<int:patient_id>/import', methods=('POST',))
@login_required
def import_patient_history(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('patient_detail', patient_id=patient_id))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('patient_detail', patient_id=patient_id))

    if file and file.filename.endswith('.json'):
        import json
        try:
            data = json.load(file)
            db = get_db()

            # Optionally validate data format here
            appointments_added = 0
            notes_added = 0
            receipts_added = 0

            # Import appointments
            appt_id_map = {}
            # Sort appointments by date and time
            sorted_appts = sorted(data.get('appointments', []), key=lambda x: (x.get('appointment_date', ''), x.get('appointment_time', '')))
            for appt in sorted_appts:
                # Check for existing
                existing = db.execute('SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ? AND appointment_time = ?',
                    (patient_id, appt.get('appointment_date'), appt.get('appointment_time'))).fetchone()
                if not existing:
                    cursor = db.execute('''INSERT INTO appointments
                        (patient_id, appointment_date, appointment_time, cost, duration_minutes, is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link, status, recurrence_end_date, recurrence_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (patient_id, appt.get('appointment_date'), appt.get('appointment_time'), appt.get('cost'), appt.get('duration_minutes'),
                         appt.get('is_recurring'), appt.get('recurrence_interval'), appt.get('recurrence_days'), appt.get('meeting_type'),
                         appt.get('meeting_link'), appt.get('status'), appt.get('recurrence_end_date'), appt.get('recurrence_count')))
                    appt_id_map[appt.get('id')] = cursor.lastrowid
                    appointments_added += 1
                else:
                    appt_id_map[appt.get('id')] = existing['id']

            # Import notes
            # Sort notes by created_at or session_number if possible
            sorted_notes = sorted(data.get('notes', []), key=lambda x: (x.get('created_at', ''), x.get('session_number', '')))
            for note in sorted_notes:
                new_appt_id = appt_id_map.get(note.get('appointment_id')) if note.get('appointment_id') else None
                db.execute('''INSERT INTO notes
                    (patient_id, appointment_id, session_number, content, content_hebrew, needs_review, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (patient_id, new_appt_id, note.get('session_number'), note.get('content'), note.get('content_hebrew'), note.get('needs_review'), note.get('created_at')))
                notes_added += 1

            # Import receipts
            for receipt in data.get('receipts', []):
                db.execute('''INSERT INTO receipts
                    (patient_id, amount, description, created_at)
                    VALUES (?, ?, ?, ?)''',
                    (patient_id, receipt.get('amount'), receipt.get('description'), receipt.get('created_at')))
                receipts_added += 1

            db.commit()
            flash(f'History imported: {appointments_added} appointments, {notes_added} notes, {receipts_added} receipts added.')
        except Exception as e:
            print("Import error:", e)
            flash('Error parsing JSON file.')
    else:
        flash('Please upload a JSON file.')

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

    limit_type = request.form.get('recurrence_limit_type')
    recurrence_end_date = None
    recurrence_count = None
    if limit_type == 'date':
        recurrence_end_date = request.form.get('recurrence_end_date')
    elif limit_type == 'count':
        try:
            recurrence_count = int(request.form.get('recurrence_count'))
        except (ValueError, TypeError):
            recurrence_count = None

    # Get checked days (multiple values)
    days_list = request.form.getlist('days')
    days_str = ','.join(days_list) if days_list else None

    db.execute("UPDATE patients SET status = 'ongoing' WHERE id = ?", (patient_id,))

    meeting_type = request.form.get('meeting_type', 'in-person')
    meeting_link = request.form.get('meeting_link', '')

    if start_date and time:
        db.execute('''INSERT INTO appointments
                      (patient_id, appointment_date, appointment_time, cost, duration_minutes, is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link, recurrence_end_date, recurrence_count)
                      VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)''',
                   (patient_id, start_date, time, cost, duration, interval, days_str, meeting_type, meeting_link, recurrence_end_date, recurrence_count))

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

        # We need patient info to log notification properly
        patient = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
        if patient:
            details = f"Patient {patient['name']} has scheduled a meeting to {date} at {time}."
            db.execute('INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)', (patient_id, 'schedule', details))

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
                generated_count = 1 # The original appointment counts as 1
                limit_date = None
                if appt.get('recurrence_end_date'):
                    try:
                        limit_date = datetime.datetime.fromisoformat(appt['recurrence_end_date']).date()
                    except ValueError:
                        pass

                limit_count = appt.get('recurrence_count')

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
                            if test_date > current_date:
                                if limit_date and test_date > limit_date:
                                    continue
                                if limit_count and generated_count >= limit_count:
                                    continue

                                generated_count += 1
                                if start_date <= test_date <= end_date:
                                    # Check for conflict with blocked slots_override
                                    test_date_iso = test_date.isoformat()
                                    is_blocked = any(
                                        o['slot_date'] == test_date_iso and o['slot_time'] == time_str and o['status'] == 'blocked'
                                        for o in overrides
                                    )
                                    if is_blocked:
                                        continue

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

@app.route('/export_ics/<int:appointment_id>')
@login_required
def export_ics(appointment_id):
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

@app.route('/appointment/<int:appointment_id>/ical')
@login_required
def export_ical(appointment_id):
    return redirect(url_for('export_ics', appointment_id=appointment_id))

@app.route('/api/notifications')
@login_required
def get_notifications():
    if current_user.role != 'admin':
        return jsonify([])

    last_id = request.args.get('last_id', 0, type=int)
    db = get_db()

    logs = db.execute('SELECT * FROM audit_logs WHERE id > ? AND action IN ("schedule", "reschedule") ORDER BY id ASC', (last_id,)).fetchall()

    notifications = []
    for log in logs:
        notifications.append({
            'id': log['id'],
            'message': log['details'],
            'created_at': log['created_at']
        })

    return jsonify(notifications)

@app.route('/api/appointments/<int:appointment_id>/reschedule', methods=('POST',))
@login_required
def reschedule_appointment(appointment_id):
    if current_user.role != 'patient':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()

    # Check permissions
    patient_id = current_user.patient_id
    patient = db.execute('SELECT can_self_schedule, name FROM patients WHERE id = ?', (patient_id,)).fetchone()

    if not patient or not patient['can_self_schedule']:
        return jsonify({'status': 'error', 'message': 'You do not have permission to reschedule appointments.'}), 403

    appt = db.execute('SELECT * FROM appointments WHERE id = ? AND patient_id = ?', (appointment_id, patient_id)).fetchone()
    if not appt:
        return jsonify({'status': 'error', 'message': 'Appointment not found.'}), 404

    data = request.get_json()
    new_date = data.get('date')
    new_time = data.get('time')

    if not new_date or not new_time:
        return jsonify({'status': 'error', 'message': 'Missing date or time.'}), 400

    # Check if slot is blocked
    blocked = db.execute('SELECT * FROM blocked_slots WHERE blocked_date = ? AND blocked_time = ?', (new_date, new_time)).fetchone()
    if blocked:
        return jsonify({'status': 'error', 'message': 'This slot is unavailable.'}), 400

    # Check if slot is occupied
    occupied = db.execute('SELECT * FROM appointments WHERE appointment_date = ? AND appointment_time = ?', (new_date, new_time)).fetchone()
    if occupied:
        return jsonify({'status': 'error', 'message': 'This slot is already booked.'}), 400

    # Reschedule
    db.execute('UPDATE appointments SET appointment_date = ?, appointment_time = ? WHERE id = ?', (new_date, new_time, appointment_id))

    # Audit log
    details = f"Patient {patient['name']} has moved a meeting to {new_date} at {new_time}."
    db.execute('INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)', (patient_id, 'reschedule', details))

    db.commit()

    return jsonify({'status': 'success'})

def send_appointment_reminders():
    # Placeholder for logic to send reminders via email or SMS via external APIs.
    # In a real application, this would query appointments for the next 24-48 hours,
    # and use an API like Twilio (SMS) or SendGrid/SMTP (Email) to notify the patient.
    db = get_db()

    # Example logic:
    # tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    # upcoming = db.execute('SELECT a.*, p.email, p.phone, p.name FROM appointments a JOIN patients p ON a.patient_id = p.id WHERE a.appointment_date = ?', (tomorrow,)).fetchall()
    # for appt in upcoming:
    #     if appt['email']:
    #         # send_email_api(appt['email'], f"Reminder: Your appointment is tomorrow at {appt['appointment_time']}.")
    #         pass
    #     if appt['phone']:
    #         # send_sms_api(appt['phone'], f"Reminder: Your appointment is tomorrow at {appt['appointment_time']}.")
    #         pass

    print("Appointment reminders sent via external APIs (Email/SMS).")

@app.route('/appointment/<int:appointment_id>/delete', methods=('POST',))
@login_required
def delete_appointment(appointment_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    appt = db.execute('SELECT patient_id, appointment_date, appointment_time FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if appt:
        patient_id = appt['patient_id']
        date = appt['appointment_date']
        time = appt['appointment_time']

        patient = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()

        db.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))

        if patient:
            details = f"Patient {patient['name']}'s appointment on {date} at {time} was deleted."
            db.execute('INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)', (patient_id, 'delete_appointment', details))

        db.commit()
        flash('Appointment deleted.')
        return redirect(url_for('patient_detail', patient_id=patient_id))

    return "Appointment not found", 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
