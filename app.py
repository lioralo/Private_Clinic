import os
import sqlite3
import socket
import json
import shutil
from collections import Counter
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, jsonify, session
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import re
from docx import Document
from datetime import datetime, timedelta
from flask import jsonify


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = os.environ.get('SECRET_KEY', 'dev')
csrf = CSRFProtect(app)
DATABASE = 'clinic.db'
BACKUP_DIR = 'secure_backups'
BACKUP_INTERVAL_HOURS = 12

@app.template_filter('rjust')
def rjust_filter(s, width, fillchar=' '):
    return str(s).rjust(width, fillchar)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

HEBREW_TRANSLATIONS = {
    "Dashboard": "לוח בקרה",
    "Add First Patient": "הוסף מטופל ראשון",
    "No patients found in this category.": "לא נמצאו מטופלים בקטגוריה זו.",
    "ID:": "ת.ז:",
    "Total": "סה״כ",
    "View Profile": "הצג פרופיל",

    "All Patients": "כל המטופלים",
    "Candidates & Waiting": "מועמדים וממתינים",
    "Candidate/Waiting": "מועמד/ממתין",
    "Patients": "מטופלים",
    "Missing Recurring Appointment": "חסרה פגישה חוזרת",

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
    "Generate AI Background": "צור רקע אוטומטי",
    "AI-generated summary based on meeting logs.": "סיכום אוטומטי המבוסס על יומני הפגישות.",
    "AI background generated.": "נוצר רקע אוטומטי.",
    "Full Name": "שם מלא",
    "Status": "סטטוס",
    "Email Address": "כתובת דוא״ל",
    "Phone Number": "מספר טלפון",
    "Date of Birth": "תאריך לידה",
    "ID Number": "תעודת זהות",
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
    "Register": "הירשם",
    "Weekly Snapshot Calendar": "תמונת מצב שבועית",
    "Current workweek only (Sunday-Thursday, 08:00-20:00). The board auto-rolls to the next week.": "שבוע העבודה הנוכחי בלבד (א'-ה', 08:00-20:00). הלוח מתעדכן אוטומטית לשבוע הבא.",
    "Back to CRM": "חזרה ל-CRM",
    "Schedule": "יומן",
    "Booking Panel": "פאנל קביעות",
    "Available Slots": "זמינות",
    "Add Block": "הוסף חסימה",
    "Legend:": "מקרא:",
    "Candidate/Waiting": "מועמד/ממתין",
    "Blocked": "חסום",
    "Special Occasion": "אירוע מיוחד",
    "Filters:": "סינון:",
    "All": "הכל",
    "Special": "מיוחד",
    "Showing:": "מוצג:",
    "Current week": "השבוע הנוכחי",
    "Ongoing this week:": "בטיפול השבוע:",
    "None": "אין",
    "Follow-Up Indicators": "התראות מעקב",
    "No pending follow-up indicators.": "אין התראות מעקב כרגע.",
    "Friday Specials": "אירועים מיוחדים - שישי",
    "Saturday Specials": "אירועים מיוחדים - שבת",
    "No weekend items.": "אין פריטים לסופ״ש.",
    "Available Slots This Week": "זמינות לשבוע זה",
    "Self-Booking": "קביעה עצמית",
    "You can book into available slots and cancel your own sessions from the calendar.": "אפשר לקבוע לזמנים פנויים ולבטל פגישות שלך מהיומן.",
    "Self-booking is currently disabled by your therapist.": "קביעה עצמית כרגע כבויה על ידי המטפל.",
    "Patient": "מטופל",
    "Select patient...": "בחר מטופל...",
    "Selected Slot": "משבצת נבחרת",
    "No slot selected": "לא נבחרה משבצת",
    "End Time": "שעת סיום",
    "Booking Type": "סוג קביעה",
    "Appointment": "פגישה",
    "Special Pattern": "תבנית אירוע מיוחד",
    "One-time": "חד פעמי",
    "Weekly Recurring": "חוזר שבועית",
    "Repeat Until": "חזרה עד",
    "Special Title": "כותרת אירוע מיוחד",
    "Seminar / Conference / Vacation": "סמינר / כנס / חופשה",
    "Meeting Link (optional)": "קישור פגישה (אופציונלי)",
    "Click Meet or Zoom to open in a new tab, copy the link, then paste above.": "לחץ Meet או Zoom לפתיחה בלשונית חדשה, העתק את הקישור והדבק כאן.",
    "Book Selected Slot": "קבע משבצת נבחרת",
    "Start Time": "שעת התחלה",
    "Type": "סוג",
    "Admin title": "כותרת למנהל",
    "Hide title from patients (shown as Unavailable)": "הסתר כותרת ממטופלים (יוצג כלא זמין)",
    "Save Override": "שמור דריסה",
    "Calendar Action": "פעולת יומן",
    "OK": "אישור",
    "Clinic CRM": "מערכת CRM קלינית",
    "Management center for patients, treatment logs, and clinic resources.": "מרכז ניהול למטופלים, יומני טיפול ומשאבי קליניקה.",
    "Treatment Log Template": "תבנית יומן טיפולים",
    "View mode": "מצב תצוגה",
    "Cards": "כרטיסים",
    "List": "רשימה"
}

@app.context_processor
def inject_translations():
    def t(text):
        if session.get('lang') == 'he':
            return HEBREW_TRANSLATIONS.get(text, text)
        return text
    return dict(t=t, lang=session.get('lang', 'en'))

@app.context_processor
def inject_global_vars():
    unread_messages = 0
    if current_user.is_authenticated:
        db = get_db()
        unread_messages = db.execute(
            'SELECT COUNT(*) as count FROM messages WHERE recipient_id = ? AND is_read = 0',
            (current_user.id,)
        ).fetchone()['count']
    return dict(unread_messages=unread_messages)

@app.route('/set_lang/<lang>')
def set_lang(lang):
    if lang in ['en', 'he']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))


@app.before_request
def routine_backup_guard():
    if request.path.startswith('/static/'):
        return
    if app.config.get('TESTING'):
        return
    try:
        perform_routine_encrypted_backup(app.config.get('DATABASE', DATABASE))
    except Exception:
        # Keep requests alive even if backup fails.
        pass

class User(UserMixin):
    def __init__(self, id, username, role, patient_id=None, display_name=None):
        self.id = id
        self.username = username
        self.role = role
        self.patient_id = patient_id
        self.display_name = display_name or username

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        return User(user['id'], user['username'], user['role'], user['patient_id'], user['display_name'])
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


def _get_or_create_backup_key():
    key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if key:
        return key.encode('utf-8')

    backup_root = Path(BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    key_path = backup_root / '.backup.key'
    if key_path.exists():
        return key_path.read_bytes().strip()

    from cryptography.fernet import Fernet
    generated = Fernet.generate_key()
    key_path.write_bytes(generated)
    return generated


def _database_backup_fingerprint(db_file_path):
    """Build a compact fingerprint so backup verification checks meaningful data parity."""
    conn = sqlite3.connect(str(db_file_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            row['name'] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]

        table_counts = {}
        for table_name in tables:
            count_row = conn.execute(f'SELECT COUNT(*) AS c FROM "{table_name}"').fetchone()
            table_counts[table_name] = int(count_row['c'] if count_row else 0)

        appointment_stats = conn.execute('''
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN COALESCE(is_recurring, 0) = 1 THEN 1 ELSE 0 END) AS recurring_total,
                SUM(CASE WHEN COALESCE(meeting_link, '') <> '' THEN 1 ELSE 0 END) AS with_meeting_link,
                SUM(CASE WHEN COALESCE(recurrence_days, '') <> '' THEN 1 ELSE 0 END) AS with_recurrence_days,
                SUM(CASE WHEN COALESCE(recurrence_interval, 0) > 0 THEN 1 ELSE 0 END) AS with_recurrence_interval,
                SUM(CASE WHEN COALESCE(recurrence_end_date, '') <> '' THEN 1 ELSE 0 END) AS with_recurrence_end_date,
                SUM(CASE WHEN COALESCE(recurrence_count, 0) > 0 THEN 1 ELSE 0 END) AS with_recurrence_count
            FROM appointments
        ''').fetchone()

        return {
            'table_counts': table_counts,
            'appointment_stats': {
                'total': int(appointment_stats['total'] or 0),
                'recurring_total': int(appointment_stats['recurring_total'] or 0),
                'with_meeting_link': int(appointment_stats['with_meeting_link'] or 0),
                'with_recurrence_days': int(appointment_stats['with_recurrence_days'] or 0),
                'with_recurrence_interval': int(appointment_stats['with_recurrence_interval'] or 0),
                'with_recurrence_end_date': int(appointment_stats['with_recurrence_end_date'] or 0),
                'with_recurrence_count': int(appointment_stats['with_recurrence_count'] or 0),
            }
        }
    finally:
        conn.close()


def perform_encrypted_backup(db_path):
    db_source = Path(db_path)
    if not db_source.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    # Guard against backing up a corrupted database.
    src_check = sqlite3.connect(db_path)
    try:
        integrity = src_check.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f"Backup aborted, source DB integrity check failed: {integrity}")
    finally:
        src_check.close()

    backup_root = Path(BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    raw_backup_path = backup_root / f'clinic_{timestamp}.db'
    encrypted_path = backup_root / f'clinic_{timestamp}.db.enc'
    verify_backup_path = backup_root / f'.verify_{timestamp}.db'

    source_fingerprint = _database_backup_fingerprint(db_path)

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(raw_backup_path)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    from cryptography.fernet import Fernet
    cipher = Fernet(_get_or_create_backup_key())
    raw_bytes = raw_backup_path.read_bytes()
    encrypted_bytes = cipher.encrypt(raw_bytes)
    encrypted_path.write_bytes(encrypted_bytes)

    # Quick sanity check so we do not keep unreadable backups.
    try:
        probe = cipher.decrypt(encrypted_bytes)
        if not probe.startswith(b'SQLite format 3'):
            raise RuntimeError('Encrypted backup verification failed: invalid SQLite header')

        verify_backup_path.write_bytes(probe)
        backup_fingerprint = _database_backup_fingerprint(verify_backup_path)
        if backup_fingerprint != source_fingerprint:
            raise RuntimeError('Encrypted backup verification failed: data fingerprint mismatch')
    except Exception as exc:
        encrypted_path.unlink(missing_ok=True)
        raw_backup_path.unlink(missing_ok=True)
        verify_backup_path.unlink(missing_ok=True)
        raise RuntimeError(f'Encrypted backup verification failed: {exc}')

    raw_backup_path.unlink(missing_ok=True)
    verify_backup_path.unlink(missing_ok=True)
    return str(encrypted_path)


def perform_routine_encrypted_backup(db_path):
    backup_root = Path(BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    marker = backup_root / '.last_backup_at'

    now = datetime.now()
    if marker.exists():
        try:
            last_run = datetime.fromisoformat(marker.read_text().strip())
            if now - last_run < timedelta(hours=BACKUP_INTERVAL_HOURS):
                return None
        except ValueError:
            pass

    encrypted_path = perform_encrypted_backup(db_path)
    marker.write_text(now.isoformat())
    return encrypted_path


def list_encrypted_backups():
    backup_root = Path(BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    backups = sorted(backup_root.glob('clinic_*.db.enc'), reverse=True)
    return [path.name for path in backups]


def perform_encrypted_restore(db_path, backup_filename=None):
    backup_root = Path(BACKUP_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)

    backups = sorted(backup_root.glob('clinic_*.db.enc'))
    if not backups:
        raise FileNotFoundError('No encrypted backups found.')

    if backup_filename:
        safe_name = Path(backup_filename).name
        target = backup_root / safe_name
        if target not in backups or not target.exists():
            raise FileNotFoundError('Selected backup file was not found.')
    else:
        target = backups[-1]

    from cryptography.fernet import Fernet
    cipher = Fernet(_get_or_create_backup_key())
    decrypted = cipher.decrypt(target.read_bytes())
    if not decrypted.startswith(b'SQLite format 3'):
        raise RuntimeError('Backup decrypt succeeded but SQLite header is invalid.')

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_restore = backup_root / f'.restore_tmp_{timestamp}.db'
    safety_copy = backup_root / f'clinic_pre_restore_{timestamp}.db'

    temp_restore.write_bytes(decrypted)

    temp_conn = sqlite3.connect(str(temp_restore))
    try:
        integrity = temp_conn.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f'Restored backup integrity check failed: {integrity}')
    finally:
        temp_conn.close()

    live_db = Path(db_path)
    if live_db.exists():
        shutil.copy2(live_db, safety_copy)

    # Ensure no request-scoped DB handle stays open while replacing file.
    existing = getattr(g, '_database', None)
    if existing is not None:
        existing.close()
        g._database = None

    shutil.copy2(temp_restore, live_db)
    temp_restore.unlink(missing_ok=True)

    verify_conn = sqlite3.connect(str(live_db))
    try:
        verify_integrity = verify_conn.execute('PRAGMA integrity_check').fetchone()[0]
        if verify_integrity != 'ok':
            raise RuntimeError(f'Post-restore database integrity check failed: {verify_integrity}')
    finally:
        verify_conn.close()

    return str(target), str(safety_copy)

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
            db.execute('ALTER TABLE notes ADD COLUMN note_date DATE')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE notes ADD COLUMN patient_appearance TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE notes ADD COLUMN key_topics TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE notes ADD COLUMN updated_at TIMESTAMP')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE notes ADD COLUMN behavior_checklist TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE notes ADD COLUMN mood_summary TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE notes ADD COLUMN behavior_notes TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE files ADD COLUMN treatment_id INTEGER')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN background TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN treatment_info TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE slots_override ADD COLUMN duration_minutes INTEGER DEFAULT 60')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN can_self_schedule BOOLEAN DEFAULT 0')
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
            db.execute('ALTER TABLE blocked_slots ADD COLUMN duration_minutes INTEGER DEFAULT 60')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE blocked_slots ADD COLUMN title TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE blocked_slots ADD COLUMN is_private BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE blocked_slots ADD COLUMN block_type TEXT DEFAULT 'blocked'")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE blocked_slots ADD COLUMN created_by INTEGER')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE patients ADD COLUMN patient_type TEXT DEFAULT 'private'")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN intake_assessment TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN intake_questionnaire TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE patients ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE patients ADD COLUMN deleted_at TIMESTAMP")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN birth_date DATE')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN id_number TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE patients ADD COLUMN has_intake_tab BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN meeting_platform TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN meeting_title TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE appointments ADD COLUMN save_to_google BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE users ADD COLUMN display_name TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE users ADD COLUMN email TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE users ADD COLUMN phone TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE users ADD COLUMN id_number TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE users ADD COLUMN birth_date DATE')
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

        try:
            db.execute('''CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('''CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_id) REFERENCES patients (id)
            )''')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('''CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_type TEXT DEFAULT 'support',
                description TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('''CREATE TABLE IF NOT EXISTS group_members (
                group_id INTEGER NOT NULL,
                patient_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                left_at TIMESTAMP,
                role TEXT DEFAULT 'member',
                PRIMARY KEY (group_id, patient_id),
                FOREIGN KEY (group_id) REFERENCES groups (id),
                FOREIGN KEY (patient_id) REFERENCES patients (id)
            )''')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('''CREATE TABLE IF NOT EXISTS group_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                session_date DATE NOT NULL,
                session_time TIME NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                title TEXT,
                facilitator TEXT,
                meeting_type TEXT DEFAULT 'in-person',
                meeting_link TEXT,
                status TEXT DEFAULT 'scheduled',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES groups (id)
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

        if admin and not admin['display_name']:
            db.execute('UPDATE users SET display_name = ? WHERE id = ?', ('Admin', admin['id']))
            db.commit()

        print(f"Initialized the database at {database}.")

        if not app.config.get('TESTING'):
            try:
                perform_routine_encrypted_backup(database)
            except Exception as backup_error:
                print(f"Routine backup skipped: {backup_error}")

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
        print(f"Created upload folder: {app.config['UPLOAD_FOLDER']}")

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('crm_dashboard'))
        elif current_user.role == 'patient':
            return redirect(url_for('patient_home'))
    return redirect(url_for('login'))


HEBREW_NUMBER_WORDS = {
    'אחד': '1',
    'אחת': '1',
    'שני': '2',
    'שניים': '2',
    'שתיים': '2',
    'שתי': '2',
    'שלושה': '3',
    'שלוש': '3',
    'ארבעה': '4',
    'ארבע': '4',
    'חמישה': '5',
    'חמש': '5'
}


BACKGROUND_REASON_TOPICS = {
    'אבל ואובדן': ['נפטר', 'פטירה', 'שבעה', 'אבל', 'אלמן', 'אלמנה'],
    'חרדה ומתח': ['חרד', 'חרדה', 'פחד', 'חשש', 'דאג', 'לחץ'],
    'קשיים במשפחה וביחסים קרובים': ['ילדים', 'ילד', 'בת', 'בן', 'בעל', 'אמא', 'אבא', 'משפחה', 'זוג'],
    'קשיי תפקוד בעבודה או בלימודים': ['עבודה', 'מנהל', 'בוס', 'מפעל', 'מכללה', 'לומד', 'לומדת', 'צבא'],
    'בושה, חריגות ודימוי עצמי': ['בושה', 'חריג', 'לא בסדר', 'אשם', 'לא נחמדה', 'רעה'],
    'מחשבות אובססיביות או ירידה נפשית': ['אובסס', 'דיכא', 'בדידות', 'אין לו כח', 'אין לה כח', 'שעמום']
}


BACKGROUND_THEME_TOPICS = {
    'יחסי קרבה, תלות ועצמאות': ['עצמאי', 'עצמאית', 'תלוי', 'תלות', 'להיעזר', 'להיתמך', 'לעזור', 'מרחק', 'קרובה'],
    'ביקורת עצמית ותחושת חריגות': ['בושה', 'חריג', 'לא בסדר', 'אשם', 'רעה', 'לא נחמדה'],
    'חרדה, דריכות וציפייה לפגיעה': ['חרד', 'פחד', 'חשש', 'לא בטוח', 'סכנה', 'מאיים', 'דריכות'],
    'אבל, בדידות וחוויית אובדן': ['נפטר', 'פטירה', 'בדידות', 'שכול', 'שבעה', 'אובדן'],
    'גבולות, עימותים וקונפליקטים': ['גבול', 'ריב', 'כעס', 'תוקפ', 'אסרטיב', 'מריבה', 'ויכוח'],
    'עומס תפקודי בעבודה, לימודים או שירות': ['עבודה', 'מכללה', 'לימוד', 'צבא', 'משמרת', 'תפקיד', 'מפעל']
}


def normalize_summary_text(text):
    if not text:
        return ''
    return ' '.join(str(text).replace('\n', ' ').split())


def split_summary_segments(text):
    clean_text = normalize_summary_text(text)
    if not clean_text:
        return []

    segments = []
    for segment in re.split(r'[.!?\n\u05c3]+', clean_text):
        segment = segment.strip(' ,;:-')
        if len(segment) >= 18:
            segments.append(segment)
    return segments


def extract_background_sentence(text):
    segments = split_summary_segments(text)
    if segments:
        return segments[0][:180].strip()
    return normalize_summary_text(text)[:180].strip()


def trim_summary_segment(segment, limit=140):
    segment = normalize_summary_text(segment)
    if len(segment) <= limit:
        return segment.rstrip(' ,;:')

    trimmed = segment[:limit].rsplit(' ', 1)[0].rstrip(' ,;:')
    return f'{trimmed}...'


def find_best_summary_segment(texts, patient_name, keywords, prefer_earlier=True):
    best_segment = ''
    best_score = -1
    normalized_name = normalize_summary_text(patient_name)

    for index, text in enumerate(texts):
        for segment in split_summary_segments(text):
            score = 0
            for keyword in keywords:
                if keyword in segment:
                    score += 2
            if normalized_name and normalized_name in segment:
                score += 2
            if prefer_earlier:
                score += max(0, 4 - index)
            if score > best_score:
                best_score = score
                best_segment = segment

    return trim_summary_segment(best_segment) if best_score > 0 else ''


def pick_top_summary_topics(texts, topics, limit):
    counts = Counter()
    for text in texts:
        clean_text = normalize_summary_text(text)
        for label, keywords in topics.items():
            hits = sum(clean_text.count(keyword) for keyword in keywords)
            if hits:
                counts[label] += hits

    return [label for label, _ in counts.most_common(limit)]


def extract_age_fact(texts, patient_name):
    if not patient_name:
        return ''

    escaped_name = re.escape(patient_name)
    patterns = [
        rf'{escaped_name}[^.!?\n]{{0,40}}?\b(בן|בת)\s+(\d{{1,2}})\b',
        rf'\b(בן|בת)\s+(\d{{1,2}})\b[^.!?\n]{{0,40}}?{escaped_name}'
    ]

    for text in texts[:4]:
        clean_text = normalize_summary_text(text)
        for pattern in patterns:
            match = re.search(pattern, clean_text)
            if match:
                return f"גיל מתועד: {match.group(1)} {match.group(2)}"

    return 'גיל מדויק לא תועד במפורש'


def extract_occupation_fact(texts, patient_name):
    segment = find_best_summary_segment(
        texts,
        patient_name,
        ['עובד', 'עובדת', 'עבודה', 'לומד', 'לומדת', 'מכללה', 'מפעל', 'תפקיד', 'מנהל', 'מנהלת', 'צבא'],
        prefer_earlier=True
    )
    if not segment:
        return ''
    return f'בהיבט התפקודי/תעסוקתי עלה כי {segment}'


def extract_children_count(corpus):
    match = re.search(r'(?:יש\s+ל[וה]\s+|אם\s+ל|אב\s+ל)(\d+|אחד|אחת|שני|שניים|שתיים|שתי|שלושה|שלוש|ארבעה|ארבע|חמישה|חמש)\s+ילדים', corpus)
    if not match:
        return ''

    raw_count = match.group(1)
    return HEBREW_NUMBER_WORDS.get(raw_count, raw_count)


def extract_family_fact(texts):
    corpus = ' '.join(normalize_summary_text(text) for text in texts if text)
    facts = []

    if any(keyword in corpus for keyword in ['בעלה שנפטר', 'פטירת האב', 'פטירה של בעל', 'בן זוגה שנפטר', 'בעלה נפטר']):
        facts.append('מתמודד/ת עם אובדן בן או בת הזוג')

    children_count = extract_children_count(corpus)
    if children_count:
        facts.append(f'הורה ל-{children_count} ילדים')
    elif 'ילדים' in corpus or 'ילדיה' in corpus:
        facts.append('יחסיו/ה עם הילדים הם מוקד משמעותי')

    if any(keyword in corpus for keyword in ['אמא', 'אביה', 'אביו', 'אחים', 'אחיו', 'אחיה', 'משפחת המקור']):
        facts.append('עולה עיסוק משמעותי גם במשפחת המקור')

    return '; '.join(facts[:3])


def extract_recent_focus(notes):
    recent_texts = []
    for note in notes[-3:]:
        if note['mood_summary']:
            recent_texts.append(note['mood_summary'])
        if note['content']:
            recent_texts.append(note['content'])

    recent_topics = pick_top_summary_topics(recent_texts, BACKGROUND_THEME_TOPICS, 2)
    if recent_topics:
        return ', '.join(recent_topics)

    if notes:
        return extract_background_sentence(notes[-1]['mood_summary'] or notes[-1]['content'])
    return ''


def parse_intake_questionnaire(raw_value):
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        return {}
    return {}


def intake_form_fields():
    return [
        'meeting_location', 'meeting_time', 'meeting_duration', 'meeting_conductor',
        'main_complaint', 'problem_history', 'early_anamnesis', 'referral_source', 'referral_date',
        'family_status', 'guardian_status', 'guardian_by_whom', 'living_with', 'living_with_other',
        'disability_status', 'disability_percent', 'self_harm_level', 'self_harm_recent', 'self_harm_count',
        'forced_treatment', 'substance_use', 'medical_cannabis', 'alcohol_use',
        'medical_conditions', 'psychiatric_conditions',
        'appearance_fit', 'appearance_fit_note', 'appearance_ordered', 'appearance_ordered_note',
        'cooperation', 'cooperation_note', 'eye_contact', 'eye_contact_note',
        'behavior_normal', 'behavior_note', 'speech_style', 'speech_note',
        'mood', 'mood_note', 'affect_match', 'affect_state', 'affect_note',
        'thinking_normal', 'thinking_rate', 'thinking_sequence', 'thinking_content',
        'perception_normal', 'perception_abnormal', 'reality_testing', 'judgment', 'self_insight',
        'orientation', 'memory',
        'referral_target', 'referral_details', 'patient_consent',
        'treatment_approach', 'treatment_frequency', 'treatment_estimated_duration'
    ]


def intake_data_from_request(form):
    if not any(key.startswith('intake_') for key in form.keys()):
        return None
    data = {}
    for key in intake_form_fields():
        raw = form.get(f'intake_{key}', '')
        data[key] = (raw or '').strip()
    return data


def serialize_intake_assessment(data):
    main_complaint = data.get('main_complaint', '')
    problem_history = data.get('problem_history', '')
    early_anamnesis = data.get('early_anamnesis', '')
    parts = []
    if main_complaint:
        parts.append(f"Main complaint:\n{main_complaint}")
    if problem_history:
        parts.append(f"Problem history / current illness:\n{problem_history}")
    if early_anamnesis:
        parts.append(f"Early anamnesis:\n{early_anamnesis}")
    return '\n\n'.join(parts).strip()


def add_intake_section_heading(doc, title):
    heading = doc.add_paragraph()
    heading.add_run(title).bold = True


def add_intake_line(doc, label, value):
    cleaned = (value or '').strip()
    if not cleaned:
        return
    paragraph = doc.add_paragraph()
    paragraph.add_run(f'{label}: ').bold = True
    paragraph.add_run(cleaned)


def build_intake_docx(patient_name, data):
    doc = Document()
    doc.add_heading(f'Intake Evaluation - {patient_name}', level=1)

    add_intake_section_heading(doc, 'Preliminary Details')
    add_intake_line(doc, 'Meeting location', data.get('meeting_location'))
    add_intake_line(doc, 'Meeting time', data.get('meeting_time'))
    add_intake_line(doc, 'Duration', data.get('meeting_duration'))
    add_intake_line(doc, 'Conducted by', data.get('meeting_conductor'))

    add_intake_section_heading(doc, 'Background / Referral Reason')
    add_intake_line(doc, 'Main complaint', data.get('main_complaint'))
    add_intake_line(doc, 'Problem history / current illness', data.get('problem_history'))
    add_intake_line(doc, 'Early anamnesis', data.get('early_anamnesis'))
    add_intake_line(doc, 'Referral source', data.get('referral_source'))
    add_intake_line(doc, 'Referral date', data.get('referral_date'))

    add_intake_section_heading(doc, 'Administrative Anamnesis')
    add_intake_line(doc, 'Family status', data.get('family_status'))
    add_intake_line(doc, 'Guardian status', data.get('guardian_status'))
    add_intake_line(doc, 'Guardian details', data.get('guardian_by_whom'))
    add_intake_line(doc, 'Living arrangement', data.get('living_with'))
    add_intake_line(doc, 'Living arrangement (other)', data.get('living_with_other'))
    add_intake_line(doc, 'Disability status', data.get('disability_status'))
    add_intake_line(doc, 'Disability percent', data.get('disability_percent'))
    add_intake_line(doc, 'Self-harm level', data.get('self_harm_level'))
    add_intake_line(doc, 'Self-harm recent timing', data.get('self_harm_recent'))
    add_intake_line(doc, 'Self-harm number of cases', data.get('self_harm_count'))
    add_intake_line(doc, 'Forced treatment history', data.get('forced_treatment'))
    add_intake_line(doc, 'Substance use', data.get('substance_use'))
    add_intake_line(doc, 'Medical cannabis', data.get('medical_cannabis'))
    add_intake_line(doc, 'Alcohol use', data.get('alcohol_use'))

    add_intake_section_heading(doc, 'Medical Anamnesis')
    add_intake_line(doc, 'Medical background conditions', data.get('medical_conditions'))
    add_intake_line(doc, 'Psychiatric conditions and history', data.get('psychiatric_conditions'))

    add_intake_section_heading(doc, 'Mental Status')
    add_intake_line(doc, 'Appearance - fit', data.get('appearance_fit'))
    add_intake_line(doc, 'Appearance - fit note', data.get('appearance_fit_note'))
    add_intake_line(doc, 'Appearance - ordered', data.get('appearance_ordered'))
    add_intake_line(doc, 'Appearance - ordered note', data.get('appearance_ordered_note'))
    add_intake_line(doc, 'Cooperation', data.get('cooperation'))
    add_intake_line(doc, 'Cooperation note', data.get('cooperation_note'))
    add_intake_line(doc, 'Eye contact', data.get('eye_contact'))
    add_intake_line(doc, 'Eye contact note', data.get('eye_contact_note'))
    add_intake_line(doc, 'Behavior', data.get('behavior_normal'))
    add_intake_line(doc, 'Behavior note', data.get('behavior_note'))
    add_intake_line(doc, 'Speech', data.get('speech_style'))
    add_intake_line(doc, 'Speech note', data.get('speech_note'))
    add_intake_line(doc, 'Mood', data.get('mood'))
    add_intake_line(doc, 'Mood note', data.get('mood_note'))
    add_intake_line(doc, 'Affect congruence', data.get('affect_match'))
    add_intake_line(doc, 'Affect state', data.get('affect_state'))
    add_intake_line(doc, 'Affect note', data.get('affect_note'))
    add_intake_line(doc, 'Thinking normal', data.get('thinking_normal'))
    add_intake_line(doc, 'Thinking rate', data.get('thinking_rate'))
    add_intake_line(doc, 'Thinking sequence', data.get('thinking_sequence'))
    add_intake_line(doc, 'Thinking content', data.get('thinking_content'))
    add_intake_line(doc, 'Perception normal', data.get('perception_normal'))
    add_intake_line(doc, 'Perception abnormal type', data.get('perception_abnormal'))
    add_intake_line(doc, 'Reality testing', data.get('reality_testing'))
    add_intake_line(doc, 'Judgment', data.get('judgment'))
    add_intake_line(doc, 'Self insight', data.get('self_insight'))
    add_intake_line(doc, 'Orientation', data.get('orientation'))
    add_intake_line(doc, 'Memory', data.get('memory'))

    add_intake_section_heading(doc, 'Treatment Decisions')
    add_intake_line(doc, 'Referral target', data.get('referral_target'))
    add_intake_line(doc, 'Referral details', data.get('referral_details'))
    add_intake_line(doc, 'Patient consent', data.get('patient_consent'))
    add_intake_line(doc, 'Treatment approach', data.get('treatment_approach'))
    add_intake_line(doc, 'Meeting frequency', data.get('treatment_frequency'))
    add_intake_line(doc, 'Estimated treatment duration', data.get('treatment_estimated_duration'))

    return doc


def build_patient_background_from_notes(db, patient_id, patient_name=None):
    if patient_name is None:
        patient_row = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
        patient_name = patient_row['name'] if patient_row else 'המטופל/ת'

    patient_row = db.execute('''
        SELECT intake_assessment, intake_questionnaire
        FROM patients
        WHERE id = ?
    ''', (patient_id,)).fetchone()

    notes = db.execute('''
        SELECT note_date, content, mood_summary, created_at
        FROM notes
        WHERE patient_id = ?
        ORDER BY COALESCE(note_date, date(created_at)) ASC, created_at ASC
    ''', (patient_id,)).fetchall()

    if not notes:
        intake_questionnaire = parse_intake_questionnaire(patient_row['intake_questionnaire'] if patient_row else None)
        main_complaint = (intake_questionnaire.get('main_complaint') or '').strip()
        problem_history = (intake_questionnaire.get('problem_history') or '').strip()
        intake_assessment = (patient_row['intake_assessment'] if patient_row else '') or ''

        main_problem = main_complaint or problem_history
        if not main_problem and intake_assessment.strip():
            main_problem = intake_assessment.strip().splitlines()[0]

        if main_problem:
            return (
                f"{patient_name}: מידע עיקרי מבוסס אינטייק ראשוני (טרם תועדו מפגשים שוטפים). "
                f"הבעיה המרכזית כיום: {main_problem}."
            )
        return 'לא נמצאה היסטוריה טיפולית מתועדת במערכת.'

    note_texts = []
    for note in notes:
        note_texts.append(note['content'])
        if note['mood_summary']:
            note_texts.append(note['mood_summary'])

    first_date = notes[0]['note_date']
    last_date = notes[-1]['note_date']

    if first_date and last_date:
        timeframe = f" בין {first_date} ל-{last_date}"
    elif last_date:
        timeframe = f" עד המפגש האחרון המתועד ב-{last_date}"
    else:
        timeframe = ''

    age_fact = extract_age_fact(note_texts, patient_name)
    occupation_fact = extract_occupation_fact(note_texts, patient_name)
    family_fact = extract_family_fact(note_texts)
    reason_topics = pick_top_summary_topics(note_texts[:8], BACKGROUND_REASON_TOPICS, 2)
    theme_topics = pick_top_summary_topics(note_texts, BACKGROUND_THEME_TOPICS, 2)
    recent_focus = extract_recent_focus(notes)

    intake_questionnaire = parse_intake_questionnaire(patient_row['intake_questionnaire'] if patient_row else None)
    main_complaint = (intake_questionnaire.get('main_complaint') or '').strip()
    problem_history = (intake_questionnaire.get('problem_history') or '').strip()

    intake_assessment = (patient_row['intake_assessment'] if patient_row else '') or ''
    intake_problem_line = ''
    if intake_assessment:
        for line in intake_assessment.splitlines():
            cleaned = line.strip()
            if cleaned and not cleaned.lower().startswith('main complaint:'):
                intake_problem_line = cleaned
                break

    if main_complaint:
        main_problem = main_complaint
    elif problem_history:
        main_problem = problem_history
    elif intake_problem_line:
        main_problem = intake_problem_line
    elif reason_topics:
        main_problem = f"קושי מרכזי סביב {', '.join(reason_topics)}"
    elif theme_topics:
        main_problem = f"מוקד קושי חוזר סביב {', '.join(theme_topics)}"
    elif recent_focus:
        main_problem = recent_focus
    else:
        main_problem = extract_background_sentence(notes[-1]['mood_summary'] or notes[-1]['content'])

    parts = [f"{patient_name} נמצא/ת במעקב טיפולי מתועד הכולל {len(notes)} מפגשים{timeframe}."]

    identity_parts = [age_fact]
    if occupation_fact:
        identity_parts.append(occupation_fact)
    if family_fact:
        identity_parts.append(family_fact)
    parts.append(f"פרטים מרכזיים שעלו בתיעוד: {'; '.join(identity_parts)}.")

    if reason_topics:
        parts.append(f"מוקדי קושי בולטים: {', '.join(reason_topics)}.")
    if theme_topics:
        parts.append(f"נושאים חוזרים בטיפול: {', '.join(theme_topics)}.")
    if recent_focus:
        parts.append(f"מיקוד עדכני: {recent_focus}.")

    parts.append(f"הבעיה המרכזית כיום: {main_problem}.")

    return ' '.join(part.strip() for part in parts if part).strip()


def _normalize_session_number(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return str(int(raw))
    except (TypeError, ValueError):
        return raw


def _has_meaningful_note_information(content_text, mood_summary, behavior_notes, appearance_text, checklist_text):
    placeholders = {
        '',
        'n/a',
        'na',
        'none',
        'unknown',
        'yyyy-mm-dd',
        'brief mood summary.',
        'short behavior notes.',
        'general appearance observations.',
    }

    values = [content_text, mood_summary, behavior_notes, appearance_text, checklist_text]
    for value in values:
        cleaned = (value or '').strip().lower()
        if cleaned and cleaned not in placeholders:
            return True
    return False


def fetch_patients_by_status(db, status, patient_type='all', search_query='', sort_by='status_priority'):
    base_query = '''
        SELECT p.*,
        (SELECT COUNT(*) FROM appointments a WHERE a.patient_id = p.id AND a.is_recurring = 1 AND COALESCE(a.status, 'scheduled') = 'scheduled') as has_recurring,
        (
            CASE
                WHEN p.status = 'candidate' AND EXISTS (
                    SELECT 1 FROM appointments a1
                    WHERE a1.patient_id = p.id
                      AND a1.is_recurring = 0
                      AND COALESCE(a1.status, 'scheduled') = 'scheduled'
                      AND a1.appointment_date < DATE('now')
                ) AND NOT EXISTS (
                    SELECT 1 FROM appointments a2
                    WHERE a2.patient_id = p.id
                      AND COALESCE(a2.status, 'scheduled') = 'scheduled'
                      AND a2.appointment_date >= DATE('now')
                )
                THEN 1
                ELSE 0
            END
        ) AS needs_followup_decision,
        (
            SELECT GROUP_CONCAT(g.name, ', ')
            FROM group_members gm
            JOIN groups g ON g.id = gm.group_id
            WHERE gm.patient_id = p.id
              AND gm.left_at IS NULL
              AND COALESCE(g.is_active, 1) = 1
        ) AS group_names,
        (
            SELECT GROUP_CONCAT(COALESCE(gm.role, 'member'), ', ')
            FROM group_members gm
            JOIN groups g ON g.id = gm.group_id
            WHERE gm.patient_id = p.id
              AND gm.left_at IS NULL
              AND COALESCE(g.is_active, 1) = 1
        ) AS group_roles
        FROM patients p
        WHERE COALESCE(p.is_deleted, 0) = 0
    '''

    params = []

    if status in ['candidate', 'waiting for scheduling', 'waiting']:
        base_query += " AND p.status IN ('candidate', 'waiting for scheduling', 'waiting')"
    elif status != 'all':
        base_query += ' AND p.status = ?'
        params.append(status)

    if patient_type in ('private', 'residency', 'initial-intake', 'group'):
        base_query += ' AND COALESCE(p.patient_type, \"private\") = ?'
        params.append(patient_type)

    if search_query:
        base_query += ' AND (LOWER(p.name) LIKE ? OR LOWER(COALESCE(p.email, \"\")) LIKE ? OR LOWER(COALESCE(p.phone, \"\")) LIKE ?)'
        like_value = f"%{search_query.lower()}%"
        params.extend([like_value, like_value, like_value])

    order_map = {
        'name_asc': 'p.name ASC',
        'name_desc': 'p.name DESC',
        'newest': 'p.created_at DESC',
        'oldest': 'p.created_at ASC',
        'status_priority': '''
            CASE
                WHEN p.status = 'ongoing' THEN 0
                WHEN p.status IN ('candidate', 'waiting for scheduling', 'waiting') THEN 1
                WHEN p.status = 'archived' THEN 2
                ELSE 3
            END ASC,
            p.created_at DESC
        '''
    }
    order_clause = order_map.get(sort_by, order_map['status_priority'])

    final_query = f"{base_query} ORDER BY {order_clause}"
    return db.execute(final_query, tuple(params)).fetchall()


@app.route('/crm')
@login_required
def crm_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('patient_home'))

    db = get_db()
    saved_filters = session.get('crm_filters', {})
    status = request.args.get('status', saved_filters.get('status', 'all')).strip()
    patient_type = request.args.get('patient_type', saved_filters.get('patient_type', 'all')).strip()
    search_query = request.args.get('q', saved_filters.get('q', '')).strip()
    sort_by = request.args.get('sort', saved_filters.get('sort', 'status_priority')).strip()

    if status not in {'all', 'ongoing', 'candidate', 'waiting', 'waiting for scheduling', 'archived'}:
        status = 'all'
    if patient_type not in {'all', 'private', 'residency', 'initial-intake', 'group'}:
        patient_type = 'all'
    if sort_by not in {'status_priority', 'name_asc', 'name_desc', 'newest', 'oldest'}:
        sort_by = 'status_priority'

    session['crm_filters'] = {
        'status': status,
        'patient_type': patient_type,
        'q': search_query,
        'sort': sort_by
    }

    patients = fetch_patients_by_status(db, status, patient_type=patient_type, search_query=search_query, sort_by=sort_by)
    counts = {
        'all': db.execute('SELECT COUNT(*) AS c FROM patients WHERE COALESCE(is_deleted, 0) = 0').fetchone()['c'],
        'ongoing': db.execute("SELECT COUNT(*) AS c FROM patients WHERE status = 'ongoing' AND COALESCE(is_deleted, 0) = 0").fetchone()['c'],
        'candidate_waiting': db.execute("SELECT COUNT(*) AS c FROM patients WHERE status IN ('candidate', 'waiting for scheduling', 'waiting') AND COALESCE(is_deleted, 0) = 0").fetchone()['c'],
        'archived': db.execute("SELECT COUNT(*) AS c FROM patients WHERE status = 'archived' AND COALESCE(is_deleted, 0) = 0").fetchone()['c']
    }
    return render_template('crm.html', patients=patients, status=status, counts=counts,
                           patient_type=patient_type, search_query=search_query, sort_by=sort_by)

@app.route('/patient/home')
@login_required
def patient_home():
    if current_user.role != 'patient':
        return redirect(url_for('patients'))

    db = get_db()
    patient_id = current_user.patient_id
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()

    today = datetime.now().strftime('%Y-%m-%d')
    upcoming = db.execute('''
        SELECT * FROM appointments
        WHERE patient_id = ? AND appointment_date >= ?
        ORDER BY appointment_date ASC, appointment_time ASC
        LIMIT 10
    ''', (patient_id, today)).fetchall()

    messages = db.execute('''
        SELECT m.*, u.username as sender_name
        FROM messages m
        LEFT JOIN users u ON m.sender_id = u.id
        WHERE m.sender_id = ? OR m.recipient_id = ?
        ORDER BY m.timestamp DESC
        LIMIT 20
    ''', (current_user.id, current_user.id)).fetchall()

    assigned_resources = db.execute('''
        SELECT r.*
        FROM resources r
        JOIN patient_resources pr ON r.id = pr.resource_id
        WHERE pr.patient_id = ?
        ORDER BY pr.assigned_at DESC
    ''', (patient_id,)).fetchall()

    db.execute('UPDATE messages SET is_read = 1 WHERE recipient_id = ?', (current_user.id,))
    db.commit()

    return render_template('patient_home.html', patient=patient,
                           upcoming=upcoming, messages=messages,
                           assigned_resources=assigned_resources)

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

    return redirect_to_patient_tab(patient_id, 'info')

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
                return redirect(url_for('patient_home'))
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
        return redirect(url_for('patient_home'))
    status = request.args.get('status', 'all')
    return redirect(url_for('crm_dashboard', status=status))

@app.route('/add_patient', methods=('GET', 'POST'))
@login_required
def add_patient():
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('patient_home'))

    if request.method == 'POST':
        name = request.form['name']
        status = request.form['status']
        email = request.form.get('email')
        phone = request.form.get('phone')
        birth_date = request.form.get('birth_date') or None
        id_number = (request.form.get('id_number') or '').strip() or None
        patient_type = request.form.get('patient_type', 'private')
        if patient_type not in ('private', 'residency', 'initial-intake', 'group'):
            patient_type = 'private'
        has_intake_tab = 1 if patient_type == 'initial-intake' else 0
        intake_assessment = request.form.get('intake_assessment', '').strip() if patient_type == 'initial-intake' else ''
        intake_questionnaire = request.form.get('intake_questionnaire', '').strip() if patient_type == 'initial-intake' else ''

        if not name:
            flash('Name is required!')
        else:
            db = get_db()
            db.execute('''INSERT INTO patients
                                  (name, status, email, phone, birth_date, id_number, patient_type, has_intake_tab, intake_assessment, intake_questionnaire)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                              (name, status, email, phone, birth_date, id_number, patient_type, has_intake_tab,
                               intake_assessment or None, intake_questionnaire or None))
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
         return redirect(url_for('patient_home'))

    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0', (patient_id,)).fetchone()
    if patient is None:
        return "Patient not found", 404

    # Fetch user account if exists
    user = db.execute('SELECT * FROM users WHERE patient_id = ?', (patient_id,)).fetchone()

    notes = db.execute('''
        SELECT * FROM notes
        WHERE patient_id = ?
        ORDER BY COALESCE(note_date, date(created_at)) DESC,
                 CAST(COALESCE(session_number, '0') AS INTEGER) DESC,
                 created_at DESC
    ''', (patient_id,)).fetchall()
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

    behavior_options = [
        'Calm', 'Anxious', 'Restless', 'Withdrawn', 'Cooperative', 'Engaged', 'Low Energy', 'Irritable'
    ]
    latest_behavior = {
        'patient_appearance': '',
        'behavior_checklist': set(),
        'mood_summary': '',
        'behavior_notes': ''
    }
    if notes:
        latest_behavior['patient_appearance'] = notes[0]['patient_appearance'] or ''
        latest_behavior['mood_summary'] = notes[0]['mood_summary'] or ''
        latest_behavior['behavior_notes'] = notes[0]['behavior_notes'] or ''
        checklist_raw = notes[0]['behavior_checklist'] or ''
        latest_behavior['behavior_checklist'] = {
            item.strip() for item in checklist_raw.split(',') if item.strip()
        }

    active_tab = request.args.get('tab', 'info')
    intake_enabled = patient['patient_type'] == 'initial-intake' or int(patient['has_intake_tab'] or 0) == 1
    if active_tab == 'intake' and not intake_enabled:
        active_tab = 'info'
    latest_note = notes[0] if notes else None
    intake_form_data = parse_intake_questionnaire(patient['intake_questionnaire'])
    next_session_row = db.execute('''
        SELECT COALESCE(MAX(CAST(COALESCE(session_number, '0') AS INTEGER)), 0) AS max_session
        FROM notes
        WHERE patient_id = ?
    ''', (patient_id,)).fetchone()
    suggested_session_number = int(next_session_row['max_session'] or 0) + 1
    suggested_note_date = datetime.now().date().isoformat()

    return render_template('patient_detail.html', patient=patient, notes=notes, files=files, receipts=receipts, user=user, appointments=appointments, messages=messages, all_resources=all_resources, assigned_resources=assigned_resources, active_tab=active_tab, behavior_options=behavior_options, latest_behavior=latest_behavior, latest_note=latest_note, suggested_session_number=suggested_session_number, suggested_note_date=suggested_note_date, intake_form_data=intake_form_data)


def redirect_to_patient_tab(patient_id, default_tab='info'):
    tab = request.form.get('active_tab') or request.args.get('tab') or default_tab
    return redirect(url_for('patient_detail', patient_id=patient_id, tab=tab))


def parse_date_safe(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_time_safe(value):
    if not value:
        return None
    raw = value.strip()
    formats = ['%H:%M', '%H:%M:%S']
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def custom_weekday(date_obj):
    # 0=Sunday, 6=Saturday
    return (date_obj.weekday() + 1) % 7


def combine_dt(date_obj, time_str):
    parsed_time = parse_time_safe((time_str or '').strip()[:5])
    if not parsed_time:
        parsed_time = datetime.strptime('00:00', '%H:%M').time()
    return datetime.combine(date_obj, parsed_time)


def daterange(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def calendar_allowed_windows(day_code):
    # 0=Sunday ... 6=Saturday
    # Requested clinic availability:
    # Sunday: 14:00-15:00
    # Monday: 09:00-10:00, 12:30-13:30
    # Tuesday: fully blocked
    # Wednesday: fully blocked
    # Thursday: 10:00-15:00, 19:00-20:00
    # Friday/Saturday: no regular slots
    if day_code == 0:
        return [('14:00', '15:00')]
    if day_code == 1:
        return [('09:00', '10:00'), ('12:30', '13:30')]
    if day_code in (2, 3):
        return []
    if day_code == 4:
        return [('10:00', '15:00'), ('19:00', '20:00')]
    return []


def parse_recurrence_days(appt):
    raw = (appt['recurrence_days'] or '').strip()
    if raw:
        days = []
        for part in raw.split(','):
            part = part.strip()
            if part.isdigit():
                val = int(part)
                if 0 <= val <= 6:
                    days.append(val)
        if days:
            return sorted(set(days))

    base_date = parse_date_safe(appt['appointment_date'])
    if not base_date:
        return [0]
    return [custom_weekday(base_date)]


def recurring_occurrences_for_week(appt, week_start, week_end):
    base_date = parse_date_safe(appt['appointment_date'])
    if not base_date:
        return []

    interval = int(appt['recurrence_interval'] or 1)
    if interval <= 0:
        interval = 1

    recurrence_end = parse_date_safe(appt['recurrence_end_date'])
    recurrence_count = int(appt['recurrence_count'] or 0)
    days = parse_recurrence_days(appt)

    anchor_week_start = base_date - timedelta(days=custom_weekday(base_date))
    result = []
    produced = 0
    week_index = 0

    while True:
        block_week_start = anchor_week_start + timedelta(weeks=week_index * interval)
        if block_week_start > week_end:
            break

        for day_code in days:
            occ_date = block_week_start + timedelta(days=day_code)
            if occ_date < base_date:
                continue
            if recurrence_end and occ_date > recurrence_end:
                continue

            produced += 1
            if recurrence_count and produced > recurrence_count:
                return result

            if week_start <= occ_date <= week_end:
                result.append(occ_date)

        week_index += 1

    return sorted(result)


def overlaps(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def has_time_conflict(db, day_obj, start_dt, end_dt, exclude_appointment_id=None, exclude_group_session_id=None, exclude_block_id=None):
    day_iso = day_obj.isoformat()

    appointment_rows = db.execute('''
        SELECT id, appointment_time, duration_minutes
        FROM appointments
        WHERE appointment_date = ?
    ''', (day_iso,)).fetchall()
    for row in appointment_rows:
        if exclude_appointment_id and int(row['id']) == int(exclude_appointment_id):
            continue
        row_start = combine_dt(day_obj, row['appointment_time'])
        row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
        if overlaps(start_dt, end_dt, row_start, row_end):
            return 'Time overlaps an existing appointment.'

    block_rows = db.execute('''
        SELECT id, blocked_time, duration_minutes
        FROM blocked_slots
        WHERE blocked_date = ?
    ''', (day_iso,)).fetchall()
    for row in block_rows:
        if exclude_block_id and int(row['id']) == int(exclude_block_id):
            continue
        row_start = combine_dt(day_obj, row['blocked_time'])
        row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
        if overlaps(start_dt, end_dt, row_start, row_end):
            return 'Time overlaps a blocked slot.'

    group_rows = db.execute('''
        SELECT id, session_time, duration_minutes
        FROM group_sessions
        WHERE session_date = ?
          AND COALESCE(status, 'scheduled') = 'scheduled'
    ''', (day_iso,)).fetchall()
    for row in group_rows:
        if exclude_group_session_id and int(row['id']) == int(exclude_group_session_id):
            continue
        row_start = combine_dt(day_obj, row['session_time'])
        row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
        if overlaps(start_dt, end_dt, row_start, row_end):
            return 'Time overlaps an existing group session.'

    return None


def ensure_ongoing_recurrence_from_previous_week(db, reference_date=None):
    """Promote last week's one-time meeting to weekly recurring for ongoing patients."""
    today = reference_date or datetime.now().date()
    current_week_start = today - timedelta(days=custom_weekday(today))
    prev_week_start = current_week_start - timedelta(days=7)
    prev_week_end = current_week_start - timedelta(days=1)

    candidate_rows = db.execute('''
        SELECT a.id AS appointment_id, a.patient_id, a.appointment_date, a.appointment_time
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE p.status = 'ongoing'
          AND COALESCE(p.patient_type, 'private') != 'initial-intake'
          AND COALESCE(a.status, 'scheduled') = 'scheduled'
          AND COALESCE(a.is_recurring, 0) = 0
          AND a.appointment_date BETWEEN ? AND ?
        ORDER BY a.patient_id ASC, a.appointment_date DESC, a.id DESC
    ''', (prev_week_start.isoformat(), prev_week_end.isoformat())).fetchall()

    latest_by_patient = {}
    for row in candidate_rows:
        if row['patient_id'] not in latest_by_patient:
            latest_by_patient[row['patient_id']] = row

    if not latest_by_patient:
        return 0

    converted = 0
    for patient_id, row in latest_by_patient.items():
        has_recurring = db.execute('''
            SELECT 1
            FROM appointments
            WHERE patient_id = ?
              AND COALESCE(status, 'scheduled') = 'scheduled'
              AND COALESCE(is_recurring, 0) = 1
            LIMIT 1
        ''', (patient_id,)).fetchone()
        if has_recurring:
            continue

        base_date = parse_date_safe(row['appointment_date'])
        if not base_date:
            continue

        recurrence_end = (base_date + timedelta(days=365)).isoformat()
        recurrence_day = str(custom_weekday(base_date))
        db.execute('''
            UPDATE appointments
            SET is_recurring = 1,
                recurrence_interval = 1,
                recurrence_days = ?,
                recurrence_end_date = ?,
                recurrence_count = NULL
            WHERE id = ?
        ''', (recurrence_day, recurrence_end, row['appointment_id']))
        converted += 1

    if converted:
        db.commit()
    return converted


def recurring_occurrences_between(appt, range_start, range_end, max_occurrences=600):
    base_date = parse_date_safe(appt['appointment_date'])
    if not base_date:
        return []

    interval = int(appt['recurrence_interval'] or 1)
    if interval <= 0:
        interval = 1

    recurrence_end = parse_date_safe(appt['recurrence_end_date'])
    recurrence_count = int(appt['recurrence_count'] or 0)
    days = parse_recurrence_days(appt)

    anchor_week_start = base_date - timedelta(days=custom_weekday(base_date))
    occurrences = []
    produced = 0
    week_index = 0

    while len(occurrences) < max_occurrences:
        block_week_start = anchor_week_start + timedelta(weeks=week_index * interval)
        if block_week_start > range_end:
            break

        for day_code in days:
            occ_date = block_week_start + timedelta(days=day_code)
            if occ_date < base_date:
                continue
            if recurrence_end and occ_date > recurrence_end:
                continue

            produced += 1
            if recurrence_count and produced > recurrence_count:
                return occurrences

            if range_start <= occ_date <= range_end:
                occurrences.append(occ_date)

        week_index += 1

    return sorted(occurrences)


def build_booking_management_payload(db, mode='upcoming', future_days=180, history_days=120):
    today = datetime.now().date()
    if mode == 'history':
        range_start = today - timedelta(days=history_days)
        range_end = today - timedelta(days=1)
        sort_reverse = True
    else:
        range_start = today
        range_end = today + timedelta(days=future_days)
        sort_reverse = False

    items = []

    appointment_rows = db.execute('''
        SELECT a.*, p.name AS patient_name, p.status AS patient_status
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE COALESCE(a.status, 'scheduled') = 'scheduled'
          AND ((COALESCE(a.is_recurring, 0) = 0 AND a.appointment_date BETWEEN ? AND ?)
               OR (COALESCE(a.is_recurring, 0) = 1 AND a.appointment_date <= ?))
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    ''', (range_start.isoformat(), range_end.isoformat(), range_end.isoformat())).fetchall()

    for appt in appointment_rows:
        is_recurring = int(appt['is_recurring'] or 0) == 1
        if is_recurring:
            occ_dates = recurring_occurrences_between(appt, range_start, range_end)
        else:
            occ_date = parse_date_safe(appt['appointment_date'])
            occ_dates = [occ_date] if occ_date else []

        for occ_date in occ_dates:
            start_dt = combine_dt(occ_date, appt['appointment_time'])
            duration = int(appt['duration_minutes'] or 60)
            end_dt = start_dt + timedelta(minutes=duration)
            items.append({
                'kind': 'appointment',
                'source_id': appt['id'],
                'occurrence_id': f"appointment-{appt['id']}-{occ_date.isoformat()}",
                'date': occ_date.isoformat(),
                'time': start_dt.strftime('%H:%M'),
                'end_time': end_dt.strftime('%H:%M'),
                'duration_minutes': duration,
                'title': appt['patient_name'],
                'type_label': 'Recurring Appointment' if is_recurring else 'Appointment',
                'status': appt['patient_status'] or '',
                'meeting_type': appt['meeting_type'] or 'in-person',
                'meeting_link': appt['meeting_link'] or '',
                'meeting_title': appt['meeting_title'] or '',
                'is_recurring': is_recurring,
                'can_edit': True,
                'can_delete': True
            })

    block_rows = db.execute('''
        SELECT *
        FROM blocked_slots
        WHERE blocked_date BETWEEN ? AND ?
        ORDER BY blocked_date ASC, blocked_time ASC
    ''', (range_start.isoformat(), range_end.isoformat())).fetchall()

    for block in block_rows:
        block_date = parse_date_safe(block['blocked_date'])
        if not block_date:
            continue
        start_dt = combine_dt(block_date, block['blocked_time'])
        duration = int(block['duration_minutes'] or 60)
        end_dt = start_dt + timedelta(minutes=duration)
        block_type = (block['block_type'] or 'blocked').strip().lower()
        items.append({
            'kind': 'block',
            'source_id': block['id'],
            'occurrence_id': f"block-{block['id']}",
            'date': block_date.isoformat(),
            'time': start_dt.strftime('%H:%M'),
            'end_time': end_dt.strftime('%H:%M'),
            'duration_minutes': duration,
            'title': block['title'] or ('Special Occasion' if block_type == 'special' else 'Blocked Slot'),
            'type_label': 'Special' if block_type == 'special' else 'Blocked',
            'status': '',
            'meeting_type': '',
            'meeting_link': '',
            'meeting_title': '',
            'is_recurring': False,
            'block_type': block_type,
            'is_private': int(block['is_private'] or 0),
            'can_edit': True,
            'can_delete': True
        })

    group_rows = db.execute('''
        SELECT gs.*, g.name AS group_name
        FROM group_sessions gs
        JOIN groups g ON g.id = gs.group_id
        WHERE COALESCE(gs.status, 'scheduled') = 'scheduled'
          AND gs.session_date BETWEEN ? AND ?
        ORDER BY gs.session_date ASC, gs.session_time ASC
    ''', (range_start.isoformat(), range_end.isoformat())).fetchall()

    for row in group_rows:
        session_date = parse_date_safe(row['session_date'])
        if not session_date:
            continue
        start_dt = combine_dt(session_date, row['session_time'])
        duration = int(row['duration_minutes'] or 60)
        end_dt = start_dt + timedelta(minutes=duration)
        items.append({
            'kind': 'group_session',
            'source_id': row['id'],
            'occurrence_id': f"group-session-{row['id']}",
            'date': session_date.isoformat(),
            'time': start_dt.strftime('%H:%M'),
            'end_time': end_dt.strftime('%H:%M'),
            'duration_minutes': duration,
            'title': row['title'] or f"Group: {row['group_name']}",
            'type_label': 'Group Session',
            'status': row['group_name'],
            'meeting_type': row['meeting_type'] or 'in-person',
            'meeting_link': row['meeting_link'] or '',
            'meeting_title': row['title'] or '',
            'is_recurring': False,
            'can_edit': True,
            'can_delete': True
        })

    items.sort(key=lambda item: (item['date'], item['time']), reverse=sort_reverse)
    return {
        'mode': mode,
        'range_start': range_start.isoformat(),
        'range_end': range_end.isoformat(),
        'items': items
    }


def build_week_calendar_snapshot(db, week_start, user):
    week_end = week_start + timedelta(days=6)
    today = datetime.now().date()

    patients = {
        row['id']: row for row in db.execute('SELECT id, name, status, can_self_schedule FROM patients').fetchall()
    }

    appointment_rows = db.execute('''
        SELECT a.*, p.name AS patient_name, p.status AS patient_status, p.patient_type AS patient_type
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE (a.is_recurring = 0 AND a.appointment_date BETWEEN ? AND ?)
           OR (a.is_recurring = 1 AND a.appointment_date <= ?)
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    ''', (week_start.isoformat(), week_end.isoformat(), week_end.isoformat())).fetchall()

    blocks = db.execute('''
        SELECT * FROM blocked_slots
        WHERE blocked_date BETWEEN ? AND ?
        ORDER BY blocked_date ASC, blocked_time ASC
    ''', (week_start.isoformat(), week_end.isoformat())).fetchall()

    group_sessions = db.execute('''
        SELECT gs.*, g.name AS group_name
        FROM group_sessions gs
        JOIN groups g ON g.id = gs.group_id
        WHERE gs.session_date BETWEEN ? AND ?
          AND COALESCE(g.is_active, 1) = 1
          AND COALESCE(gs.status, 'scheduled') = 'scheduled'
        ORDER BY gs.session_date ASC, gs.session_time ASC
    ''', (week_start.isoformat(), week_end.isoformat())).fetchall()

    events = []
    occupied = []
    emitted_appointment_keys = set()
    weekend_specials = {'friday': [], 'saturday': []}
    follow_up_alerts = []

        # Candidate with a past one-time session and no future booking needs a decision.
    follow_up_rows = db.execute('''
        SELECT p.id AS patient_id, p.name, p.status, MAX(a.appointment_date) AS last_date
        FROM patients p
        JOIN appointments a ON a.patient_id = p.id
                WHERE p.status = 'candidate'
          AND a.is_recurring = 0
                    AND COALESCE(a.status, 'scheduled') = 'scheduled'
          AND a.appointment_date < ?
        GROUP BY p.id, p.name, p.status
    ''', (today.isoformat(),)).fetchall()

    for row in follow_up_rows:
        has_future = db.execute('''
            SELECT 1 FROM appointments
            WHERE patient_id = ? AND appointment_date >= ?
              AND COALESCE(status, 'scheduled') = 'scheduled'
            LIMIT 1
        ''', (row['patient_id'], today.isoformat())).fetchone()
        if not has_future:
            follow_up_alerts.append({
                'patient_id': row['patient_id'],
                'patient_name': row['name'],
                'status': row['status'],
                'last_meeting_date': row['last_date'],
                'message': 'Initial one-time meeting has passed with no next booking. Further decision is needed.'
            })

    for appt in appointment_rows:
        is_recurring = int(appt['is_recurring'] or 0) == 1
        occ_dates = recurring_occurrences_for_week(appt, week_start, week_end) if is_recurring else [parse_date_safe(appt['appointment_date'])]
        occ_dates = [d for d in occ_dates if d is not None]

        for occ_date in occ_dates:
            start_dt = combine_dt(occ_date, appt['appointment_time'])
            duration = int(appt['duration_minutes'] or 60)
            end_dt = start_dt + timedelta(minutes=duration)

            title = appt['patient_name']
            if user.role == 'patient' and appt['patient_id'] != user.patient_id:
                title = 'Unavailable'

            is_own = (user.role == 'patient' and appt['patient_id'] == user.patient_id)
            can_delete = user.role == 'admin' or is_own

            # Prevent duplicate renders when legacy data has multiple recurring rows
            # that resolve to the same patient+time occurrence in the same week.
            appointment_key = (appt['patient_id'], start_dt.isoformat(), end_dt.isoformat())
            if appointment_key in emitted_appointment_keys:
                continue
            emitted_appointment_keys.add(appointment_key)

            event_color = '#2563eb' if appt['patient_status'] == 'ongoing' else '#f59e0b'
            if appt['patient_status'] == 'archived':
                event_color = '#6b7280'

            platform = (appt['meeting_platform'] or '') if 'meeting_platform' in appt.keys() else ''
            meeting_title = (appt['meeting_title'] or '') if 'meeting_title' in appt.keys() else ''
            save_to_google = int(appt['save_to_google'] or 0) if 'save_to_google' in appt.keys() else 0
            events.append({
                'id': f"appointment-{appt['id']}-{occ_date.isoformat()}",
                'appointment_id': appt['id'],
                'patient_id': appt['patient_id'],
                'title': title,
                'start': start_dt.isoformat(),
                'end': end_dt.isoformat(),
                'editable': False,
                'color': event_color,
                'meta': {
                    'type': 'appointment',
                    'appointment_id': appt['id'],
                    'patient_id': appt['patient_id'],
                    'patient_name': appt['patient_name'],
                    'patient_status': appt['patient_status'],
                    'is_recurring': is_recurring,
                    'meeting_type': appt['meeting_type'],
                    'meeting_link': appt['meeting_link'],
                    'meeting_platform': platform,
                    'meeting_title': meeting_title,
                    'save_to_google': save_to_google,
                    'can_delete': can_delete
                }
            })
            occupied.append((start_dt, end_dt))

    for group_session in group_sessions:
        session_date = parse_date_safe(group_session['session_date'])
        if not session_date:
            continue

        session_start = combine_dt(session_date, group_session['session_time'])
        session_duration = int(group_session['duration_minutes'] or 60)
        session_end = session_start + timedelta(minutes=session_duration)

        events.append({
            'id': f"group-session-{group_session['id']}",
            'group_session_id': group_session['id'],
            'group_id': group_session['group_id'],
            'title': f"Group: {group_session['group_name']}",
            'start': session_start.isoformat(),
            'end': session_end.isoformat(),
            'editable': False,
            'color': '#8b5cf6',
            'meta': {
                'type': 'group_session',
                'group_session_id': group_session['id'],
                'session_date': group_session['session_date'],
                'session_time': group_session['session_time'],
                'duration_minutes': session_duration,
                'title': group_session['title'] or '',
                'facilitator': group_session['facilitator'] or '',
                'group_name': group_session['group_name'],
                'meeting_type': group_session['meeting_type'],
                'meeting_link': group_session['meeting_link'],
                'can_delete': user.role == 'admin',
                'can_edit': user.role == 'admin'
            }
        })
        occupied.append((session_start, session_end))

    for block in blocks:
        block_date = parse_date_safe(block['blocked_date'])
        if not block_date:
            continue
        start_dt = combine_dt(block_date, block['blocked_time'])
        duration = int(block['duration_minutes'] or 60)
        end_dt = start_dt + timedelta(minutes=duration)
        is_private = int(block['is_private'] or 0) == 1
        block_type = (block['block_type'] or 'blocked').strip().lower()
        raw_title = block['title'] or ('Blocked Slot' if block_type == 'blocked' else 'Special Occasion')
        visible_title = raw_title if (user.role == 'admin' or not is_private) else 'Unavailable'

        # Always mark blocked/special slots as occupied so they don't appear in available_slots.
        occupied.append((start_dt, end_dt))

        # Blocked durations are only shown to admin; patients should not see them at all.
        if user.role != 'admin':
            continue

        events.append({
            'id': f"block-{block['id']}",
            'block_id': block['id'],
            'title': visible_title,
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat(),
            'editable': False,
            'color': '#dc2626' if block_type == 'blocked' else '#7c3aed',
            'meta': {
                'type': 'block',
                'block_id': block['id'],
                'title': raw_title,
                'blocked_date': block['blocked_date'],
                'blocked_time': block['blocked_time'],
                'duration_minutes': duration,
                'block_type': block_type,
                'is_private': is_private,
                'can_edit': user.role == 'admin',
                'can_delete': user.role == 'admin'
            }
        })

        day_code = custom_weekday(block_date)
        if day_code == 5:
            weekend_specials['friday'].append({
                'id': block['id'],
                'title': visible_title,
                'time': block['blocked_time'],
                'duration': duration,
                'type': block_type
            })
        if day_code == 6:
            weekend_specials['saturday'].append({
                'id': block['id'],
                'title': visible_title,
                'time': block['blocked_time'],
                'duration': duration,
                'type': block_type
            })

    # Available slots are restricted to admin-enabled vacancy overrides.
    vacancy_rows = db.execute('''
        SELECT slot_date, slot_time, duration_minutes
        FROM slots_override
        WHERE status = 'available' AND slot_date BETWEEN ? AND ?
        ORDER BY slot_date ASC, slot_time ASC
    ''', (week_start.isoformat(), week_end.isoformat())).fetchall()

    available_slots = []
    seen_slots = set()
    for row in vacancy_rows:
        day = parse_date_safe(row['slot_date'])
        if not day:
            continue
        slot_time = (row['slot_time'] or '').strip()
        parsed = parse_time_safe(slot_time)
        if not parsed:
            continue
        duration = int(row['duration_minutes'] or 60)
        if duration <= 0:
            duration = 60

        slot_start = datetime.combine(day, parsed)
        slot_end = slot_start + timedelta(minutes=duration)
        slot_key = (day.isoformat(), slot_start.strftime('%H:%M'), duration)
        if slot_key in seen_slots:
            continue
        seen_slots.add(slot_key)

        if not any(overlaps(slot_start, slot_end, occ_start, occ_end) for occ_start, occ_end in occupied):
            available_slots.append({
                'date': day.isoformat(),
                'time': slot_start.strftime('%H:%M'),
                'duration_minutes': duration
            })
            # Show vacant slots as calendar events for admins
            if user.role == 'admin':
                events.append({
                    'id': f"vacancy-{day.isoformat()}-{slot_start.strftime('%H:%M')}",
                    'title': f"Vacant ({duration}min)",
                    'start': slot_start.isoformat(),
                    'end': slot_end.isoformat(),
                    'editable': False,
                    'color': '#10b981',
                    'meta': {'type': 'vacancy', 'can_delete': False}
                })

    return {
        'week_start': week_start.isoformat(),
        'week_end': week_end.isoformat(),
        'events': events,
        'weekend_specials': weekend_specials,
        'available_slots': available_slots,
        'follow_up_alerts': follow_up_alerts
    }


@app.route('/calendar')
@login_required
def weekly_calendar():
    db = get_db()
    if current_user.role == 'admin':
        ensure_ongoing_recurrence_from_previous_week(db)
    patient_options = []
    can_self_schedule = False
    if current_user.role == 'admin':
        patient_options = db.execute(
            'SELECT id, name, status, patient_type FROM patients ORDER BY name ASC'
        ).fetchall()
    else:
        patient = db.execute('SELECT can_self_schedule FROM patients WHERE id = ?', (current_user.patient_id,)).fetchone()
        can_self_schedule = bool(patient and int(patient['can_self_schedule'] or 0) == 1)
    return render_template('calendar.html', patient_options=patient_options, can_self_schedule=can_self_schedule,
                           is_admin=(current_user.role == 'admin'))


@app.route('/groups', methods=['GET', 'POST'])
@login_required
def groups_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('patient_home'))

    db = get_db()
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        group_type = (request.form.get('group_type') or 'support').strip()
        description = (request.form.get('description') or '').strip()
        if not name:
            flash('Group name is required.')
        else:
            db.execute('INSERT INTO groups (name, group_type, description) VALUES (?, ?, ?)',
                       (name, group_type or 'support', description or None))
            db.commit()
            flash('Group created.')
        return redirect(url_for('groups_dashboard'))

    groups = db.execute('''
        SELECT g.*, COUNT(gm.patient_id) AS member_count
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id AND gm.left_at IS NULL
        GROUP BY g.id
        ORDER BY g.created_at DESC, g.name ASC
    ''').fetchall()

    group_members = db.execute('''
        SELECT gm.group_id, p.id AS patient_id, p.name AS patient_name
        FROM group_members gm
        JOIN patients p ON p.id = gm.patient_id
        WHERE gm.left_at IS NULL AND COALESCE(p.is_deleted, 0) = 0
        ORDER BY p.name ASC
    ''').fetchall()

    group_sessions = db.execute('''
        SELECT gs.*, g.name AS group_name
        FROM group_sessions gs
        JOIN groups g ON g.id = gs.group_id
        WHERE COALESCE(gs.status, 'scheduled') = 'scheduled'
        ORDER BY gs.session_date ASC, gs.session_time ASC
    ''').fetchall()

    patients = db.execute('''
        SELECT id, name
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
        ORDER BY name ASC
    ''').fetchall()

    return render_template('groups.html', groups=groups, group_members=group_members,
                           group_sessions=group_sessions, patients=patients)


@app.route('/groups/<int:group_id>/members', methods=['POST'])
@login_required
def add_group_member(group_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    patient_id_raw = (request.form.get('patient_id') or '').strip()
    if not patient_id_raw.isdigit():
        flash('Valid patient is required.')
        return redirect(url_for('groups_dashboard'))

    db = get_db()
    db.execute('''
        INSERT OR REPLACE INTO group_members (group_id, patient_id, joined_at, left_at, role)
        VALUES (?, ?, CURRENT_TIMESTAMP, NULL, 'member')
    ''', (group_id, int(patient_id_raw)))
    db.commit()
    flash('Patient added to group.')
    return redirect(url_for('groups_dashboard'))


@app.route('/groups/<int:group_id>/members/<int:patient_id>/remove', methods=['POST'])
@login_required
def remove_group_member(group_id, patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    db.execute('''
        UPDATE group_members
        SET left_at = CURRENT_TIMESTAMP
        WHERE group_id = ? AND patient_id = ?
    ''', (group_id, patient_id))
    db.commit()
    flash('Patient removed from group.')
    return redirect(url_for('groups_dashboard'))


@app.route('/groups/<int:group_id>/sessions', methods=['POST'])
@login_required
def add_group_session(group_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    session_date = (request.form.get('session_date') or '').strip()
    session_time = (request.form.get('session_time') or '').strip()
    end_time_raw = (request.form.get('end_time') or '').strip()
    title = (request.form.get('title') or '').strip()
    facilitator = (request.form.get('facilitator') or '').strip()
    meeting_type = (request.form.get('meeting_type') or 'in-person').strip()
    meeting_link = (request.form.get('meeting_link') or '').strip()

    parsed_date = parse_date_safe(session_date)
    parsed_time = parse_time_safe(session_time)
    parsed_end = parse_time_safe(end_time_raw)
    if not parsed_date or not parsed_time:
        flash('Valid session date and start time are required.')
        return redirect(url_for('groups_dashboard'))

    duration = 60
    if parsed_end:
        start_minutes = parsed_time.hour * 60 + parsed_time.minute
        end_minutes = parsed_end.hour * 60 + parsed_end.minute
        if end_minutes > start_minutes:
            duration = end_minutes - start_minutes

    session_start = datetime.combine(parsed_date, parsed_time)
    session_end = session_start + timedelta(minutes=duration)

    db = get_db()
    conflict_message = has_time_conflict(db, parsed_date, session_start, session_end)
    if conflict_message:
        flash(conflict_message)
        return redirect(url_for('groups_dashboard'))

    db.execute('''
        INSERT INTO group_sessions
            (group_id, session_date, session_time, duration_minutes, title, facilitator, meeting_type, meeting_link, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled')
    ''', (group_id, session_date, parsed_time.strftime('%H:%M'), duration,
          title or None, facilitator or None, meeting_type or 'in-person', meeting_link or None))
    db.commit()
    flash('Group session added.')
    return redirect(url_for('groups_dashboard'))


@app.route('/api/calendar/snapshot')
@login_required
def api_calendar_snapshot():
    start_raw = request.args.get('week_start', '').strip()
    anchor = parse_date_safe(start_raw) or datetime.now().date()
    week_start = anchor - timedelta(days=custom_weekday(anchor))
    db = get_db()
    if current_user.role == 'admin':
        ensure_ongoing_recurrence_from_previous_week(db, anchor)
    payload = build_week_calendar_snapshot(db, week_start, current_user)
    return jsonify(payload)


@app.route('/api/calendar/block', methods=['POST'])
@login_required
def api_calendar_block():
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    blocked_date = request.form.get('blocked_date', '').strip()
    blocked_time = request.form.get('blocked_time', '').strip()
    end_time_raw = request.form.get('end_time', '').strip()
    title = request.form.get('title', '').strip()
    block_type = request.form.get('block_type', 'blocked').strip().lower() or 'blocked'
    if block_type not in ('blocked', 'special'):
        block_type = 'blocked'
    is_private = 1 if request.form.get('is_private') else 0
    recurrence_pattern = request.form.get('recurrence_pattern', 'one-time').strip().lower() or 'one-time'
    repeat_until_raw = request.form.get('repeat_until', '').strip()

    anchor_date = parse_date_safe(blocked_date)
    parsed_start = parse_time_safe(blocked_time)
    if not anchor_date or not parsed_start:
        return jsonify({'status': 'error', 'message': 'Invalid date or time.'}), 400

    # Compute duration from start + end time.
    duration_value = 60
    parsed_end = parse_time_safe(end_time_raw) if end_time_raw else None
    if parsed_start and parsed_end:
        start_minutes = parsed_start.hour * 60 + parsed_start.minute
        end_minutes = parsed_end.hour * 60 + parsed_end.minute
        computed = end_minutes - start_minutes
        if computed > 0:
            duration_value = computed

    dates_to_create = [anchor_date]
    if recurrence_pattern == 'weekly':
        repeat_until = parse_date_safe(repeat_until_raw)
        if not repeat_until or repeat_until < anchor_date:
            return jsonify({'status': 'error', 'message': 'Invalid repeat-until date for recurring block.'}), 400
        dates_to_create = []
        current_date = anchor_date
        while current_date <= repeat_until:
            dates_to_create.append(current_date)
            current_date += timedelta(days=7)

    db = get_db()
    for block_day in dates_to_create:
        start_dt = datetime.combine(block_day, parsed_start)
        end_dt = start_dt + timedelta(minutes=duration_value)
        conflict_message = has_time_conflict(db, block_day, start_dt, end_dt)
        if conflict_message:
            return jsonify({'status': 'error', 'message': f'{conflict_message} ({block_day.isoformat()})'}), 409

    for block_day in dates_to_create:
        db.execute('''
            INSERT INTO blocked_slots
            (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (block_day.isoformat(), parsed_start.strftime('%H:%M'), duration_value, title or None, is_private, block_type, current_user.id))

    db.commit()
    return jsonify({'status': 'success', 'created': len(dates_to_create)})


@app.route('/api/calendar/block/<int:block_id>/update', methods=['POST'])
@login_required
def api_calendar_block_update(block_id):
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    existing = db.execute('SELECT * FROM blocked_slots WHERE id = ?', (block_id,)).fetchone()
    if not existing:
        return jsonify({'status': 'error', 'message': 'Block not found.'}), 404

    blocked_date = request.form.get('blocked_date', '').strip()
    blocked_time = request.form.get('blocked_time', '').strip()
    end_time_raw = request.form.get('end_time', '').strip()
    title = request.form.get('title', '').strip()
    block_type = request.form.get('block_type', (existing['block_type'] or 'blocked')).strip().lower() or 'blocked'
    if block_type not in ('blocked', 'special'):
        block_type = 'blocked'
    is_private = 1 if request.form.get('is_private') in ('1', 'true', 'on') else 0

    day_obj = parse_date_safe(blocked_date)
    start_time = parse_time_safe(blocked_time)
    end_time = parse_time_safe(end_time_raw) if end_time_raw else None
    if not day_obj or not start_time:
        return jsonify({'status': 'error', 'message': 'Invalid date or time.'}), 400

    duration = int(existing['duration_minutes'] or 60)
    if end_time:
        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        computed = end_minutes - start_minutes
        if computed > 0:
            duration = computed

    start_dt = datetime.combine(day_obj, start_time)
    end_dt = start_dt + timedelta(minutes=duration)
    conflict_message = has_time_conflict(db, day_obj, start_dt, end_dt, exclude_block_id=block_id)
    if conflict_message:
        return jsonify({'status': 'error', 'message': conflict_message}), 409

    db.execute('''
        UPDATE blocked_slots
        SET blocked_date = ?, blocked_time = ?, duration_minutes = ?,
            title = ?, is_private = ?, block_type = ?
        WHERE id = ?
    ''', (day_obj.isoformat(), start_time.strftime('%H:%M'), duration, title or None, is_private, block_type, block_id))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/api/calendar/block/<int:block_id>/delete', methods=['POST'])
@login_required
def api_calendar_block_delete(block_id):
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    db.execute('DELETE FROM blocked_slots WHERE id = ?', (block_id,))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/api/calendar/bookings')
@login_required
def api_calendar_bookings():
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    mode = (request.args.get('mode') or 'upcoming').strip().lower()
    if mode not in ('upcoming', 'history'):
        mode = 'upcoming'

    db = get_db()
    payload = build_booking_management_payload(db, mode=mode)
    return jsonify(payload)


@app.route('/api/calendar/vacancy', methods=['POST'])
@login_required
def api_calendar_vacancy():
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    slot_date = request.form.get('slot_date', '').strip()
    slot_time = request.form.get('slot_time', '').strip()
    end_time_raw = request.form.get('end_time', '').strip()

    date_obj = parse_date_safe(slot_date)
    start_time = parse_time_safe(slot_time)
    end_time = parse_time_safe(end_time_raw)
    if not date_obj or not start_time or not end_time:
        return jsonify({'status': 'error', 'message': 'Invalid date or time.'}), 400

    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    duration = end_minutes - start_minutes
    if duration <= 0:
        return jsonify({'status': 'error', 'message': 'End time must be after start time.'}), 400

    slot_start = datetime.combine(date_obj, start_time)
    slot_end = slot_start + timedelta(minutes=duration)

    db = get_db()
    conflict_message = has_time_conflict(db, date_obj, slot_start, slot_end)
    if conflict_message:
        return jsonify({'status': 'error', 'message': f'Vacancy conflict: {conflict_message}'}), 409

    db.execute('''
        DELETE FROM slots_override
        WHERE slot_date = ? AND slot_time = ? AND status = 'available'
    ''', (slot_date, start_time.strftime('%H:%M')))
    db.execute('''
        INSERT INTO slots_override (slot_date, slot_time, status, duration_minutes)
        VALUES (?, ?, 'available', ?)
    ''', (slot_date, start_time.strftime('%H:%M'), duration))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/api/calendar/book', methods=['POST'])
@login_required
def api_calendar_book():
    db = get_db()

    booking_date = request.form.get('date', '').strip()
    booking_time = request.form.get('time', '').strip()
    end_time_raw = request.form.get('end_time', '').strip()
    meeting_type = request.form.get('meeting_type', 'in-person').strip() or 'in-person'
    meeting_link = request.form.get('meeting_link', '').strip()
    meeting_platform = request.form.get('meeting_platform', '').strip()
    meeting_title = request.form.get('meeting_title', '').strip()
    save_to_google = 1 if request.form.get('save_to_google') in ('1', 'true', 'on') else 0
    booking_type = request.form.get('booking_type', 'appointment').strip().lower() or 'appointment'
    special_pattern = request.form.get('special_pattern', 'one-time').strip().lower() or 'one-time'
    special_repeat_until = request.form.get('special_repeat_until', '').strip()
    special_title = request.form.get('special_title', '').strip()

    if not parse_date_safe(booking_date) or not parse_time_safe(booking_time):
        return jsonify({'status': 'error', 'message': 'Invalid date or time.'}), 400

    # Compute duration from start + end time.
    duration = 60
    parsed_start = parse_time_safe(booking_time)
    parsed_end = parse_time_safe(end_time_raw) if end_time_raw else None
    if parsed_start and parsed_end:
        start_minutes = parsed_start.hour * 60 + parsed_start.minute
        end_minutes = parsed_end.hour * 60 + parsed_end.minute
        computed = end_minutes - start_minutes
        if computed > 0:
            duration = computed

    if current_user.role == 'admin':
        patient_id_raw = request.form.get('patient_id', '').strip()
        if booking_type != 'special' and not patient_id_raw.isdigit():
            return jsonify({'status': 'error', 'message': 'Patient is required.'}), 400
        patient_id = int(patient_id_raw) if patient_id_raw.isdigit() else None
    else:
        if booking_type == 'special':
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        patient_id = current_user.patient_id
        patient = db.execute('SELECT can_self_schedule FROM patients WHERE id = ?', (patient_id,)).fetchone()
        if not patient or int(patient['can_self_schedule'] or 0) != 1:
            return jsonify({'status': 'error', 'message': 'Self-booking is disabled for your account.'}), 403

    patient_type = None
    patient_status = None
    if booking_type != 'special' and patient_id:
        patient_row = db.execute('SELECT patient_type, status FROM patients WHERE id = ?', (patient_id,)).fetchone()
        patient_type = (patient_row['patient_type'] if patient_row else 'private') or 'private'
        patient_status = (patient_row['status'] if patient_row else '') or ''

    def slot_is_available(date_iso, start_time_str, slot_duration):
        date_obj = parse_date_safe(date_iso)
        if not date_obj:
            return False
        slot_start = combine_dt(date_obj, start_time_str)
        slot_end = slot_start + timedelta(minutes=slot_duration)

        date_rows = db.execute('''
            SELECT appointment_time, duration_minutes FROM appointments WHERE appointment_date = ?
        ''', (date_iso,)).fetchall()
        for row in date_rows:
            row_start = combine_dt(date_obj, row['appointment_time'])
            row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
            if overlaps(slot_start, slot_end, row_start, row_end):
                return False

        block_rows = db.execute('''
            SELECT blocked_time, duration_minutes FROM blocked_slots WHERE blocked_date = ?
        ''', (date_iso,)).fetchall()
        for row in block_rows:
            row_start = combine_dt(date_obj, row['blocked_time'])
            row_end = row_start + timedelta(minutes=int(row['duration_minutes'] or 60))
            if overlaps(slot_start, slot_end, row_start, row_end):
                return False

        return True

    anchor = parse_date_safe(booking_date)
    if not anchor:
        return jsonify({'status': 'error', 'message': 'Invalid booking date.'}), 400

    if booking_type == 'special':
        if current_user.role != 'admin':
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

        if special_pattern not in ('one-time', 'weekly'):
            special_pattern = 'one-time'

        dates_to_block = [anchor]
        if special_pattern == 'weekly':
            repeat_until = parse_date_safe(special_repeat_until)
            if not repeat_until or repeat_until < anchor:
                return jsonify({'status': 'error', 'message': 'Invalid repeat-until date for recurring special slot.'}), 400
            dates_to_block = []
            current = anchor
            while current <= repeat_until:
                dates_to_block.append(current)
                current += timedelta(days=7)

        for d in dates_to_block:
            date_iso = d.isoformat()
            if not slot_is_available(date_iso, booking_time, duration):
                return jsonify({'status': 'error', 'message': f'Special slot overlaps existing time on {date_iso}.'}), 409

        for d in dates_to_block:
            db.execute('''
                INSERT INTO blocked_slots
                (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
                VALUES (?, ?, ?, ?, 1, 'special', ?)
            ''', (d.isoformat(), parse_time_safe(booking_time).strftime('%H:%M'), duration,
                  special_title or 'Special Occasion', current_user.id))
        db.commit()
        return jsonify({'status': 'success'})

    if patient_type == 'initial-intake':
        db.execute('DELETE FROM appointments WHERE patient_id = ? AND status = ?', (patient_id, 'scheduled'))

    # Business rule: ongoing patients are booked as weekly recurring sessions.
    # Candidate/waiting/initial-intake remain one-time bookings.
    is_recurring = 1 if patient_status == 'ongoing' else 0
    recurrence_interval = 1 if is_recurring else None
    recurrence_days = str(custom_weekday(anchor)) if is_recurring else None

    parsed_booking_time = parse_time_safe(booking_time)
    if not parsed_booking_time:
        return jsonify({'status': 'error', 'message': 'Invalid time.'}), 400

    start_dt = combine_dt(anchor, parsed_booking_time.strftime('%H:%M'))
    end_dt = start_dt + timedelta(minutes=duration)
    conflict_message = has_time_conflict(db, anchor, start_dt, end_dt)
    if conflict_message:
        return jsonify({'status': 'error', 'message': conflict_message}), 409

    # Patients can only self-book into explicit vacancy slots; admins can book any free time.
    if current_user.role != 'admin':
        week_start = anchor - timedelta(days=custom_weekday(anchor))
        snapshot = build_week_calendar_snapshot(
            db,
            week_start,
            User(current_user.id, current_user.username, current_user.role, patient_id, current_user.display_name)
        )
        is_available = any(slot['date'] == booking_date and slot['time'] == booking_time for slot in snapshot['available_slots'])
        if not is_available:
            return jsonify({'status': 'error', 'message': 'Selected slot is not available.'}), 409

    recurrence_end_date = None
    if is_recurring:
        recurrence_end_date = (anchor + timedelta(days=365)).isoformat()

    db.execute('''
        INSERT INTO appointments
        (patient_id, appointment_date, appointment_time, duration_minutes, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google, status, is_recurring, recurrence_interval, recurrence_days, recurrence_end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?)
    ''', (
        patient_id,
        booking_date,
        parsed_booking_time.strftime('%H:%M'),
        duration,
        meeting_type,
        meeting_link or None,
        meeting_platform or None,
        meeting_title or None,
        save_to_google,
        is_recurring,
        recurrence_interval,
        recurrence_days,
        recurrence_end_date
    ))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/patient/<int:patient_id>/quick_book', methods=('POST',))
@login_required
def quick_book_patient_appointment(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    date_raw = (request.form.get('date') or '').strip()
    time_raw = (request.form.get('time') or '').strip()
    end_time_raw = (request.form.get('end_time') or '').strip()
    meeting_type = (request.form.get('meeting_type') or 'in-person').strip() or 'in-person'
    meeting_link = (request.form.get('meeting_link') or '').strip()
    meeting_title = (request.form.get('meeting_title') or '').strip()
    save_to_google = 1 if request.form.get('save_to_google') in ('1', 'true', 'on') else 0

    booking_date = parse_date_safe(date_raw)
    booking_time = parse_time_safe(time_raw)
    booking_end = parse_time_safe(end_time_raw)
    if not booking_date or not booking_time:
        flash('Valid date and time are required.', 'error')
        return redirect_to_patient_tab(patient_id, 'info')

    duration = 60
    if booking_end:
        start_minutes = booking_time.hour * 60 + booking_time.minute
        end_minutes = booking_end.hour * 60 + booking_end.minute
        if end_minutes > start_minutes:
            duration = end_minutes - start_minutes

    db = get_db()
    patient_row = db.execute('''
        SELECT id, status, patient_type
        FROM patients
        WHERE id = ? AND COALESCE(is_deleted, 0) = 0
    ''', (patient_id,)).fetchone()
    if not patient_row:
        flash('Patient not found.', 'error')
        return redirect(url_for('crm_dashboard'))

    start_dt = datetime.combine(booking_date, booking_time)
    end_dt = start_dt + timedelta(minutes=duration)
    conflict_message = has_time_conflict(db, booking_date, start_dt, end_dt)
    if conflict_message:
        flash(conflict_message, 'error')
        return redirect_to_patient_tab(patient_id, 'info')

    patient_type = (patient_row['patient_type'] or 'private').strip().lower()
    patient_status = (patient_row['status'] or '').strip().lower()
    if patient_type == 'initial-intake':
        db.execute('DELETE FROM appointments WHERE patient_id = ? AND status = ?', (patient_id, 'scheduled'))

    is_recurring = 1 if patient_status == 'ongoing' and patient_type != 'initial-intake' else 0
    recurrence_interval = 1 if is_recurring else None
    recurrence_days = str(custom_weekday(booking_date)) if is_recurring else None
    recurrence_end_date = (booking_date + timedelta(days=365)).isoformat() if is_recurring else None
    meeting_platform = meeting_type if meeting_type in ('zoom', 'google-meet') else None

    db.execute('''
        INSERT INTO appointments (
            patient_id, appointment_date, appointment_time, duration_minutes,
            meeting_type, meeting_link, meeting_platform, meeting_title,
            save_to_google, status, is_recurring, recurrence_interval,
            recurrence_days, recurrence_end_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?)
    ''', (
        patient_id,
        booking_date.isoformat(),
        booking_time.strftime('%H:%M'),
        duration,
        meeting_type,
        meeting_link or None,
        meeting_platform,
        meeting_title or None,
        save_to_google,
        is_recurring,
        recurrence_interval,
        recurrence_days,
        recurrence_end_date
    ))
    db.commit()

    if is_recurring:
        flash('Recurring weekly appointment booked for one year.', 'success')
    else:
        flash('Appointment booked.', 'success')
    return redirect_to_patient_tab(patient_id, 'info')


@app.route('/api/calendar/appointment/<int:appointment_id>/delete', methods=['POST'])
@login_required
def api_calendar_appointment_delete(appointment_id):
    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if not appt:
        return jsonify({'status': 'error', 'message': 'Appointment not found.'}), 404

    if current_user.role == 'patient' and appt['patient_id'] != current_user.patient_id:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    if current_user.role == 'patient':
        patient = db.execute('SELECT can_self_schedule FROM patients WHERE id = ?', (current_user.patient_id,)).fetchone()
        if not patient or int(patient['can_self_schedule'] or 0) != 1:
            return jsonify({'status': 'error', 'message': 'Self-management is disabled.'}), 403

    db.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))
    db.commit()
    return jsonify({'status': 'success'})

@app.route('/patient/<int:patient_id>/add_note', methods=('POST',))
@login_required
def add_note(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form.get('content', '').strip()
    session_number = request.form.get('session_number', '').strip()
    note_date = request.form.get('note_date', '').strip()
    patient_appearance = request.form.get('patient_appearance', '').strip()
    behavior_flags = ','.join(request.form.getlist('behavior_flags'))
    mood_summary = request.form.get('mood_summary', '').strip()
    behavior_notes = request.form.get('behavior_notes', '').strip()

    if content:
        db = get_db()
        appointment_id = None
        if note_date:
            existing = db.execute(
                'SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ? LIMIT 1',
                (patient_id, note_date)
            ).fetchone()
            if existing:
                appointment_id = existing['id']

        cur = db.execute(
            '''INSERT INTO notes (patient_id, appointment_id, session_number, note_date, content,
                                  patient_appearance, behavior_checklist, mood_summary, behavior_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                patient_id,
                appointment_id,
                session_number or None,
                note_date or None,
                content,
                patient_appearance or None,
                behavior_flags or None,
                mood_summary or None,
                behavior_notes or None
            )
        )
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

    else:
        flash('Content is required for treatment log entries.')

    return redirect_to_patient_tab(patient_id, 'notes')

@app.route('/note/<int:note_id>/edit', methods=('POST',))
@login_required
def edit_note(note_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = request.form.get('content', '').strip()
    session_number = request.form.get('session_number', '').strip()
    note_date = request.form.get('note_date', '').strip()
    patient_appearance = request.form.get('patient_appearance', '').strip()
    behavior_flags = ','.join(request.form.getlist('behavior_flags'))
    mood_summary = request.form.get('mood_summary', '').strip()
    behavior_notes = request.form.get('behavior_notes', '').strip()

    db = get_db()
    note = db.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
    if note:
        db.execute(
            '''UPDATE notes
               SET content = ?, session_number = ?, note_date = ?, patient_appearance = ?,
                   behavior_checklist = ?, mood_summary = ?, behavior_notes = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (
                content,
                session_number or None,
                note_date or None,
                patient_appearance or None,
                behavior_flags or None,
                mood_summary or None,
                behavior_notes or None,
                note_id
            )
        )
        db.commit()
        return redirect_to_patient_tab(note['patient_id'], 'notes')
    return "Note not found", 404


@app.route('/note/<int:note_id>/delete', methods=('POST',))
@login_required
def delete_note(note_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    note = db.execute('SELECT id, patient_id FROM notes WHERE id = ?', (note_id,)).fetchone()
    if note is None:
        return "Note not found", 404

    db.execute('DELETE FROM notes WHERE id = ?', (note_id,))
    db.commit()
    flash('Meeting log deleted.')
    return redirect_to_patient_tab(note['patient_id'], 'notes')

@app.route('/patient/<int:patient_id>/add_goal', methods=('POST',))
@login_required
def add_goal(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    description = request.form.get('description', '').strip()
    if description:
        db = get_db()
        db.execute('INSERT INTO goals (patient_id, description) VALUES (?, ?)', (patient_id, description))
        db.commit()
    return redirect_to_patient_tab(patient_id, 'info')

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
        return redirect_to_patient_tab(goal['patient_id'], 'info')
    return "Goal not found", 404

@app.route('/patient/<int:patient_id>/add_file', methods=('POST',))
@login_required
def add_file(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    if 'file' not in request.files:
        flash('No file part')
        return redirect_to_patient_tab(patient_id, 'notes')
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect_to_patient_tab(patient_id, 'notes')
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        db = get_db()
        db.execute('INSERT INTO files (patient_id, filename) VALUES (?, ?)', (patient_id, filename))
        db.commit()

        if filename.endswith('.docx'):
            # Attempt to parse document
            try:
                doc = Document(filepath)
                text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

                # Split the text by meeting header to support multiple entries
                meeting_pattern = re.compile(r'(?:Meeting #|פגישה מספר)[:\s]*\w+', re.IGNORECASE)
                matches = list(meeting_pattern.finditer(text))

                if not matches:
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
                    parsed_date = None
                    meeting_no_match = re.search(r'(?:Meeting #|פגישה מספר)[:\s]*(\w+)', block, re.IGNORECASE)
                    date_match = re.search(r'(?:Date|תאריך)[:\s]*([\d\./\-]+)', block, re.IGNORECASE)
                    content_match = re.search(r'(?:Content|תוכן)[:\s]*(.*)', block, re.IGNORECASE | re.DOTALL)

                    meeting_no = meeting_no_match.group(1).strip() if meeting_no_match else None
                    date_str = date_match.group(1).strip() if date_match else None
                    content = content_match.group(1).strip() if content_match else block.strip()

                    needs_review = False
                    if not meeting_no or not date_str:
                        needs_review = True

                    appointment_id = None
                    if date_str:
                        try:
                            if '.' in date_str or '/' in date_str:
                                parts = re.split(r'[\./]', date_str)
                                if len(parts) == 3:
                                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                                    if y < 100:
                                        y += 2000
                                    parsed_date = f"{y:04d}-{m:02d}-{d:02d}"
                            if not parsed_date:
                                if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                                    parsed_date = date_str

                            if parsed_date:
                                appt = db.execute('SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ?', (patient_id, parsed_date)).fetchone()
                                if appt:
                                    appointment_id = appt['id']
                        except Exception as e:
                            print("Error parsing date:", e)
                            needs_review = True

                    db.execute('''INSERT INTO notes (patient_id, appointment_id, session_number, note_date, needs_review, content)
                                  VALUES (?, ?, ?, ?, ?, ?)''',
                               (patient_id, appointment_id, meeting_no, parsed_date, needs_review, content))
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

    return redirect_to_patient_tab(patient_id, 'notes')

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

    # Ensure latest schema/migrations are applied before inserting example records.
    init_db()
    db = get_db()

    # Keep sample data loading safe and repeatable.
    existing_examples = db.execute(
        "SELECT COUNT(*) AS count FROM patients WHERE name IN (?, ?, ?, ?)",
        ('Maya Cohen', 'Daniel Levy', 'Noa Shapiro', 'Eran Mizrahi')
    ).fetchone()['count']
    if existing_examples > 0:
        flash('Example patients are already loaded. No duplicate records were created.', 'info')
        return redirect(url_for('patients'))

    try:
        today = datetime.now()

        # ─── 1. ONGOING patient — active therapy, recurring weekly session ───
        db.execute(
            """INSERT INTO patients (name, status, email, phone, background, treatment_info)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                'Maya Cohen',
                'ongoing',
                'maya.cohen@example.com',
                '050-1234567',
                'Mid-30s professional. Referred by GP following prolonged work-related stress. '
                'Reports difficulty sleeping, concentration issues, and emotional exhaustion.',
                'Weekly CBT sessions. Focus areas: stress regulation, cognitive reframing, '
                'work-life boundaries. 8 sessions completed, good progress.'
            )
        )
        ongoing_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Past appointments (last 8 weeks)
        past_appt_ids = []
        for week in range(8, 0, -1):
            appt_date = (today - timedelta(weeks=week)).strftime('%Y-%m-%d')
            db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                            cost, duration_minutes, status, meeting_type, is_recurring,
                            recurrence_interval, recurrence_days)
                          VALUES (?, ?, '10:00', 350, 50, 'completed', 'in-person', 1, 1, '0')""",
                       (ongoing_id, appt_date))
            past_appt_ids.append((db.execute("SELECT last_insert_rowid()").fetchone()[0], week, appt_date))

        # Session notes for past appointments
        notes_data = [
            (1, 'Initial assessment. Patient reports chronic work stress for ~18 months. Sleep disturbed — waking at 3am with racing thoughts. Explored presenting concerns, treatment goals set: reduce anxiety baseline, improve sleep hygiene, build assertiveness at work.', 'Tense, guarded initially. Warmed through session.', 'Work stress triggers, sleep patterns, goal-setting'),
            (2, 'Introduced thought records. Patient practiced identifying automatic negative thoughts around a recent conflict with manager. Good engagement. Homework: daily thought record.', 'More relaxed than session 1.', 'Cognitive distortions, thought records'),
            (3, 'Reviewed homework — completed 4/7 days. Identified core belief: "I must not disappoint others." Explored origin. Introduced behavioural activation for mood.', 'Reflective, some distress when exploring core beliefs.', 'Core beliefs, behavioural activation'),
            (4, 'Sleep significantly improved (5→7hrs avg). Reports using progressive relaxation technique. Discussed assertiveness — role-played declining extra work from colleague. Patient found it difficult but agreed to try.', 'Visibly more relaxed than prior sessions.', 'Sleep improvement, assertiveness, relaxation'),
            (5, 'Used assertiveness with manager — partial success. Processed feelings of guilt. Sleep still good. Introduced mindfulness breathing.', 'Confident, engaged.', 'Assertiveness in practice, guilt, mindfulness'),
            (6, 'Mid-treatment review. PHQ-9 reduced from 14 to 7. GAD-7 reduced from 16 to 9. Patient attributes progress to thought monitoring and sleep routine. Identified remaining work: perfectionism.', 'Positive, motivated.', 'Progress review, perfectionism, measurement'),
            (7, 'Explored perfectionism schema — linked to early family expectations. Patient journalled between sessions about "good enough." Discussed self-compassion.', 'Somewhat emotional, insight-oriented.', 'Perfectionism, self-compassion, schema'),
            (8, 'Strong session. Patient reported turning down optional weekend project without significant guilt. Sleep 7-8hrs consistently. Planning consolidation phase.', 'Settled, confident.', 'Consolidation, boundary-setting success'),
        ]
        for (appt_id, week, appt_date), (sn, content, appearance, topics) in zip(past_appt_ids, notes_data):
            db.execute("""INSERT INTO notes (patient_id, appointment_id, session_number, content)
                          VALUES (?, ?, ?, ?)""",
                       (ongoing_id, appt_id, str(sn), content))

        # Upcoming recurring appointment (next Monday)
        days_ahead = (7 - today.weekday()) % 7 or 7
        next_session = (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                        cost, duration_minutes, status, meeting_type, is_recurring,
                        recurrence_interval, recurrence_days)
                      VALUES (?, ?, '10:00', 350, 50, 'scheduled', 'in-person', 1, 1, '0')""",
                   (ongoing_id, next_session))

        # Receipts for past sessions
        for (appt_id, week, appt_date) in past_appt_ids:
            db.execute("INSERT INTO receipts (patient_id, amount, description, created_at) VALUES (?, 350, 'Session payment', ?)",
                       (ongoing_id, appt_date))

        # Goals
        db.execute("INSERT INTO goals (patient_id, description, status) VALUES (?, ?, 'achieved')",
                   (ongoing_id, 'Improve sleep to at least 6 hours per night'))
        db.execute("INSERT INTO goals (patient_id, description, status) VALUES (?, ?, 'achieved')",
                   (ongoing_id, 'Set one work boundary per week'))
        db.execute("INSERT INTO goals (patient_id, description, status) VALUES (?, ?, 'active')",
                   (ongoing_id, 'Reduce perfectionist self-criticism using self-compassion exercises'))

        # Message exchange
        admin_user = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        admin_id = admin_user['id'] if admin_user else None
        existing_maya = db.execute("SELECT id FROM users WHERE username = 'maya'").fetchone()
        if not existing_maya:
            db.execute("INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', ?)",
                       ('maya', generate_password_hash('patient123'), ongoing_id))
        maya_user = db.execute("SELECT id FROM users WHERE username = 'maya'").fetchone()
        if maya_user and admin_id:
            db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                       (maya_user['id'], admin_id, 'Hi, just confirming our appointment next Monday at 10:00. See you then!'))
            db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                       (admin_id, maya_user['id'], 'Confirmed! See you Monday at 10:00. Bring your thought record homework if you have it ready.'))

        # ─── 2. CANDIDATE patient — initial inquiry, no appointments yet ───
        db.execute(
            """INSERT INTO patients (name, status, email, phone, background)
               VALUES (?, ?, ?, ?, ?)""",
            (
                'Daniel Levy',
                'candidate',
                'daniel.levy@example.com',
                '052-9876543',
                'Late 20s, referred by his GP. Experiencing social anxiety and avoidance '
                'behaviour. First contact made via intake form. Awaiting initial assessment session.'
            )
        )
        candidate_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        if admin_id:
            existing_daniel = db.execute("SELECT id FROM users WHERE username = 'daniel'").fetchone()
            if not existing_daniel:
                db.execute("INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', ?)",
                           ('daniel', generate_password_hash('patient123'), candidate_id))
            daniel_user = db.execute("SELECT id FROM users WHERE username = 'daniel'").fetchone()
            if daniel_user:
                db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                           (daniel_user['id'], admin_id, 'Hello, I was referred by Dr. Shapira. I struggle a lot with social situations and anxiety. When would we be able to meet?'))
                db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                           (admin_id, daniel_user['id'], 'Thank you for reaching out, Daniel. I have reviewed your intake form. I can offer an initial assessment on Sunday at 11:00. Does that work for you?'))
                db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                           (daniel_user['id'], admin_id, 'Yes, Sunday at 11:00 works perfectly. Thank you!'))

        # ─── 3. WAITING FOR SCHEDULING patient — assessed, slot being arranged ───
        db.execute(
            """INSERT INTO patients (name, status, email, phone, background, treatment_info)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                'Noa Shapiro',
                'waiting for scheduling',
                'noa.shapiro@example.com',
                '054-3456789',
                'Early 40s, presenting with grief and adjustment difficulties following loss of parent. '
                'Initial assessment completed. Psychoeducation around grief provided.',
                'Humanistic integrative approach planned. Weekly sessions. '
                'Awaiting mutually available recurring slot to be confirmed.'
            )
        )
        waiting_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Initial assessment appointment (2 weeks ago)
        assess_date = (today - timedelta(weeks=2)).strftime('%Y-%m-%d')
        db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                        cost, duration_minutes, status, meeting_type)
                      VALUES (?, ?, '14:00', 350, 60, 'completed', 'in-person')""",
                   (waiting_id, assess_date))
        assess_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            """INSERT INTO notes (patient_id, appointment_id, session_number, content)
               VALUES (?, ?, '0', ?)""",
            (
                waiting_id,
                assess_id,
                "Initial assessment session. Patient describes grief following mother's passing 4 months ago. "
                "Reports low mood, social withdrawal, and difficulty returning to routine. "
                "No risk indicators present. Agreed on weekly therapy."
            )
        )
        db.execute("INSERT INTO receipts (patient_id, amount, description, created_at) VALUES (?, 350, 'Assessment session', ?)",
                   (waiting_id, assess_date))

        existing_noa = db.execute("SELECT id FROM users WHERE username = 'noa'").fetchone()
        if not existing_noa:
            db.execute("INSERT INTO users (username, password_hash, role, patient_id) VALUES (?, ?, 'patient', ?)",
                       ('noa', generate_password_hash('patient123'), waiting_id))
        noa_user = db.execute("SELECT id FROM users WHERE username = 'noa'").fetchone()
        if noa_user and admin_id:
            db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                       (admin_id, noa_user['id'], 'Hi Noa, thank you for coming in last week. I am looking for a recurring Tuesday slot for us. Are mornings or afternoons better for you?'))
            db.execute("INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)",
                       (noa_user['id'], admin_id, 'Afternoons work better, anytime after 15:00. Thank you for checking.'))

        # ─── 4. ARCHIVED patient — completed treatment ───
        db.execute(
            """INSERT INTO patients (name, status, email, phone, background, treatment_info)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                'Eran Mizrahi',
                'archived',
                'eran.mizrahi@example.com',
                '053-7654321',
                'Early 50s. Presented with panic disorder and agoraphobia. '
                'Referred by psychiatrist. Treatment completed after 22 sessions.',
                'CBT for panic disorder. Completed January 2025. Full remission achieved. '
                'Discharged with relapse prevention plan. Follow-up offered in 6 months.'
            )
        )
        archived_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 6 representative past sessions (spanning ~5 months, ending ~2 months ago)
        archive_notes = [
            ('1', 'Psychoeducation on panic cycle. Explained fight/flight response. Patient very relieved to understand physical symptoms are not dangerous.', 'Anxious, engaged.', 'Panic psychoeducation, normalisation'),
            ('5', 'Began interoceptive exposure — spun in chair, breathing through straw. High anxiety initially but habituated within session. Great work.', 'Nervous but willing.', 'Interoceptive exposure'),
            ('10', 'First in vivo exposure — entered shopping centre for 10 minutes. Panic peaked at SUDS 7, dropped to 3. Huge milestone.', 'Visibly proud.', 'In vivo exposure, SUDS monitoring'),
            ('15', 'Supermarket visit alone completed between sessions. No panic attack. Patient reports increased confidence. PRN medication use dropped to zero past 3 weeks.', 'Confident, energised.', 'Medication reduction, independence'),
            ('20', 'Near full remission. PDQ-A score 4 (was 28 at intake). Patient planning holiday abroad — first since onset.', 'Bright, motivated.', 'Outcome measurement, relapse prevention'),
            ('22', 'Termination session. Reviewed progress, consolidated relapse prevention plan. Patient tearful and grateful. Discussed open-door policy for future support.', 'Emotional, positive.', 'Termination, relapse prevention plan'),
        ]
        for i, (sn, content, appearance, topics) in enumerate(archive_notes):
            session_offset_weeks = 22 - (i * 4) + 8  # ended ~2 months ago
            appt_date = (today - timedelta(weeks=session_offset_weeks)).strftime('%Y-%m-%d')
            db.execute("""INSERT INTO appointments (patient_id, appointment_date, appointment_time,
                            cost, duration_minutes, status, meeting_type)
                          VALUES (?, ?, '09:00', 350, 50, 'completed', 'in-person')""",
                       (archived_id, appt_date))
            appt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("""INSERT INTO notes (patient_id, appointment_id, session_number, content)
                          VALUES (?, ?, ?, ?)""",
                       (archived_id, appt_id, sn, content))
            db.execute("INSERT INTO receipts (patient_id, amount, description, created_at) VALUES (?, 350, 'Session payment', ?)",
                       (archived_id, appt_date))

        db.commit()
        flash('Example patients created: Maya Cohen (ongoing), Daniel Levy (candidate), Noa Shapiro (waiting), Eran Mizrahi (archived). Credentials: username = maya / daniel / noa, password = patient123', 'success')
    except sqlite3.IntegrityError as e:
        db.rollback()
        flash(f'Sample data already exists or an error occurred: {str(e)}', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Error seeding data: {str(e)}', 'error')

    return redirect(url_for('patients'))

@app.route('/api/admin/import_calendar', methods=('POST',))
@login_required
def import_calendar():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('patients'))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('patients'))

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

    return redirect(url_for('patients'))

@app.route('/patient/<int:patient_id>/import', methods=('POST',))
@login_required
def import_patient_history(patient_id):

    if current_user.role != 'admin':
        return "Unauthorized", 403

    if 'file' not in request.files:
        flash('No file part')
        return redirect_to_patient_tab(patient_id, 'notes')

    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect_to_patient_tab(patient_id, 'notes')

    if file and file.filename.endswith('.json'):

        import json
        try:
            data = json.load(file)
            db = get_db()

            appointments_added = 0
            notes_added = 0
            receipts_added = 0

            if isinstance(data, list):
                def _sort_key(item):
                    raw_date = (item.get('date') or item.get('note_date') or '').strip()
                    meeting_raw = item.get('meeting_number') or item.get('session_number') or 0
                    try:
                        meeting_num = int(meeting_raw)
                    except (TypeError, ValueError):
                        meeting_num = 0
                    return (raw_date, meeting_num)

                # Handle flat list of treatment logs (meeting number, date, content)
                for item in sorted(data, key=_sort_key):
                    meeting_number = _normalize_session_number(item.get('meeting_number') or item.get('session_number'))
                    date_str = (item.get('date') or item.get('note_date') or '').strip() or None
                    content_text = (item.get('content') or '').strip()
                    appearance_text = (item.get('patient_appearance') or '').strip()
                    checklist_text = item.get('behavior_checklist')
                    if isinstance(checklist_text, list):
                        checklist_text = ','.join([str(i).strip() for i in checklist_text if str(i).strip()])
                    checklist_text = (checklist_text or '').strip()
                    mood_summary = (item.get('mood_summary') or '').strip()
                    behavior_notes = (item.get('behavior_notes') or '').strip()

                    if not meeting_number and not _has_meaningful_note_information(
                        content_text,
                        mood_summary,
                        behavior_notes,
                        appearance_text,
                        checklist_text,
                    ):
                        continue

                    if not content_text:
                        content_text = mood_summary or behavior_notes or appearance_text
                    if not content_text:
                        continue

                    appt_id = None
                    if date_str:
                        existing = db.execute('SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ?', (patient_id, date_str)).fetchone()
                        if not existing:
                            cursor = db.execute('INSERT INTO appointments (patient_id, appointment_date, appointment_time, status) VALUES (?, ?, ?, ?)', (patient_id, date_str, '00:00', 'completed'))
                            appt_id = cursor.lastrowid
                            appointments_added += 1
                        else:
                            appt_id = existing['id']

                    db.execute(
                        '''INSERT INTO notes (patient_id, appointment_id, session_number, note_date, content,
                                              patient_appearance, behavior_checklist, mood_summary, behavior_notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (
                            patient_id,
                            appt_id,
                            meeting_number,
                            date_str,
                            content_text,
                            appearance_text,
                            checklist_text,
                            mood_summary,
                            behavior_notes
                        )
                    )
                    notes_added += 1
            else:


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

                # Import notes sorted by date and meeting number.
                sorted_notes = sorted(
                    data.get('notes', []),
                    key=lambda x: (
                        x.get('note_date') or x.get('date') or x.get('created_at', ''),
                        str(x.get('session_number') or x.get('meeting_number') or '')
                    )
                )
                for note in sorted_notes:
                    new_appt_id = appt_id_map.get(note.get('appointment_id')) if note.get('appointment_id') else None
                    session_number = _normalize_session_number(note.get('session_number') or note.get('meeting_number'))
                    note_date = (note.get('note_date') or note.get('date') or '').strip() or None
                    content_text = (note.get('content') or '').strip()
                    appearance_text = (note.get('patient_appearance') or '').strip()
                    checklist_text = note.get('behavior_checklist')
                    if isinstance(checklist_text, list):
                        checklist_text = ','.join([str(i).strip() for i in checklist_text if str(i).strip()])
                    checklist_text = (checklist_text or '').strip()
                    mood_summary = (note.get('mood_summary') or '').strip()
                    behavior_notes = (note.get('behavior_notes') or '').strip()

                    if not session_number and not _has_meaningful_note_information(
                        content_text,
                        mood_summary,
                        behavior_notes,
                        appearance_text,
                        checklist_text,
                    ):
                        continue

                    if not content_text:
                        content_text = mood_summary or behavior_notes or appearance_text
                    if not content_text:
                        continue

                    db.execute('''INSERT INTO notes
                        (patient_id, appointment_id, session_number, note_date, content, patient_appearance,
                         behavior_checklist, mood_summary, behavior_notes, needs_review, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (
                            patient_id,
                            new_appt_id,
                            session_number,
                            note_date,
                            content_text,
                            appearance_text,
                            checklist_text,
                            mood_summary,
                            behavior_notes,
                            note.get('needs_review'),
                            note.get('created_at')
                        ))
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

    return redirect_to_patient_tab(patient_id, 'notes')


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
    return redirect_to_patient_tab(patient_id, 'billing')

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

@app.route('/api/messages', methods=['GET'])
@login_required
def api_get_messages():
    db = get_db()
    if current_user.role == 'admin':
        search_query = request.args.get('q', '').strip().lower()
        patient_type = request.args.get('patient_type', 'all').strip().lower()
        status_filter = request.args.get('status', 'all').strip().lower()

        filters = ["COALESCE(p.is_deleted, 0) = 0"]
        params = [current_user.id, current_user.id, current_user.id]

        if search_query:
            filters.append('(LOWER(p.name) LIKE ? OR LOWER(COALESCE(u.username, "")) LIKE ? OR LOWER(COALESCE(u.display_name, "")) LIKE ?)')
            like_query = f"%{search_query}%"
            params.extend([like_query, like_query, like_query])

        if patient_type in ('private', 'residency', 'initial-intake', 'group'):
            filters.append('LOWER(COALESCE(p.patient_type, "private")) = ?')
            params.append(patient_type)

        if status_filter in ('ongoing', 'candidate', 'waiting', 'waiting for scheduling', 'archived'):
            if status_filter == 'waiting':
                filters.append("p.status IN ('waiting', 'waiting for scheduling')")
            else:
                filters.append('LOWER(p.status) = ?')
                params.append(status_filter)

        where_clause = ' AND '.join(filters)
        conversations = db.execute('''
            SELECT
                p.id AS patient_id,
                u.id AS user_id,
                COALESCE(u.username, '') AS username,
                COALESCE(u.display_name, '') AS display_name,
                p.name AS patient_name,
                p.status AS patient_status,
                COALESCE(p.patient_type, 'private') AS patient_type,
                MAX(m.timestamp) AS last_message_at,
                SUM(CASE
                    WHEN m.recipient_id = ? AND m.is_read = 0 AND m.sender_id = u.id THEN 1
                    ELSE 0
                END) AS unread_count,
                CASE WHEN u.id IS NULL THEN 0 ELSE 1 END AS can_message
            FROM patients p
            LEFT JOIN users u ON u.patient_id = p.id AND u.role = 'patient' AND u.is_active = 1
            LEFT JOIN messages m ON (
                u.id IS NOT NULL AND (
                    (m.sender_id = u.id AND m.recipient_id = ?) OR
                    (m.sender_id = ? AND m.recipient_id = u.id)
                )
            )
            WHERE ''' + where_clause + '''
            GROUP BY p.id, u.id, u.username, u.display_name, p.name, p.status, p.patient_type
            ORDER BY CASE WHEN p.status = 'archived' THEN 1 ELSE 0 END ASC,
                     COALESCE(MAX(m.timestamp), '') DESC,
                     p.name ASC
        ''', tuple(params)).fetchall()

        requested_user = request.args.get('conversation_with', type=int)
        if requested_user is None:
            for conv in conversations:
                if conv['user_id'] is not None:
                    requested_user = conv['user_id']
                    break

        if requested_user is not None and not any(c['user_id'] == requested_user for c in conversations if c['user_id'] is not None):
            requested_user = None

        if requested_user is not None:
            db.execute(
                'UPDATE messages SET is_read = 1 WHERE recipient_id = ? AND sender_id = ?',
                (current_user.id, requested_user)
            )
            db.commit()

        messages = db.execute('''
            SELECT m.*, u.username as sender_name
            FROM messages m
            LEFT JOIN users u ON m.sender_id = u.id
            WHERE (m.sender_id = ? AND m.recipient_id = ?) OR (m.sender_id = ? AND m.recipient_id = ?)
            ORDER BY m.timestamp ASC
        ''', (current_user.id, requested_user, requested_user, current_user.id)).fetchall() if requested_user else []

        return jsonify({
            'conversations': [dict(c) for c in conversations],
            'active_conversation': requested_user,
            'messages': [dict(m) for m in messages]
        })
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

    recipient_id = None

    if current_user.role == 'patient':
        admin = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        recipient_id = admin['id'] if admin else None
    else:
        recipient_id_raw = request.form.get('recipient_id')
        if recipient_id_raw == 'all':
            recipients = db.execute('''
                SELECT u.id
                FROM users u
                JOIN patients p ON p.id = u.patient_id
                WHERE u.role = 'patient'
                  AND u.is_active = 1
                  AND COALESCE(p.is_deleted, 0) = 0
                ORDER BY CASE WHEN p.status = 'archived' THEN 1 ELSE 0 END ASC,
                         p.name ASC
            ''').fetchall()
            for recipient in recipients:
                db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                           (current_user.id, recipient['id'], content))
            db.commit()
            return jsonify({'status': 'success'})
        try:
            recipient_id = int(recipient_id_raw)
        except (TypeError, ValueError):
            recipient_id = None
        if recipient_id is None:
            return jsonify({'status': 'error', 'message': 'Recipient is required for admin messages.'}), 400

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

    return redirect_to_patient_tab(patient_id, 'messages')

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

    return redirect(url_for('patient_home'))


@app.route('/groups/sessions/<int:session_id>/delete', methods=['POST'])
@login_required
def delete_group_session(session_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    db.execute('DELETE FROM group_sessions WHERE id = ?', (session_id,))
    db.commit()
    flash('Group session deleted.')
    return redirect(url_for('groups_dashboard'))


@app.route('/api/groups/sessions/<int:session_id>/delete', methods=['POST'])
@login_required
def api_delete_group_session(session_id):
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    existing = db.execute('SELECT id FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
    if not existing:
        return jsonify({'status': 'error', 'message': 'Group session not found.'}), 404

    db.execute('DELETE FROM group_sessions WHERE id = ?', (session_id,))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/admin/profile', methods=['GET', 'POST'])
@login_required
def admin_profile():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    admin = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    if admin is None:
        return "Admin not found", 404

    if request.method == 'POST':
        display_name = (request.form.get('display_name') or '').strip() or admin['username']
        email = (request.form.get('email') or '').strip() or None
        phone = (request.form.get('phone') or '').strip() or None
        id_number = (request.form.get('id_number') or '').strip() or None
        birth_date = request.form.get('birth_date') or None

        db.execute('''
            UPDATE users
            SET display_name = ?, email = ?, phone = ?, id_number = ?, birth_date = ?
            WHERE id = ?
        ''', (display_name, email, phone, id_number, birth_date, current_user.id))
        db.commit()
        flash('Admin profile updated.')
        return redirect(url_for('admin_profile'))

    backup_files = list_encrypted_backups()
    return render_template('admin_profile.html', admin=admin, backup_files=backup_files)


@app.route('/admin/backup_now', methods=['POST'])
@login_required
def backup_now():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    database = app.config.get('DATABASE', DATABASE)
    try:
        backup_path = perform_encrypted_backup(database)
        flash(f'Encrypted backup created: {backup_path}')
    except Exception as exc:
        flash(f'Backup failed: {exc}')
    return redirect(url_for('admin_profile'))


@app.route('/admin/restore_backup', methods=['POST'])
@login_required
def restore_backup_now():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    selected_backup = (request.form.get('backup_file') or '').strip() or None
    database = app.config.get('DATABASE', DATABASE)

    try:
        restored_from, safety_copy = perform_encrypted_restore(database, selected_backup)
        flash(f'Restore completed from: {restored_from}. Safety copy created: {safety_copy}')
    except Exception as exc:
        flash(f'Restore failed: {exc}')
    return redirect(url_for('admin_profile'))

@app.route('/patient/<int:patient_id>/convert', methods=('POST',))
@login_required
def convert_patient(patient_id):

    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()

    start_date = request.form.get('start_date', '').strip()
    time = request.form.get('time', '').strip()
    duration = request.form.get('duration', 60)
    interval = request.form.get('interval', 1)
    cost = request.form.get('cost', 0)
    meeting_type = request.form.get('meeting_type', 'in-person')
    meeting_link = request.form.get('meeting_link', '')

    # Validate required fields
    if not start_date or not time:
        flash('Start date and time are required!', 'error')
        return redirect_to_patient_tab(patient_id, 'info')

    # Validate date and time formats
    try:
        datetime.fromisoformat(start_date)
        datetime.strptime(time, '%H:%M')
    except ValueError as e:
        flash(f'Invalid date or time format: {str(e)}', 'error')
        return redirect_to_patient_tab(patient_id, 'info')

    # Convert types
    try:
        duration = int(duration)
        interval = int(interval)
        cost = float(cost) if cost else 0
    except (ValueError, TypeError):
        flash('Invalid duration, interval, or cost value!', 'error')
        return redirect_to_patient_tab(patient_id, 'info')

    # Get recurrence limit
    limit_type = request.form.get('recurrence_limit_type')
    recurrence_end_date = None
    recurrence_count = None
    
    if limit_type == 'date':
        recurrence_end_date = request.form.get('recurrence_end_date', '').strip()
        if recurrence_end_date:
            try:
                datetime.fromisoformat(recurrence_end_date)
            except ValueError:
                flash('Invalid recurrence end date!', 'error')
                return redirect_to_patient_tab(patient_id, 'info')
    elif limit_type == 'count':
        try:
            recurrence_count = int(request.form.get('recurrence_count', 12))
            if recurrence_count <= 0:
                recurrence_count = 12
        except ValueError:
            recurrence_count = 12

    # Get checked days (multiple values)
    days_list = request.form.getlist('days')
    days_str = ','.join(str(d) for d in days_list if d.strip().isdigit()) if days_list else None

    try:
        # Update patient status
        db.execute("UPDATE patients SET status = 'ongoing' WHERE id = ?", (patient_id,))

        # Create recurring appointment
        db.execute('''INSERT INTO appointments
                      (patient_id, appointment_date, appointment_time, cost, duration_minutes, 
                       is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link, 
                       recurrence_end_date, recurrence_count)
                      VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)''',
                   (patient_id, start_date, time, cost, duration, interval, days_str, 
                    meeting_type, meeting_link, recurrence_end_date, recurrence_count))

        # Log the action
        patient = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
        if patient:
            details = f"Patient {patient['name']} converted to ongoing status with recurring appointment starting {start_date} at {time}."
            db.execute('INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)', 
                       (patient_id, 'convert', details))

        db.commit()
        flash('Patient converted to ongoing successfully with recurring appointments.', 'success')
    except sqlite3.IntegrityError as e:
        db.rollback()
        flash(f'Database error: {str(e)}', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Error converting patient: {str(e)}', 'error')

    return redirect_to_patient_tab(patient_id, 'info')

@app.route('/patient/<int:patient_id>/delete', methods=('POST',))
@login_required
def delete_patient(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return "Patient not found", 404

    db.execute('''
        UPDATE patients
        SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP, status = 'archived'
        WHERE id = ?
    ''', (patient_id,))
    db.execute('UPDATE users SET is_active = 0 WHERE patient_id = ?', (patient_id,))
    db.execute('INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)',
               (patient_id, 'delete', f"Patient {patient['name']} marked as deleted."))
    db.commit()
    flash('Patient moved to deleted records.')
    return redirect(url_for('crm_dashboard', status='all'))

@app.route('/admin/profile/name', methods=('POST',))
@login_required
def update_admin_profile_name():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    new_name = request.form.get('display_name', '').strip()
    if not new_name:
        flash('Admin name is required.')
        return redirect(request.referrer or url_for('crm_dashboard'))

    db = get_db()
    db.execute('UPDATE users SET display_name = ? WHERE id = ?', (new_name, current_user.id))
    db.commit()
    flash('Admin display name updated.')
    return redirect(request.referrer or url_for('crm_dashboard'))

@app.route('/api/calendar/appointment/<int:appointment_id>/update', methods=['POST'])
@login_required
def api_calendar_appointment_update(appointment_id):
    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if not appt:
        return jsonify({'status': 'error', 'message': 'Appointment not found.'}), 404

    if current_user.role == 'patient' and appt['patient_id'] != current_user.patient_id:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    booking_date = request.form.get('date', '').strip()
    booking_time = request.form.get('time', '').strip()
    end_time_raw = request.form.get('end_time', '').strip()
    meeting_type = request.form.get('meeting_type', (appt['meeting_type'] or 'in-person')).strip() or 'in-person'
    meeting_link = request.form.get('meeting_link', '').strip()
    meeting_platform = request.form.get('meeting_platform', '').strip()
    meeting_title = request.form.get('meeting_title', '').strip()
    save_to_google = 1 if request.form.get('save_to_google') in ('1', 'true', 'on') else 0

    if not parse_date_safe(booking_date) or not parse_time_safe(booking_time):
        return jsonify({'status': 'error', 'message': 'Invalid date or time.'}), 400

    duration = int(appt['duration_minutes'] or 60)
    parsed_start = parse_time_safe(booking_time)
    parsed_end = parse_time_safe(end_time_raw) if end_time_raw else None
    if parsed_start and parsed_end:
        start_minutes = parsed_start.hour * 60 + parsed_start.minute
        end_minutes = parsed_end.hour * 60 + parsed_end.minute
        computed = end_minutes - start_minutes
        if computed > 0:
            duration = computed

    day_obj = parse_date_safe(booking_date)
    start_dt = combine_dt(day_obj, parse_time_safe(booking_time).strftime('%H:%M'))
    end_dt = start_dt + timedelta(minutes=duration)
    conflict_message = has_time_conflict(db, day_obj, start_dt, end_dt, exclude_appointment_id=appointment_id)
    if conflict_message:
        return jsonify({'status': 'error', 'message': conflict_message}), 409

    db.execute('''
        UPDATE appointments
        SET appointment_date = ?, appointment_time = ?, duration_minutes = ?,
            meeting_type = ?, meeting_link = ?, meeting_platform = ?,
            meeting_title = ?, save_to_google = ?
        WHERE id = ?
    ''', (booking_date, parse_time_safe(booking_time).strftime('%H:%M'), duration,
          meeting_type, meeting_link or None, meeting_platform or None, meeting_title or None, save_to_google, appointment_id))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/api/groups/sessions/<int:session_id>/update', methods=['POST'])
@login_required
def api_update_group_session(session_id):
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    existing = db.execute('SELECT * FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
    if not existing:
        return jsonify({'status': 'error', 'message': 'Group session not found.'}), 404

    session_date = (request.form.get('session_date') or '').strip()
    session_time = (request.form.get('session_time') or '').strip()
    end_time_raw = (request.form.get('end_time') or '').strip()
    title = (request.form.get('title') or '').strip()
    facilitator = (request.form.get('facilitator') or '').strip()
    meeting_type = (request.form.get('meeting_type') or 'in-person').strip() or 'in-person'
    meeting_link = (request.form.get('meeting_link') or '').strip()

    parsed_date = parse_date_safe(session_date)
    parsed_time = parse_time_safe(session_time)
    parsed_end = parse_time_safe(end_time_raw)
    if not parsed_date or not parsed_time:
        return jsonify({'status': 'error', 'message': 'Valid date and start time are required.'}), 400

    duration = int(existing['duration_minutes'] or 60)
    if parsed_end:
        start_minutes = parsed_time.hour * 60 + parsed_time.minute
        end_minutes = parsed_end.hour * 60 + parsed_end.minute
        if end_minutes > start_minutes:
            duration = end_minutes - start_minutes

    start_dt = datetime.combine(parsed_date, parsed_time)
    end_dt = start_dt + timedelta(minutes=duration)
    conflict_message = has_time_conflict(db, parsed_date, start_dt, end_dt, exclude_group_session_id=session_id)
    if conflict_message:
        return jsonify({'status': 'error', 'message': conflict_message}), 409

    db.execute('''
        UPDATE group_sessions
        SET session_date = ?, session_time = ?, duration_minutes = ?,
            title = ?, facilitator = ?, meeting_type = ?, meeting_link = ?
        WHERE id = ?
    ''', (session_date, parsed_time.strftime('%H:%M'), duration,
          title or None, facilitator or None, meeting_type, meeting_link or None, session_id))
    db.commit()
    return jsonify({'status': 'success'})

@app.route('/patient/<int:patient_id>/edit_info', methods=('POST',))
@login_required
def update_patient_info(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    background = request.form.get('background')
    treatment_info = request.form.get('treatment_info')
    intake_data = intake_data_from_request(request.form)
    serialized_intake = json.dumps(intake_data, ensure_ascii=False, indent=2) if intake_data is not None else None
    serialized_assessment = serialize_intake_assessment(intake_data) if intake_data is not None else None

    db = get_db()
    if background is None or treatment_info is None:
        existing = db.execute('SELECT background, treatment_info FROM patients WHERE id = ?', (patient_id,)).fetchone()
        if existing is not None:
            if background is None:
                background = existing['background'] or ''
            if treatment_info is None:
                treatment_info = existing['treatment_info'] or ''
    background = background or ''
    treatment_info = treatment_info or ''

    if intake_data is None:
        db.execute('UPDATE patients SET background = ?, treatment_info = ? WHERE id = ?',
                   (background, treatment_info, patient_id))
    else:
        db.execute('''
            UPDATE patients
            SET background = ?, treatment_info = ?, intake_assessment = ?, intake_questionnaire = ?
            WHERE id = ?
        ''', (background, treatment_info, serialized_assessment or None, serialized_intake or None, patient_id))
    db.commit()
    flash('Patient information updated.')
    return redirect_to_patient_tab(patient_id, 'info')


@app.route('/patient/<int:patient_id>/intake_docx', methods=('GET',))
@login_required
def export_patient_intake_docx(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    patient = db.execute('SELECT id, name, intake_questionnaire FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if patient is None:
        return "Patient not found", 404

    intake_data = parse_intake_questionnaire(patient['intake_questionnaire'])
    if not intake_data:
        flash('No intake form data found for export.')
        return redirect_to_patient_tab(patient_id, 'intake')

    document = build_intake_docx(patient['name'], intake_data)
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f'intake_{patient_id}.docx')
    document.save(temp_path)
    return send_from_directory(app.config['UPLOAD_FOLDER'], f'intake_{patient_id}.docx', as_attachment=True)


@app.route('/patient/<int:patient_id>/generate_background', methods=('POST',))
@login_required
def generate_patient_background(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    patient = db.execute('SELECT id, name FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if patient is None:
        return "Patient not found", 404

    background = build_patient_background_from_notes(db, patient_id, patient['name'])
    db.execute('UPDATE patients SET background = ? WHERE id = ?', (background, patient_id))
    db.commit()
    flash('AI background generated.')
    return redirect_to_patient_tab(patient_id, 'info')

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
        birth_date = request.form.get('birth_date') or None
        id_number = (request.form.get('id_number') or '').strip() or None
        can_self_schedule = 1 if request.form.get('can_self_schedule') else 0
        patient_type = request.form.get('patient_type', 'private')
        if patient_type not in ('private', 'residency', 'initial-intake', 'group'):
            patient_type = 'private'
        has_intake_tab = int(patient['has_intake_tab'] or 0)
        if patient_type == 'initial-intake':
            has_intake_tab = 1
        intake_assessment = request.form.get('intake_assessment', '').strip() if patient_type == 'initial-intake' else ''
        intake_questionnaire = request.form.get('intake_questionnaire', '').strip() if patient_type == 'initial-intake' else ''

        if not name:
            flash('Name is required!')
        else:
            db.execute('''UPDATE patients
                          SET name = ?, status = ?, email = ?, phone = ?, birth_date = ?, id_number = ?, can_self_schedule = ?,
                              patient_type = ?, has_intake_tab = ?, intake_assessment = ?, intake_questionnaire = ?
                          WHERE id = ?''',
                       (name, status, email, phone, birth_date, id_number, can_self_schedule, patient_type,
                        has_intake_tab, intake_assessment or None, intake_questionnaire or None, patient_id))
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
        return redirect_to_patient_tab(patient_id, 'info')

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

    return redirect_to_patient_tab(patient_id, 'info')


@app.route('/patient/<int:patient_id>/enable_intake_tab', methods=('POST',))
@login_required
def enable_intake_tab(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    db.execute('UPDATE patients SET has_intake_tab = 1 WHERE id = ?', (patient_id,))
    db.commit()
    flash('Intake tab enabled for this patient.')
    return redirect(url_for('patient_detail', patient_id=patient_id, tab='intake'))

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

    return redirect_to_patient_tab(patient_id, 'info')

@app.route('/patient/<int:patient_id>/add_appointment', methods=('POST',))
@login_required
def add_appointment(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    date = request.form.get('date', '').strip()
    time = request.form.get('time', '').strip()
    
    # Properly handle cost - convert to float with default 0
    cost_input = request.form.get('cost', '').strip()
    try:
        cost = float(cost_input) if cost_input else 0
    except (ValueError, TypeError):
        cost = 0
    
    meeting_type = request.form.get('meeting_type', 'in-person')
    meeting_link = request.form.get('meeting_link', '')
    meeting_title = request.form.get('meeting_title', '').strip()
    save_to_google = 1 if request.form.get('save_to_google') in ('1', 'true', 'on') else 0
    is_recurring = int(request.form.get('is_recurring', 0))
    duration = int(request.form.get('duration', 60))

    if not date or not time:
        flash('Date and time are required!', 'error')
        return redirect(url_for('patient_detail', patient_id=patient_id))

    # Validate date format
    try:
        datetime.fromisoformat(date)
    except ValueError:
        flash('Invalid date format!', 'error')
        return redirect(url_for('patient_detail', patient_id=patient_id))

    # Validate time format (should be HH:MM or H:MM)
    try:
        time_obj = datetime.strptime(time, '%H:%M')
        time = time_obj.strftime('%H:%M')
    except ValueError:
        flash('Invalid time format! Expected HH:MM', 'error')
        return redirect(url_for('patient_detail', patient_id=patient_id))

    db = get_db()
    patient_row = db.execute('SELECT patient_type FROM patients WHERE id = ?', (patient_id,)).fetchone()
    patient_type = (patient_row['patient_type'] if patient_row else 'private') or 'private'
    if patient_type == 'initial-intake':
        is_recurring = 0
        db.execute('DELETE FROM appointments WHERE patient_id = ? AND status = ?', (patient_id, 'scheduled'))

    # Handle recurring appointment fields
    recurrence_interval = None
    recurrence_days = None
    recurrence_end_date = None
    recurrence_count = None

    if is_recurring:
        recurrence_interval = int(request.form.get('interval', 1))
        
        # Get recurrence limit type and values
        limit_type = request.form.get('recurrence_limit_type')
        if limit_type == 'date':
            recurrence_end_date = request.form.get('recurrence_end_date', '').strip()
            if recurrence_end_date:
                try:
                    datetime.fromisoformat(recurrence_end_date)
                except ValueError:
                    flash('Invalid recurrence end date!', 'error')
                    return redirect(url_for('patient_detail', patient_id=patient_id))
        elif limit_type == 'count':
            try:
                recurrence_count = int(request.form.get('recurrence_count', 12))
                if recurrence_count <= 0:
                    recurrence_count = 12
            except ValueError:
                recurrence_count = 12
        
        # Get days (if provided, otherwise default will be set in the calendar)
        days_list = request.form.getlist('days')
        if days_list:
            recurrence_days = ','.join(str(d) for d in days_list if d.strip().isdigit())

    try:
        if is_recurring:
            db.execute('''INSERT INTO appointments 
                          (patient_id, appointment_date, appointment_time, cost, duration_minutes, 
                                    is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link,
                                    recurrence_end_date, recurrence_count, meeting_title, save_to_google) 
                                  VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (patient_id, date, time, cost, duration, recurrence_interval, 
                                recurrence_days, meeting_type, meeting_link, recurrence_end_date, recurrence_count,
                                meeting_title or None, save_to_google))
        else:
            db.execute('''INSERT INTO appointments 
                          (patient_id, appointment_date, appointment_time, cost, duration_minutes, 
                                    meeting_type, meeting_link, meeting_title, save_to_google) 
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                              (patient_id, date, time, cost, duration, meeting_type, meeting_link,
                                meeting_title or None, save_to_google))

        # Log the appointment
        patient = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
        if patient:
            appt_type = "recurring" if is_recurring else "single"
            details = f"Patient {patient['name']} has scheduled a {appt_type} appointment on {date} at {time}."
            db.execute('INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)', 
                       (patient_id, 'schedule', details))

        db.commit()
        appt_msg = "Recurring appointment series added successfully." if is_recurring else "Single appointment added."
        flash(appt_msg)
    except sqlite3.IntegrityError as e:
        flash(f'Error adding appointment: {str(e)}', 'error')
    except Exception as e:
        flash(f'Unexpected error: {str(e)}', 'error')

    return redirect(url_for('patient_detail', patient_id=patient_id))


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

    start_datetime = datetime.fromisoformat(f"{appt['appointment_date']}T{appt['appointment_time'].zfill(5)}")
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

    db = get_db()
    notifications = db.execute('SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at ASC').fetchall()

    for n in notifications:
        db.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (n['id'],))
    db.commit()

    return jsonify([dict(n) for n in notifications])

@app.route('/appointment/<int:appointment_id>/delete', methods=('POST',))
@login_required
def delete_appointment(appointment_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if appt:
        patient = db.execute('SELECT name FROM patients WHERE id = ?', (appt['patient_id'],)).fetchone()
        if patient:
            details = f"Patient {patient['name']} appointment on {appt['appointment_date']} at {appt['appointment_time']} was deleted."
            db.execute('INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)', (appt['patient_id'], 'delete', details))

        db.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))
        db.commit()
        flash('Appointment deleted.')
        return redirect(url_for('patient_detail', patient_id=appt['patient_id']))

    return "Appointment not found", 404

def is_port_in_use(port, host='127.0.0.1'):
    """Return True when a TCP port is already occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) == 0


def find_available_port(start_port=5000, max_tries=100):
    """Find an open TCP port, starting from start_port."""
    for port in range(start_port, start_port + max_tries):
        if not is_port_in_use(port):
            return port
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_tries - 1}")

if __name__ == '__main__':
    init_db()
    try:
        requested_port = int(os.environ.get('PORT', '5000'))
    except ValueError:
        requested_port = 5000

    port = requested_port
    if is_port_in_use(port):
        port = find_available_port(start_port=port + 1)
        print(f"[WARNING] Port {requested_port} is in use. Falling back to {port}.")

    print(f"[INFO] Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
