import os
import sqlite3
import socket
import json
import ast
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
# OAUTHLIB_INSECURE_TRANSPORT=1 in .env allows OAuth over plain HTTP in local dev.
# Never set this in production — the production .env does not include it.
import hashlib
import threading
from io import BytesIO
import shutil
import secrets
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote
try:
    import google_calendar as gcal
except ImportError:
    gcal = None
try:
    import google_docs as gdocs
except ImportError:
    gdocs = None
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, jsonify, session, Response, send_file
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import re
import pyotp
from docx import Document
from datetime import datetime, timedelta, timezone


app = Flask(__name__)
app.jinja_env.add_extension('jinja2.ext.do')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'static/uploads')
app.config['PUBLIC_BASE_URL'] = os.environ.get('PUBLIC_BASE_URL', '').strip()
app.secret_key = os.environ.get('SECRET_KEY', 'dev')
app.config['INACTIVITY_TIMEOUT_MINUTES'] = int(os.environ.get('INACTIVITY_TIMEOUT_MINUTES', '5') or 5)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB upload limit
csrf = CSRFProtect(app)
DATABASE = os.environ.get('DATABASE', 'clinic.db')
DUMMY_PASSWORD_HASH = generate_password_hash('dummy_password_for_timing_attack_mitigation')
BACKUP_DIR = os.environ.get('BACKUP_DIR', 'secure_backups')
KEY_DIR = os.environ.get('KEY_DIR', '.clinic_keys')
BACKUP_INTERVAL_HOURS = 12

ALLOWED_UPLOAD_EXTENSIONS = {'.docx', '.pdf', '.txt', '.png', '.jpg', '.jpeg', '.gif', '.xlsx', '.csv'}
ALLOWED_DIAGNOSIS_EXTENSIONS = {'.pdf', '.docx', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}

def _allowed_upload(filename, allowed_set):
    ext = os.path.splitext(filename)[1].lower()
    return bool(ext) and ext in allowed_set

# ── Login rate limiting ───────────────────────────────────────────────────────
_failed_login_attempts = defaultdict(list)  # ip -> [datetime, ...]
_failed_login_lock = threading.Lock()
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_LOCKOUT_WINDOW = timedelta(minutes=15)

def _is_login_rate_limited(ip):
    cutoff = datetime.now() - _LOGIN_LOCKOUT_WINDOW
    with _failed_login_lock:
        attempts = _failed_login_attempts[ip]
        attempts[:] = [t for t in attempts if t > cutoff]
        return len(attempts) >= _LOGIN_MAX_ATTEMPTS

def _record_failed_login(ip):
    with _failed_login_lock:
        _failed_login_attempts[ip].append(datetime.now())

def _clear_failed_logins(ip):
    with _failed_login_lock:
        _failed_login_attempts.pop(ip, None)


def ensure_runtime_paths():
    db_path = Path(app.config.get('DATABASE', DATABASE))
    if db_path.parent != Path('.'):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    upload_path = Path(app.config.get('UPLOAD_FOLDER', 'static/uploads'))
    upload_path.mkdir(parents=True, exist_ok=True)

    backup_path = Path(BACKUP_DIR)
    backup_path.mkdir(parents=True, exist_ok=True)


def _resolve_backup_artifact_sources():
    upload_folder = Path(app.config.get('UPLOAD_FOLDER', 'static/uploads'))
    patient_logs_folder = Path(app.config.get('PATIENT_LOGS_FOLDER', 'patients_logs'))
    app_log_file = Path(app.config.get('APP_LOG_FILE', 'app_log.txt'))
    return {
        'uploads': upload_folder,
        'patients_logs': patient_logs_folder,
        'app_log.txt': app_log_file,
    }


def _snapshot_artifact_tree(path, file_label=None):
    if not path.exists():
        return {'exists': False, 'files': []}

    if path.is_file():
        payload = path.read_bytes()
        return {
            'exists': True,
            'files': [{
                'path': file_label or path.name,
                'size': len(payload),
                'sha256': hashlib.sha256(payload).hexdigest(),
            }]
        }

    files = []
    for child in sorted(path.rglob('*')):
        if not child.is_file():
            continue
        rel_path = child.relative_to(path).as_posix()
        payload = child.read_bytes()
        files.append({
            'path': rel_path,
            'size': len(payload),
            'sha256': hashlib.sha256(payload).hexdigest(),
        })
    return {'exists': True, 'files': files}


def _artifact_backup_fingerprint(base_override=None):
    base_override = Path(base_override) if base_override else None
    fingerprint = {}
    for label, source_path in _resolve_backup_artifact_sources().items():
        target_path = (base_override / label) if base_override else source_path
        fingerprint[label] = _snapshot_artifact_tree(target_path, file_label=label)
    return fingerprint


def _write_backup_bundle(bundle_path, db_path):
    db_source = Path(db_path)
    manifest = {
        'version': 2,
        'created_at': datetime.now().isoformat(),
        'database_name': db_source.name,
        'artifacts': sorted(_resolve_backup_artifact_sources().keys()),
    }

    with zipfile.ZipFile(bundle_path, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=True, sort_keys=True))
        bundle.write(db_source, arcname=f'database/{db_source.name}')

        for label, source_path in _resolve_backup_artifact_sources().items():
            if not source_path.exists():
                continue
            if source_path.is_file():
                bundle.write(source_path, arcname=f'artifacts/{label}')
                continue
            for child in sorted(source_path.rglob('*')):
                if child.is_file():
                    rel_path = child.relative_to(source_path).as_posix()
                    bundle.write(child, arcname=f'artifacts/{label}/{rel_path}')


def _is_encrypted_zip_backup(payload):
    return zipfile.is_zipfile(BytesIO(payload))


def _restore_artifact_tree(source_root, destination_path):
    source_root = Path(source_root)
    destination_path = Path(destination_path)

    if destination_path.exists():
        if destination_path.is_dir():
            shutil.rmtree(destination_path)
        else:
            destination_path.unlink()

    if not source_root.exists():
        return

    if source_root.is_file():
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root, destination_path)
        return

    destination_path.mkdir(parents=True, exist_ok=True)
    for child in sorted(source_root.rglob('*')):
        rel_path = child.relative_to(source_root)
        target = destination_path / rel_path
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _backup_live_artifacts(safety_root):
    safety_root = Path(safety_root)
    safety_root.mkdir(parents=True, exist_ok=True)
    for label, source_path in _resolve_backup_artifact_sources().items():
        if not source_path.exists():
            continue
        target = safety_root / label
        if source_path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
        else:
            shutil.copytree(source_path, target, dirs_exist_ok=True)

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
    "Diagnosee": "מאובחן",
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
    ,"Welcome back": "ברוך/ה הבא/ה"
    ,"Here is your current status": "הנה הסטטוס הנוכחי שלך"
    ,"Weekly Calendar": "יומן שבועי"
    ,"Weekly Calendar Locked": "היומן השבועי נעול"
    ,"Self-booking is disabled": "קביעה עצמית כבויה"
    ,"Next meeting:": "הפגישה הבאה:"
    ,"Recurring": "חוזר"
    ,"Upcoming Appointments": "פגישות קרובות"
    ,"Online Session": "פגישה מקוונת"
    ,"In-Person Session": "פגישה פרונטלית"
    ,"Join Link": "קישור להצטרפות"
    ,"Download .ics": "הורדת קובץ .ics"
    ,"No upcoming appointments scheduled.": "אין פגישות קרובות מתוכננות."
    ,"Shared Documents": "מסמכים משותפים"
    ,"No shared documents yet.": "אין עדיין מסמכים משותפים."
    ,"Download": "הורדה"
    ,"Request Cancellation": "בקשת ביטול"
    ,"Cancellation Reason": "סיבת הביטול"
    ,"Send Cancellation Request": "שליחת בקשת ביטול"
    ,"Send cancellation request": "שליחת בקשת ביטול"
    ,"Ask to Book Another Meeting": "בקשה לקביעת פגישה נוספת"
    ,"Request Notes": "הערות לבקשה"
    ,"Send Booking Request": "שליחת בקשת קביעה"
    ,"Admin portal preview mode for patient": "מצב תצוגה מקדימה של פורטל המטופל עבור מטופל"
    ,"minutes": "דקות"
    ,"Add to calendar": "הוספה ליומן"
    ,"Ask to cancel": "בקשה לביטול"
    ,"Why do you need to cancel?": "למה צריך לבטל את הפגישה?"
    ,"Write a short explanation for the clinic team": "יש לכתוב הסבר קצר לצוות הקליניקה"
    ,"Close": "סגירה"
    ,"No upcoming appointments.": "אין פגישות קרובות."
    ,"Need another meeting?": "צריך/ה פגישה נוספת?"
    ,"Send a request and the clinic team will contact you or open self-booking if needed.": "שלח/י בקשה וצוות הקליניקה יחזור אליך או יפתח קביעה עצמית במידת הצורך."
    ,"Request details": "פרטי הבקשה"
    ,"Share preferred days, urgency, or anything else the team should know": "אפשר לציין ימים מועדפים, דחיפות, או כל פרט נוסף שחשוב לצוות לדעת"
    ,"Request another meeting": "בקשה לפגישה נוספת"
    ,"Open weekly calendar": "פתיחת היומן השבועי"
    ,"Message composer is disabled in preview mode.": "שדה כתיבת ההודעות מושבת במצב תצוגה מקדימה."
    ,"Your cancellation request was sent.": "בקשת הביטול שלך נשלחה."
    ,"Your booking request was sent.": "בקשת הקביעה שלך נשלחה."
    ,"Cancellation request sent.": "בקשת הביטול נשלחה."
    ,"Booking request sent.": "בקשת הקביעה נשלחה."
    ,"Please explain why you want to cancel.": "נא להסביר מדוע ברצונך לבטל."
    ,"Please add a note for your booking request.": "נא להוסיף הערה לבקשת הקביעה."
    ,"System": "מערכת"
    ,"Requested": "נשלחה בקשה"
    ,"Time before meeting": "זמן לפני הפגישה"
    ,"No reason provided": "לא נמסרה סיבה"
    ,"Open self-booking for me": "פתיחת קביעה עצמית עבורי"
    ,"Request another meeting from available slots": "בקשה לפגישה נוספת מתוך הזמנים הפנויים"
    ,"This request was added to your chat.": "הבקשה נוספה לצ'אט שלך."
    ,"Edit Meeting": "ערוך פגישה"
    ,"Delete Meeting": "מחק פגישה"
    ,"Delete Recurring Meeting": "מחיקת פגישה חוזרת"
    ,"How would you like to delete this recurring meeting?": "כיצד ברצונך למחוק את הפגישה החוזרת?"
    ,"Delete this occurrence only": "מחק מופע זה בלבד"
    ,"Delete this and all upcoming meetings": "מחק פגישה זו וכל הפגישות הבאות"
    ,"Delete all meetings in this series": "מחק את כל הפגישות בסדרה"
    ,"Delete": "מחק"
    ,"Edit Recurring Meeting": "עריכת פגישה חוזרת"
    ,"How would you like to apply this change?": "כיצד ברצונך להחיל שינוי זה?"
    ,"This occurrence only": "מופע זה בלבד"
    ,"This and all upcoming": "פגישה זו וכל הבאות"
    ,"All occurrences in this series": "כל המופעים בסדרה"
}

TRANSLATION_OVERRIDES_FILE = Path(__file__).resolve().parent / 'translations' / 'he.json'


def load_hebrew_translation_overrides():
    if not TRANSLATION_OVERRIDES_FILE.exists():
        return {}
    try:
        payload = json.loads(TRANSLATION_OVERRIDES_FILE.read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            return {}
        return {
            str(k): str(v)
            for k, v in payload.items()
            if isinstance(k, str) and isinstance(v, str)
        }
    except Exception:
        return {}


HEBREW_TRANSLATIONS.update(load_hebrew_translation_overrides())

@app.context_processor
def inject_translations():
    def t(text):
        if session.get('lang') == 'he':
            return HEBREW_TRANSLATIONS.get(text, text)
        return text
    ui_density = (session.get('ui_density') or 'balanced').strip().lower()
    if ui_density not in {'compact', 'balanced', 'large'}:
        ui_density = 'balanced'
    return dict(t=t, lang=session.get('lang', 'en'), ui_density=ui_density)

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


@app.route('/set_density/<density>')
def set_density(density):
    normalized = (density or '').strip().lower()
    if normalized in {'compact', 'balanced', 'large'}:
        session['ui_density'] = normalized
    return redirect(request.referrer or url_for('index'))


@app.before_request
def enforce_inactivity_timeout():
    if request.path.startswith('/static/'):
        return

    if not current_user.is_authenticated:
        session.pop('last_activity_at', None)
        return

    timeout_minutes = int(app.config.get('INACTIVITY_TIMEOUT_MINUTES', 5) or 5)
    timeout_seconds = max(timeout_minutes, 1) * 60
    now_ts = int(datetime.now(timezone.utc).timestamp())
    last_activity_at = session.get('last_activity_at')

    if last_activity_at is not None:
        try:
            idle_seconds = now_ts - int(last_activity_at)
        except (TypeError, ValueError):
            idle_seconds = 0

        if idle_seconds >= timeout_seconds:
            logout_user()
            session.pop('last_activity_at', None)
            flash('Session expired due to inactivity. Please log in again.')
            return redirect(url_for('login'))

    session['last_activity_at'] = now_ts


@app.before_request
def routine_backup_guard():
    if request.path.startswith('/static/'):
        return
    if app.config.get('TESTING'):
        return

    import os
    import time

    db_path = app.config.get('DATABASE_PATH') or app.config.get('DATABASE', DATABASE)
    if not db_path or not os.path.exists(db_path):
        return

    last_modified = os.path.getmtime(db_path)
    now = time.time()

    if now - last_modified > 86400: # 24 hours
        try:
            perform_routine_encrypted_backup(db_path)
        except Exception:
            app.logger.exception('Routine encrypted backup failed')

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


def _verify_totp_code(secret, candidate_code):
    if not secret:
        return False
    normalized = re.sub(r'\s+', '', str(candidate_code or ''))
    if not normalized.isdigit():
        return False
    return pyotp.TOTP(secret).verify(normalized, valid_window=1)


def _admin_totp_uri(user_row, secret):
    issuer = 'Private Clinic CRM'
    account = user_row['username']
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def _login_redirect_for_user(user_row):
    user_obj = User(
        user_row['id'],
        user_row['username'],
        user_row['role'],
        user_row['patient_id'],
        user_row['display_name']
    )
    login_user(user_obj)

    if user_row['role'] == 'admin':
        if not user_row['totp_enabled'] or not user_row['totp_secret']:
            flash('Set up two-factor authentication from the admin profile before continuing.')
            return redirect(url_for('admin_profile'))
        if user_row['force_password_change']:
            flash('Admin password must be changed before continuing.')
            return redirect(url_for('admin_profile'))
        return redirect(url_for('patients'))

    return redirect(url_for('patient_home'))


def _get_or_create_backup_key():
    key = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if key:
        return key.encode('utf-8')

    key_dir = Path(KEY_DIR)
    key_dir.mkdir(parents=True, exist_ok=True)
    key_path = key_dir / '.backup.key'

    # Migrate key from old location inside backup dir if it exists
    old_key_path = Path(BACKUP_DIR) / '.backup.key'
    if not key_path.exists() and old_key_path.exists():
        key_data = old_key_path.read_bytes()
        key_path.write_bytes(key_data)
        try:
            old_key_path.unlink()
        except Exception:
            pass
        return key_data.strip()

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
            safe_table_name = table_name.replace('"', '""')
            count_row = conn.execute(f'SELECT COUNT(*) AS c FROM "{safe_table_name}"').fetchone()
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
    raw_backup_path = backup_root / f'clinic_{timestamp}.bundle'
    encrypted_path = backup_root / f'clinic_{timestamp}.db.enc'
    verify_dir = backup_root / f'.verify_{timestamp}'

    source_fingerprint = _database_backup_fingerprint(db_path)
    source_artifact_fingerprint = _artifact_backup_fingerprint()

    _write_backup_bundle(raw_backup_path, db_path)

    from cryptography.fernet import Fernet
    cipher = Fernet(_get_or_create_backup_key())
    raw_bytes = raw_backup_path.read_bytes()
    encrypted_bytes = cipher.encrypt(raw_bytes)
    encrypted_path.write_bytes(encrypted_bytes)

    # Quick sanity check so we do not keep unreadable backups.
    try:
        probe = cipher.decrypt(encrypted_bytes)
        if not _is_encrypted_zip_backup(probe):
            raise RuntimeError('Encrypted backup verification failed: invalid backup bundle')

        verify_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(probe), 'r') as bundle:
            bundle.extractall(verify_dir)

        extracted_dbs = sorted(path for path in (verify_dir / 'database').iterdir() if path.is_file()) if (verify_dir / 'database').exists() else []
        if not extracted_dbs:
            raise RuntimeError('Encrypted backup verification failed: database missing from bundle')

        backup_fingerprint = _database_backup_fingerprint(extracted_dbs[0])
        if backup_fingerprint != source_fingerprint:
            raise RuntimeError('Encrypted backup verification failed: data fingerprint mismatch')

        backup_artifact_fingerprint = _artifact_backup_fingerprint(verify_dir / 'artifacts')
        if backup_artifact_fingerprint != source_artifact_fingerprint:
            raise RuntimeError('Encrypted backup verification failed: artifact fingerprint mismatch')
    except Exception as exc:
        encrypted_path.unlink(missing_ok=True)
        raw_backup_path.unlink(missing_ok=True)
        shutil.rmtree(verify_dir, ignore_errors=True)
        raise RuntimeError(f'Encrypted backup verification failed: {exc}')

    raw_backup_path.unlink(missing_ok=True)
    shutil.rmtree(verify_dir, ignore_errors=True)
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

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_restore = backup_root / f'.restore_tmp_{timestamp}'
    safety_copy = backup_root / f'clinic_pre_restore_{timestamp}'

    temp_restore.mkdir(parents=True, exist_ok=True)

    if _is_encrypted_zip_backup(decrypted):
        with zipfile.ZipFile(BytesIO(decrypted), 'r') as bundle:
            bundle.extractall(temp_restore)
        extracted_dbs = sorted(path for path in (temp_restore / 'database').iterdir() if path.is_file()) if (temp_restore / 'database').exists() else []
        if not extracted_dbs:
            raise RuntimeError('Backup restore failed: database missing from bundle.')
        restore_db = extracted_dbs[0]
    else:
        restore_db = temp_restore / Path(db_path).name
        restore_db.write_bytes(decrypted)
        if not decrypted.startswith(b'SQLite format 3'):
            raise RuntimeError('Backup decrypt succeeded but SQLite header is invalid.')

    temp_conn = sqlite3.connect(str(restore_db))
    try:
        integrity = temp_conn.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f'Restored backup integrity check failed: {integrity}')
    finally:
        temp_conn.close()

    live_db = Path(db_path)
    _backup_live_artifacts(safety_copy)
    if live_db.exists():
        shutil.copy2(live_db, safety_copy / live_db.name)

    # Ensure no request-scoped DB handle stays open while replacing file.
    existing = getattr(g, '_database', None)
    if existing is not None:
        existing.close()
        g._database = None

    shutil.copy2(restore_db, live_db)

    artifacts_root = temp_restore / 'artifacts'
    if artifacts_root.exists():
        for label, destination in _resolve_backup_artifact_sources().items():
            _restore_artifact_tree(artifacts_root / label, destination)

    shutil.rmtree(temp_restore, ignore_errors=True)

    verify_conn = sqlite3.connect(str(live_db))
    try:
        verify_integrity = verify_conn.execute('PRAGMA integrity_check').fetchone()[0]
        if verify_integrity != 'ok':
            raise RuntimeError(f'Post-restore database integrity check failed: {verify_integrity}')
    finally:
        verify_conn.close()

    return str(target), str(safety_copy)

def _run_db_migrations(db):
    """Run all schema migrations and index creations."""
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
        db.execute('ALTER TABLE notes ADD COLUMN is_missed_meeting BOOLEAN DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE notes ADD COLUMN missed_reason TEXT')
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
        db.execute('ALTER TABLE appointments ADD COLUMN missed_reason TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE appointments ADD COLUMN save_to_google BOOLEAN DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE appointments ADD COLUMN excluded_dates TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE appointments ADD COLUMN recurrence_group_id TEXT')
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
        db.execute('ALTER TABLE users ADD COLUMN totp_secret TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN force_password_change BOOLEAN DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE slots_override ADD COLUMN share_token TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE slots_override ADD COLUMN booked_by_name TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE slots_override ADD COLUMN booked_by_phone TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE slots_override ADD COLUMN booked_notes TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE slots_override ADD COLUMN booked_at TIMESTAMP')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS vacancy_recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),
            slot_time TEXT NOT NULL,
            duration_minutes INTEGER DEFAULT 60,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE vacancy_recurring ADD COLUMN duration_minutes INTEGER DEFAULT 60')
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
        db.execute('''CREATE TABLE IF NOT EXISTS public_booking_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            created_by INTEGER,
            is_active BOOLEAN DEFAULT 1,
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
            series_id INTEGER,
            occurrence_index INTEGER,
            session_summary TEXT,
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES groups (id)
        )''')
    except sqlite3.OperationalError:
        pass

    try:
        db.execute('ALTER TABLE group_sessions ADD COLUMN series_id INTEGER')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE group_sessions ADD COLUMN occurrence_index INTEGER')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE group_sessions ADD COLUMN session_summary TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE group_sessions ADD COLUMN supervision_id INTEGER')
    except sqlite3.OperationalError:
        pass

    try:
        db.execute('''CREATE TABLE IF NOT EXISTS group_member_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            left_at TIMESTAMP,
            role TEXT DEFAULT 'member',
            FOREIGN KEY (group_id) REFERENCES groups (id),
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )''')
    except sqlite3.OperationalError:
        pass

    try:
        db.execute('''CREATE TABLE IF NOT EXISTS group_session_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            start_date DATE NOT NULL,
            start_time TIME NOT NULL,
            duration_minutes INTEGER DEFAULT 60,
            recurrence_interval_weeks INTEGER DEFAULT 1,
            recurrence_end_date DATE,
            recurrence_count INTEGER,
            title TEXT,
            facilitator TEXT,
            meeting_type TEXT DEFAULT 'in-person',
            meeting_link TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES groups (id)
        )''')
    except sqlite3.OperationalError:
        pass

    try:
        db.execute('''CREATE TABLE IF NOT EXISTS group_session_attendance (
            session_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            attendance_status TEXT NOT NULL DEFAULT 'pending',
            absence_reason TEXT,
            notified_on_time BOOLEAN DEFAULT 0,
            attendance_note TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, patient_id),
            FOREIGN KEY (session_id) REFERENCES group_sessions (id),
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )''')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE group_session_attendance ADD COLUMN notified_on_time BOOLEAN DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    # Performance indexes for common filters and sort paths.
    db.execute('CREATE INDEX IF NOT EXISTS idx_patients_status_deleted ON patients(status, is_deleted)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_patients_type_deleted ON patients(patient_type, is_deleted)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_users_patient_id ON users(patient_id)')

    db.execute('CREATE INDEX IF NOT EXISTS idx_appointments_patient_date_time ON appointments(patient_id, appointment_date, appointment_time)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_appointments_patient_status_date ON appointments(patient_id, status, appointment_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_appointments_date_time_status ON appointments(appointment_date, appointment_time, status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_appointments_recurrence_group ON appointments(recurrence_group_id)')

    db.execute('CREATE INDEX IF NOT EXISTS idx_notes_patient_created ON notes(patient_id, created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_receipts_patient_created ON receipts(patient_id, created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_files_patient_created ON files(patient_id, created_at)')

    db.execute('CREATE INDEX IF NOT EXISTS idx_messages_recipient_read_time ON messages(recipient_id, is_read, timestamp)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_messages_sender_recipient_time ON messages(sender_id, recipient_id, timestamp)')

    db.execute('CREATE INDEX IF NOT EXISTS idx_slots_override_date_time_status ON slots_override(slot_date, slot_time, status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_blocked_slots_date_time ON blocked_slots(blocked_date, blocked_time)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_vacancy_recurring_weekday_active_time ON vacancy_recurring(weekday, is_active, slot_time)')

    db.execute('CREATE INDEX IF NOT EXISTS idx_group_members_patient_left ON group_members(patient_id, left_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_group_sessions_date_time_status ON group_sessions(session_date, session_time, status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_group_member_history_group_patient ON group_member_history(group_id, patient_id, joined_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_group_series_group_start ON group_session_series(group_id, start_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_group_attendance_session_status ON group_session_attendance(session_id, attendance_status)')

    db.execute('CREATE INDEX IF NOT EXISTS idx_notifications_read_created ON notifications(is_read, created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_goals_patient_status ON goals(patient_id, status)')

    try:
        db.execute('''CREATE TABLE IF NOT EXISTS supervisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            group_id INTEGER,
            supervision_date DATE NOT NULL,
            supervisor_name TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (group_id) REFERENCES groups (id)
        )''')
    except sqlite3.OperationalError:
        pass
    db.execute('CREATE INDEX IF NOT EXISTS idx_supervisions_patient ON supervisions(patient_id, supervision_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_supervisions_group ON supervisions(group_id, supervision_date)')

    try:
        db.execute('''CREATE TABLE IF NOT EXISTS diagnosis_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            category TEXT NOT NULL DEFAULT 'test_document',
            title TEXT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )''')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE diagnosis_documents ADD COLUMN category TEXT NOT NULL DEFAULT 'test_document'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE diagnosis_documents ADD COLUMN title TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE diagnosis_documents ADD COLUMN original_filename TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE diagnosis_documents ADD COLUMN stored_filename TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE diagnosis_documents ADD COLUMN notes TEXT')
    except sqlite3.OperationalError:
        pass
    db.execute('CREATE INDEX IF NOT EXISTS idx_diagnosis_documents_patient ON diagnosis_documents(patient_id, category, created_at)')

    # Google Calendar: add google_event_id to appointments and group_sessions
    try:
        db.execute('ALTER TABLE appointments ADD COLUMN google_event_id TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE group_sessions ADD COLUMN google_event_id TEXT')
    except sqlite3.OperationalError:
        pass
    # Ensure google_calendar_tokens table exists
    db.execute('''
        CREATE TABLE IF NOT EXISTS google_calendar_tokens (
            id INTEGER PRIMARY KEY,
            owner TEXT NOT NULL DEFAULT 'admin',
            token_json TEXT NOT NULL,
            calendar_id TEXT NOT NULL DEFAULT 'primary',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Treatment method tag and manual sort order for patients
    try:
        db.execute('ALTER TABLE patients ADD COLUMN treatment_method TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE patients ADD COLUMN sort_order INTEGER')
    except sqlite3.OperationalError:
        pass
    db.execute('''CREATE TABLE IF NOT EXISTS treatment_method_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL UNIQUE,
        display_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Seed default options (only inserts if they don't exist yet)
    for _label in ['Psychodynamic', 'CBT', 'EFT', 'Management', '15 sessions', '3 sessions']:
        db.execute('INSERT OR IGNORE INTO treatment_method_options (label) VALUES (?)', (_label,))

    # Google Docs integration columns
    try:
        db.execute('ALTER TABLE patients ADD COLUMN gdoc_id TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE patients ADD COLUMN gdoc_watch_channel TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE patients ADD COLUMN gdoc_watch_expiry TEXT')
    except sqlite3.OperationalError:
        pass

    db.commit()

def _seed_admin_user(db):
    """Seed the default admin user and handle legacy migrations."""
    # Check if admin exists
    admin = db.execute("SELECT * FROM users WHERE role = 'admin' ORDER BY id ASC").fetchone()
    if not admin:
        print("Creating default admin user...")
        hashed_pw = generate_password_hash('Flo@tingind4')
        db.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, force_password_change) VALUES (?, ?, ?, ?)",
            ('lioraloni', hashed_pw, 'admin', 0)
        )
        db.commit()
        print("Admin user created (username: lioraloni).")
        admin = db.execute("SELECT * FROM users WHERE role = 'admin' ORDER BY id ASC").fetchone()

    # One-time migration from legacy default admin credentials.
    legacy_admin = db.execute("SELECT * FROM users WHERE username = 'admin' AND role = 'admin'").fetchone()
    if legacy_admin:
        collision = db.execute("SELECT id FROM users WHERE username = 'lioraloni' AND id <> ?", (legacy_admin['id'],)).fetchone()
        if not collision:
            db.execute(
                '''
                UPDATE users
                SET username = ?, password_hash = ?, force_password_change = ?
                WHERE id = ?
                ''',
                ('lioraloni', generate_password_hash('Flo@tingind4'), 0, legacy_admin['id'])
            )
            db.commit()
            admin = db.execute("SELECT * FROM users WHERE id = ?", (legacy_admin['id'],)).fetchone()
            print('Legacy admin account migrated to lioraloni.')

    if admin and not admin['display_name']:
        db.execute('UPDATE users SET display_name = ? WHERE id = ?', ('Admin', admin['id']))
        db.commit()


def init_db():

    database = app.config.get('DATABASE', DATABASE)
    # Always run schema to ensure tables exist
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

        _run_db_migrations(db)
        _seed_admin_user(db)

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
            return redirect(url_for('admin_dashboard'))
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


def extract_key_summary_points(notes, limit=3):
    scored_segments = []
    keyword_sets = list(BACKGROUND_REASON_TOPICS.values()) + list(BACKGROUND_THEME_TOPICS.values())

    recent_notes = list(notes[-8:])
    for idx, note in enumerate(reversed(recent_notes)):
        note_text = ' '.join([
            normalize_summary_text(note['mood_summary'] or ''),
            normalize_summary_text(note['content'] or '')
        ]).strip()
        if not note_text:
            continue
        for segment in split_summary_segments(note_text):
            score = max(0, 6 - idx)
            for keywords in keyword_sets:
                if any(keyword in segment for keyword in keywords):
                    score += 2
            if len(segment) > 140:
                score += 1
            scored_segments.append((score, segment))

    unique_segments = []
    seen_prefix = set()
    for _, segment in sorted(scored_segments, key=lambda pair: pair[0], reverse=True):
        key = normalize_summary_text(segment)[:64]
        if not key or key in seen_prefix:
            continue
        seen_prefix.add(key)
        unique_segments.append(trim_summary_segment(segment, 170))
        if len(unique_segments) >= limit:
            break

    return unique_segments


def normalize_intake_payload(payload):
    if not isinstance(payload, dict):
        return {}
    allowed_fields = set(intake_form_fields())
    normalized = {}
    for key, value in payload.items():
        key_text = str(key or '').strip()
        if not key_text:
            continue
        if key_text.startswith('intake_'):
            key_text = key_text[7:]
        if key_text not in allowed_fields:
            continue
        if isinstance(value, list):
            clean_values = [str(item or '').strip() for item in value if str(item or '').strip()]
            normalized[key_text] = ', '.join(clean_values)
        else:
            normalized[key_text] = str(value or '').strip()
    return normalized


def parse_legacy_intake_text(raw_value):
    text = str(raw_value or '').strip()
    if not text:
        return {}

    label_map = {
        'main complaint': 'main_complaint',
        'problem history / current illness': 'problem_history',
        'problem history': 'problem_history',
        'early anamnesis': 'early_anamnesis',
    }

    parsed = {}
    current_key = None
    current_lines = []

    def flush_current():
        if current_key is None:
            return
        value = '\n'.join(current_lines).strip()
        if value:
            parsed[current_key] = value

    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.endswith(':'):
            candidate = lowered[:-1].strip()
            mapped = label_map.get(candidate)
            if mapped:
                flush_current()
                current_key = mapped
                current_lines = []
                continue
        if current_key is not None:
            current_lines.append(stripped)

    flush_current()
    if parsed:
        return parsed

    # Fall back to using the entire legacy text as the main complaint.
    return {'main_complaint': text}


def parse_intake_questionnaire(raw_value, fallback_assessment=None):
    if raw_value:
        try:
            parsed = json.loads(raw_value)
            normalized = normalize_intake_payload(parsed)
            if normalized:
                return normalized
        except (json.JSONDecodeError, TypeError):
            pass

        # Some legacy records were stored as Python dict strings.
        raw_text = str(raw_value).strip()
        if raw_text.startswith('{') and raw_text.endswith('}'):
            try:
                literal = ast.literal_eval(raw_text)
                normalized = normalize_intake_payload(literal)
                if normalized:
                    return normalized
            except (ValueError, SyntaxError):
                pass

        legacy_from_questionnaire = parse_legacy_intake_text(raw_value)
        if legacy_from_questionnaire:
            return legacy_from_questionnaire

    legacy_from_assessment = parse_legacy_intake_text(fallback_assessment)
    if legacy_from_assessment:
        return legacy_from_assessment

    return {}


def intake_form_fields():
    return [
        'meeting_location', 'meeting_location_specify', 'meeting_time', 'meeting_duration', 'meeting_conductor',
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
        'treatment_approach', 'treatment_frequency', 'treatment_estimated_duration',
        'diag_referral_question', 'diag_test_battery', 'diag_observations',
        'diag_differential', 'diag_impression', 'diag_recommendations',
        'diag_followup_plan', 'diag_final_summary'
    ]


def intake_multi_select_fields():
    return {
        'appearance_fit',
        'appearance_ordered',
        'behavior_normal',
        'speech_style',
        'mood',
        'affect_match',
        'affect_state',
        'thinking_normal',
        'thinking_rate',
        'thinking_sequence',
        'thinking_content',
        'referral_target',
    }


def intake_data_from_request(form):
    if not any(key.startswith('intake_') for key in form.keys()):
        return None
    data = {}
    multi_fields = intake_multi_select_fields()
    for key in intake_form_fields():
        field_name = f'intake_{key}'
        if key in multi_fields:
            values = [value.strip() for value in form.getlist(field_name) if value and value.strip()]
            data[key] = ', '.join(values)
        else:
            raw = form.get(field_name, '')
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
    doc.add_heading(title, level=2)


def split_intake_values(value):
    cleaned = (value or '').strip()
    if not cleaned:
        return []
    if '\n' in cleaned:
        return [line.strip() for line in cleaned.splitlines() if line.strip()]
    if ',' in cleaned:
        return [item.strip() for item in cleaned.split(',') if item.strip()]
    return [cleaned]


def add_intake_line(doc, label, value):
    values = split_intake_values(value)
    if not values:
        return
    if len(values) == 1:
        paragraph = doc.add_paragraph()
        paragraph.add_run(f'{label}: ').bold = True
        paragraph.add_run(values[0])
        return

    heading = doc.add_paragraph()
    heading.add_run(f'{label}:').bold = True
    for item in values:
        doc.add_paragraph(item, style='List Bullet')


def get_intake_docx_text(language):
    is_hebrew = language == 'he'
    return {
        'title': 'טופס הערכת אינטייק' if is_hebrew else 'Intake Evaluation',
        'patient': 'מטופל/ת' if is_hebrew else 'Patient',
        'generated': 'הופק בתאריך' if is_hebrew else 'Generated',
        'sections': {
            'prelim': 'פרטים מקדימים' if is_hebrew else 'Prelim',
            'background': 'רקע' if is_hebrew else 'Background',
            'administrative': 'אדמיניסטרטיבי' if is_hebrew else 'Administrative',
            'medical': 'רפואי' if is_hebrew else 'Medical',
            'mental_status': 'סטטוס מנטלי' if is_hebrew else 'Mental Status',
            'treatment_plan': 'תוכנית טיפול' if is_hebrew else 'Treatment Plan',
        },
        'labels': {
            'meeting_location': 'מקום הפגישה' if is_hebrew else 'Meeting location',
            'meeting_location_specify': 'מקום הפגישה (פירוט)' if is_hebrew else 'Meeting location (specify)',
            'meeting_time': 'זמן הפגישה' if is_hebrew else 'Meeting time',
            'meeting_duration': 'משך' if is_hebrew else 'Duration',
            'meeting_conductor': 'מי מעביר' if is_hebrew else 'Conducted by',
            'main_complaint': 'תלונה עיקרית' if is_hebrew else 'Main complaint',
            'problem_history': 'היסטוריה של הבעיה / מחלה נוכחית' if is_hebrew else 'Problem history / current illness',
            'early_anamnesis': 'אנמנזה מוקדמת' if is_hebrew else 'Early anamnesis',
            'referral_source': 'מקור ההפניה' if is_hebrew else 'Referral source',
            'referral_date': 'תאריך ההפניה' if is_hebrew else 'Referral date',
            'family_status': 'מצב משפחתי' if is_hebrew else 'Family status',
            'guardian_status': 'אפוטרופסות' if is_hebrew else 'Guardian status',
            'guardian_by_whom': 'פרטי אפוטרופסות' if is_hebrew else 'Guardian details',
            'living_with': 'עם מי גר/ה' if is_hebrew else 'Living arrangement',
            'living_with_other': 'מגורים - אחר (פירוט)' if is_hebrew else 'Living arrangement (other)',
            'disability_status': 'סטטוס נכות' if is_hebrew else 'Disability status',
            'disability_percent': 'אחוזי נכות' if is_hebrew else 'Disability percent',
            'self_harm_level': 'רמת סיכון לפגיעה עצמית' if is_hebrew else 'Self-harm level',
            'self_harm_recent': 'מתי לאחרונה' if is_hebrew else 'Self-harm recent timing',
            'self_harm_count': 'מספר מקרי עבר' if is_hebrew else 'Self-harm number of cases',
            'forced_treatment': 'טיפולים כפויים בעבר' if is_hebrew else 'Forced treatment history',
            'substance_use': 'שימוש בסמים' if is_hebrew else 'Substance use',
            'medical_cannabis': 'קנאביס רפואי' if is_hebrew else 'Medical cannabis',
            'alcohol_use': 'שימוש באלכוהול' if is_hebrew else 'Alcohol use',
            'medical_conditions': 'מחלות רקע' if is_hebrew else 'Medical background conditions',
            'psychiatric_conditions': 'מצבים פסיכיאטריים והיסטוריה' if is_hebrew else 'Psychiatric conditions and history',
            'appearance_fit': 'הופעה - תואמת' if is_hebrew else 'Appearance - fit',
            'appearance_fit_note': 'הופעה - הערה' if is_hebrew else 'Appearance - fit note',
            'appearance_ordered': 'הופעה - מסודרת' if is_hebrew else 'Appearance - ordered',
            'appearance_ordered_note': 'הופעה - הערת סדר' if is_hebrew else 'Appearance - ordered note',
            'cooperation': 'שיתוף פעולה' if is_hebrew else 'Cooperation',
            'cooperation_note': 'הערת שיתוף פעולה' if is_hebrew else 'Cooperation note',
            'eye_contact': 'קשר עין' if is_hebrew else 'Eye contact',
            'eye_contact_note': 'הערת קשר עין' if is_hebrew else 'Eye contact note',
            'behavior_normal': 'התנהגות' if is_hebrew else 'Behavior',
            'behavior_note': 'הערת התנהגות' if is_hebrew else 'Behavior note',
            'speech_style': 'דיבור' if is_hebrew else 'Speech',
            'speech_note': 'הערת דיבור' if is_hebrew else 'Speech note',
            'mood': 'מצב רוח' if is_hebrew else 'Mood',
            'mood_note': 'הערת מצב רוח' if is_hebrew else 'Mood note',
            'affect_match': 'אפקט תואם' if is_hebrew else 'Affect congruence',
            'affect_state': 'מצב אפקט' if is_hebrew else 'Affect state',
            'affect_note': 'הערת אפקט' if is_hebrew else 'Affect note',
            'thinking_normal': 'חשיבה תקינה' if is_hebrew else 'Thinking normal',
            'thinking_rate': 'קצב חשיבה' if is_hebrew else 'Thinking rate',
            'thinking_sequence': 'רצף חשיבה' if is_hebrew else 'Thinking sequence',
            'thinking_content': 'תוכן חשיבה' if is_hebrew else 'Thinking content',
            'perception_normal': 'תפיסה תקינה' if is_hebrew else 'Perception normal',
            'perception_abnormal': 'תפיסה לא תקינה' if is_hebrew else 'Perception abnormal type',
            'reality_testing': 'בוחן מציאות' if is_hebrew else 'Reality testing',
            'judgment': 'שיפוט' if is_hebrew else 'Judgment',
            'self_insight': 'תובנה עצמית' if is_hebrew else 'Self insight',
            'orientation': 'התמצאות' if is_hebrew else 'Orientation',
            'memory': 'זיכרון' if is_hebrew else 'Memory',
            'referral_target': 'יעד הפניה' if is_hebrew else 'Referral target',
            'referral_details': 'פירוט מטרות ההפניה' if is_hebrew else 'Referral details',
            'patient_consent': 'הסכמת המטופל/ת' if is_hebrew else 'Patient consent',
            'treatment_approach': 'גישה טיפולית' if is_hebrew else 'Treatment approach',
            'treatment_frequency': 'תדירות מפגשים' if is_hebrew else 'Meeting frequency',
            'treatment_estimated_duration': 'משך טיפול משוער' if is_hebrew else 'Estimated treatment duration',
            'diag_referral_question': 'שאלת הפניה אבחונית' if is_hebrew else 'Diagnostic referral question',
            'diag_test_battery': 'סוללת מבחנים' if is_hebrew else 'Test battery',
            'diag_observations': 'תצפיות בזמן אבחון' if is_hebrew else 'Diagnostic observations',
            'diag_differential': 'אבחנה מבדלת' if is_hebrew else 'Differential diagnosis',
            'diag_impression': 'התרשמות קלינית' if is_hebrew else 'Clinical impression',
            'diag_recommendations': 'המלצות' if is_hebrew else 'Recommendations',
            'diag_followup_plan': 'תוכנית המשך' if is_hebrew else 'Follow-up plan',
            'diag_final_summary': 'סיכום אבחוני סופי' if is_hebrew else 'Final diagnostic summary',
        }
    }


INTAKE_SECTIONS_MAPPING = [
    ('prelim', [
        'meeting_location',
        'meeting_location_specify',
        'meeting_time',
        'meeting_duration',
        'meeting_conductor'
    ]),
    ('background', [
        'main_complaint',
        'problem_history',
        'early_anamnesis',
        'referral_source',
        'referral_date'
    ]),
    ('administrative', [
        'family_status',
        'guardian_status',
        'guardian_by_whom',
        'living_with',
        'living_with_other',
        'disability_status',
        'disability_percent',
        'self_harm_level',
        'self_harm_recent',
        'self_harm_count',
        'forced_treatment',
        'substance_use',
        'medical_cannabis',
        'alcohol_use'
    ]),
    ('medical', [
        'medical_conditions',
        'psychiatric_conditions'
    ]),
    ('mental_status', [
        'appearance_fit',
        'appearance_fit_note',
        'appearance_ordered',
        'appearance_ordered_note',
        'cooperation',
        'cooperation_note',
        'eye_contact',
        'eye_contact_note',
        'behavior_normal',
        'behavior_note',
        'speech_style',
        'speech_note',
        'mood',
        'mood_note',
        'affect_match',
        'affect_state',
        'affect_note',
        'thinking_normal',
        'thinking_rate',
        'thinking_sequence',
        'thinking_content',
        'perception_normal',
        'perception_abnormal',
        'reality_testing',
        'judgment',
        'self_insight',
        'orientation',
        'memory'
    ]),
    ('treatment_plan', [
        'referral_target',
        'referral_details',
        'patient_consent',
        'treatment_approach',
        'treatment_frequency',
        'treatment_estimated_duration',
        'diag_referral_question',
        'diag_test_battery',
        'diag_observations',
        'diag_differential',
        'diag_impression',
        'diag_recommendations',
        'diag_followup_plan',
        'diag_final_summary'
    ])
]


def build_intake_docx(patient_name, data, language='en'):
    text = get_intake_docx_text(language)

    doc = Document()
    title = doc.add_heading(text['title'], level=1)
    title.alignment = 1
    subtitle = doc.add_paragraph(
        f"{text['patient']}: {patient_name} | {text['generated']}: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    subtitle.alignment = 1

    for section_key, fields in INTAKE_SECTIONS_MAPPING:
        add_intake_section_heading(doc, text['sections'][section_key])
        for field in fields:
            add_intake_line(doc, text['labels'][field], data.get(field))

    return doc



def _get_intake_data(patient_row):
    if not patient_row:
        return {}, ''
    intake_questionnaire = parse_intake_questionnaire(
        patient_row['intake_questionnaire'],
        patient_row['intake_assessment']
    )
    return intake_questionnaire, patient_row['intake_assessment'] or ''


def _extract_main_problem_no_notes(patient_row):
    intake_questionnaire, intake_assessment = _get_intake_data(patient_row)
    main_complaint = (intake_questionnaire.get('main_complaint') or '').strip()
    problem_history = (intake_questionnaire.get('problem_history') or '').strip()

    main_problem = main_complaint or problem_history
    if not main_problem and intake_assessment.strip():
        main_problem = intake_assessment.strip().splitlines()[0]
    return main_problem


def _extract_main_problem_with_notes(patient_row, notes, reason_topics, theme_topics, recent_focus):
    intake_questionnaire, intake_assessment = _get_intake_data(patient_row)
    main_complaint = (intake_questionnaire.get('main_complaint') or '').strip()
    problem_history = (intake_questionnaire.get('problem_history') or '').strip()

    intake_problem_line = ''
    if intake_assessment:
        for line in intake_assessment.splitlines():
            cleaned = line.strip()
            if cleaned and not cleaned.lower().startswith('main complaint:'):
                intake_problem_line = cleaned
                break

    if main_complaint:
        return main_complaint
    elif problem_history:
        return problem_history
    elif intake_problem_line:
        return intake_problem_line
    elif reason_topics:
        return f"קושי מרכזי סביב {', '.join(reason_topics)}"
    elif theme_topics:
        return f"מוקד קושי חוזר סביב {', '.join(theme_topics)}"
    elif recent_focus:
        return recent_focus
    else:
        return extract_background_sentence(notes[-1]['mood_summary'] or notes[-1]['content'])


def _get_notes_timeframe(notes):
    first_date = notes[0]['note_date']
    last_date = notes[-1]['note_date']

    if first_date and last_date:
        return f" בין {first_date} ל-{last_date}"
    if last_date:
        return f" עד המפגש האחרון המתועד ב-{last_date}"
    return ''


def _format_patient_summary(patient_name, notes, timeframe, age_fact, occupation_fact, family_fact, reason_topics, theme_topics, key_points, recent_focus, main_problem):
    parts = [f"סיכום מטופל: {patient_name}."]
    parts.append(f"תמונת זמן: {len(notes)} מפגשים מתועדים{timeframe}.")

    identity_parts = [age_fact]
    if occupation_fact:
        identity_parts.append(occupation_fact)
    if family_fact:
        identity_parts.append(family_fact)
    parts.append(f"פרופיל רקע: {'; '.join(identity_parts)}.")

    if reason_topics:
        parts.append(f"סיבות ופניות מרכזיות: {', '.join(reason_topics)}.")
    if theme_topics:
        parts.append(f"דפוסים חוזרים לאורך המפגשים: {', '.join(theme_topics)}.")
    if key_points:
        parts.append(f"תובנות מפתח מהתיעוד: {' | '.join(key_points)}.")
    if recent_focus:
        parts.append(f"מיקוד עדכני לטווח הקרוב: {recent_focus}.")

    parts.append(f"תמצית קלינית נוכחית: {main_problem}.")

    return ' '.join(part.strip() for part in parts if part).strip()


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
        main_problem = _extract_main_problem_no_notes(patient_row)
        if main_problem:
            return (
                f"סיכום מטופל: {patient_name}. "
                "סטטוס תיעוד: מידע ראשוני מאינטייק בלבד (ללא מפגשים שוטפים מתועדים). "
                f"מוקד עיקרי נוכחי: {main_problem}."
            )
        return 'לא נמצאה היסטוריה טיפולית מתועדת במערכת.'

    note_texts = []
    for note in notes:
        note_texts.append(note['content'])
        if note['mood_summary']:
            note_texts.append(note['mood_summary'])

    timeframe = _get_notes_timeframe(notes)

    age_fact = extract_age_fact(note_texts, patient_name)
    occupation_fact = extract_occupation_fact(note_texts, patient_name)
    family_fact = extract_family_fact(note_texts)
    reason_topics = pick_top_summary_topics(note_texts[:8], BACKGROUND_REASON_TOPICS, 2)
    theme_topics = pick_top_summary_topics(note_texts, BACKGROUND_THEME_TOPICS, 2)
    recent_focus = extract_recent_focus(notes)
    key_points = extract_key_summary_points(notes, limit=3)

    main_problem = _extract_main_problem_with_notes(patient_row, notes, reason_topics, theme_topics, recent_focus)

    return _format_patient_summary(
        patient_name, notes, timeframe, age_fact, occupation_fact, family_fact,
        reason_topics, theme_topics, key_points, recent_focus, main_problem
    )


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


def _parse_note_fields(item):
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
        return None

    if not content_text:
        content_text = mood_summary or behavior_notes or appearance_text
    if not content_text:
        return None

    return {
        'meeting_number': meeting_number,
        'date_str': date_str,
        'content_text': content_text,
        'appearance_text': appearance_text,
        'checklist_text': checklist_text,
        'mood_summary': mood_summary,
        'behavior_notes': behavior_notes
    }


def _import_flat_patient_history(db, patient_id, data):
    appointments_added = 0
    notes_added = 0

    def _sort_key(item):
        raw_date = (item.get('date') or item.get('note_date') or '').strip()
        meeting_raw = item.get('meeting_number') or item.get('session_number') or 0
        try:
            meeting_num = int(meeting_raw)
        except (TypeError, ValueError):
            meeting_num = 0
        return (raw_date, meeting_num)

    for item in sorted(data, key=_sort_key):
        parsed = _parse_note_fields(item)
        if not parsed:
            continue

        appt_id = None
        if parsed['date_str']:
            existing = db.execute('SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ?', (patient_id, parsed['date_str'])).fetchone()
            if not existing:
                cursor = db.execute('INSERT INTO appointments (patient_id, appointment_date, appointment_time, status) VALUES (?, ?, ?, ?)', (patient_id, parsed['date_str'], '00:00', 'completed'))
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
                parsed['meeting_number'],
                parsed['date_str'],
                parsed['content_text'],
                parsed['appearance_text'],
                parsed['checklist_text'],
                parsed['mood_summary'],
                parsed['behavior_notes']
            )
        )
        notes_added += 1

    return appointments_added, notes_added, 0

def _import_structured_patient_history(db, patient_id, data):
    appointments_added = 0
    notes_added = 0
    receipts_added = 0

    # Import appointments
    appt_id_map = {}
    sorted_appts = sorted(data.get('appointments', []), key=lambda x: (x.get('appointment_date', ''), x.get('appointment_time', '')))
    for appt in sorted_appts:
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
    sorted_notes = sorted(
        data.get('notes', []),
        key=lambda x: (
            x.get('note_date') or x.get('date') or x.get('created_at', ''),
            str(x.get('session_number') or x.get('meeting_number') or '')
        )
    )
    for note in sorted_notes:
        parsed = _parse_note_fields(note)
        if not parsed:
            continue

        new_appt_id = appt_id_map.get(note.get('appointment_id')) if note.get('appointment_id') else None

        db.execute('''INSERT INTO notes
            (patient_id, appointment_id, session_number, note_date, content, patient_appearance,
             behavior_checklist, mood_summary, behavior_notes, needs_review, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                patient_id,
                new_appt_id,
                parsed['meeting_number'],
                parsed['date_str'],
                parsed['content_text'],
                parsed['appearance_text'],
                parsed['checklist_text'],
                parsed['mood_summary'],
                parsed['behavior_notes'],
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

    return appointments_added, notes_added, receipts_added


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


def _get_patients_select_clause(admin_user_id):
    unread_case = '0'
    if admin_user_id is not None:
        unread_case = f'''(
            SELECT COUNT(*)
            FROM messages m
            JOIN users pu ON pu.patient_id = p.id AND pu.role = 'patient'
            WHERE m.sender_id = pu.id
              AND m.recipient_id = {int(admin_user_id)}
              AND COALESCE(m.is_read, 0) = 0
        )'''

    return f'''
        SELECT p.*,
        (SELECT COUNT(*) FROM appointments a WHERE a.patient_id = p.id AND a.is_recurring = 1 AND COALESCE(a.status, 'scheduled') = 'scheduled') as has_recurring,
        (SELECT MIN(a0.appointment_date) FROM appointments a0 WHERE a0.patient_id = p.id AND COALESCE(a0.status, 'scheduled') = 'scheduled' AND a0.appointment_date >= DATE('now')) AS next_appointment_date,
        (
            SELECT a1.appointment_time
            FROM appointments a1
            WHERE a1.patient_id = p.id
              AND COALESCE(a1.status, 'scheduled') = 'scheduled'
              AND a1.appointment_date >= DATE('now')
            ORDER BY a1.appointment_date ASC, a1.appointment_time ASC
            LIMIT 1
        ) AS next_appointment_time,
        {unread_case} AS unread_messages,
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

def _get_patients_where_clause(status, patient_type, search_query, include_group, treatment_method):
    where_query = ""
    params = []

    if status in ['candidate', 'waiting for scheduling', 'waiting']:
        where_query += " AND p.status IN ('candidate', 'waiting for scheduling', 'waiting')"
    elif status != 'all':
        where_query += ' AND p.status = ?'
        params.append(status)

    if patient_type in ('private', 'residency', 'initial-intake', 'diagnosee', 'group'):
        where_query += ' AND COALESCE(p.patient_type, "private") = ?'
        params.append(patient_type)
    elif not include_group:
        where_query += ' AND COALESCE(p.patient_type, "private") != "group"'

    if search_query:
        where_query += ' AND (LOWER(p.name) LIKE ? OR LOWER(COALESCE(p.email, "")) LIKE ? OR LOWER(COALESCE(p.phone, "")) LIKE ?)'
        like_value = f"%{search_query.lower()}%"
        params.extend([like_value, like_value, like_value])

    if treatment_method and treatment_method != 'all':
        where_query += ' AND COALESCE(p.treatment_method, "") = ?'
        params.append(treatment_method)

    return where_query, params

def _get_patients_order_clause(sort_by):
    order_map = {
        'name_asc': 'p.name ASC',
        'name_desc': 'p.name DESC',
        'newest': 'p.created_at DESC',
        'oldest': 'p.created_at ASC',
        'manual_order': 'COALESCE(p.sort_order, 999999) ASC, p.created_at DESC',
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
    return " ORDER BY " + order_map.get(sort_by, order_map['status_priority'])


def fetch_patients_by_status(db, status, patient_type='all', search_query='', sort_by='status_priority', admin_user_id=None, include_group=True, treatment_method='all'):
    select_clause = _get_patients_select_clause(admin_user_id)
    where_clause, params = _get_patients_where_clause(status, patient_type, search_query, include_group, treatment_method)
    order_clause = _get_patients_order_clause(sort_by)

    final_query = f"{select_clause}{where_clause}{order_clause}"
    return db.execute(final_query, tuple(params)).fetchall()


@app.route('/crm')
@login_required
def crm_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('patient_home'))

    db = get_db()
    saved_filters = session.get('crm_filters', {})
    status = request.args.get('status', saved_filters.get('status', 'all')).strip()
    clinic_type = request.args.get('clinic_type', saved_filters.get('clinic_type', 'all')).strip()
    search_query = request.args.get('q', saved_filters.get('q', '')).strip()
    sort_by = request.args.get('sort', saved_filters.get('sort', 'status_priority')).strip()
    include_group_raw = request.args.get('include_group', saved_filters.get('include_group', 'false'))
    include_group = include_group_raw == 'true'
    treatment_method = request.args.get('treatment_method', saved_filters.get('treatment_method', 'all')).strip()

    if status not in {'all', 'ongoing', 'candidate', 'waiting', 'waiting for scheduling', 'archived'}:
        status = 'all'
    if clinic_type not in {'all', 'private', 'residency', 'group'}:
        clinic_type = 'all'
    if sort_by not in {'status_priority', 'name_asc', 'name_desc', 'newest', 'oldest', 'manual_order'}:
        sort_by = 'status_priority'

    session['crm_filters'] = {
        'status': status,
        'clinic_type': clinic_type,
        'q': search_query,
        'sort': sort_by,
        'include_group': 'true' if include_group else 'false',
        'treatment_method': treatment_method
    }
    
    patient_type = clinic_type

    treatment_method_options = db.execute(
        'SELECT label FROM treatment_method_options ORDER BY display_order ASC, label ASC'
    ).fetchall()
    treatment_method_labels = [row['label'] for row in treatment_method_options]

    patients = fetch_patients_by_status(db, status, patient_type=patient_type, search_query=search_query, sort_by=sort_by, admin_user_id=current_user.id, include_group=include_group, treatment_method=treatment_method)
    counts_row = db.execute('''
        SELECT
            COUNT(*) AS all_count,
            SUM(CASE WHEN status = 'ongoing' THEN 1 ELSE 0 END) AS ongoing_count,
            SUM(CASE WHEN status IN ('candidate', 'waiting for scheduling', 'waiting') THEN 1 ELSE 0 END) AS candidate_waiting_count,
            SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) AS archived_count
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
    ''').fetchone()
    counts = {
        'all': counts_row['all_count'] or 0,
        'ongoing': counts_row['ongoing_count'] or 0,
        'candidate_waiting': counts_row['candidate_waiting_count'] or 0,
        'archived': counts_row['archived_count'] or 0
    }
    reminders = send_appointment_reminders(db)
    return render_template('crm.html', patients=patients, status=status, counts=counts,
                           clinic_type=clinic_type, search_query=search_query, sort_by=sort_by,
                           include_group=include_group, reminders=reminders,
                           treatment_method=treatment_method,
                           treatment_method_options=treatment_method_labels)


def _get_dashboard_today_appointments(db, today):
    return db.execute('''
        SELECT a.id, a.appointment_date, a.appointment_time, a.duration_minutes,
               a.meeting_type, a.meeting_link, a.is_recurring,
               p.id AS patient_id, p.name AS patient_name,
               p.status AS patient_status, p.treatment_method
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE COALESCE(a.status, 'scheduled') = 'scheduled'
          AND COALESCE(p.is_deleted, 0) = 0
          AND a.appointment_date = ?
        ORDER BY a.appointment_time ASC
    ''', (today.isoformat(),)).fetchall()

def _get_dashboard_week_appointments(db, today, week_end):
    return db.execute('''
        SELECT a.id, a.appointment_date, a.appointment_time, a.meeting_type,
               p.id AS patient_id, p.name AS patient_name
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE COALESCE(a.status, 'scheduled') = 'scheduled'
          AND COALESCE(p.is_deleted, 0) = 0
          AND a.appointment_date > ?
          AND a.appointment_date <= ?
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    ''', (today.isoformat(), week_end.isoformat())).fetchall()

def _get_dashboard_patient_counts(db):
    counts_row = db.execute('''
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'ongoing' THEN 1 ELSE 0 END) AS ongoing,
            SUM(CASE WHEN status IN ('candidate', 'waiting for scheduling', 'waiting') THEN 1 ELSE 0 END) AS waiting,
            SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) AS archived
        FROM patients WHERE COALESCE(is_deleted, 0) = 0
    ''').fetchone()
    return {
        'total':   counts_row['total']   or 0,
        'ongoing': counts_row['ongoing'] or 0,
        'waiting': counts_row['waiting'] or 0,
        'archived':counts_row['archived']or 0,
    }

def _get_dashboard_unread_count(db, user_id):
    return db.execute(
        'SELECT COUNT(*) FROM messages WHERE recipient_id = ? AND COALESCE(is_read, 0) = 0',
        (user_id,)
    ).fetchone()[0]

def _get_dashboard_followup_patients(db):
    return db.execute('''
        SELECT p.id, p.name, p.status, MAX(a.appointment_date) AS last_appt_date
        FROM patients p
        JOIN appointments a ON a.patient_id = p.id
        WHERE p.status = 'candidate'
          AND COALESCE(p.is_deleted, 0) = 0
          AND a.is_recurring = 0
          AND COALESCE(a.status, 'scheduled') = 'scheduled'
          AND a.appointment_date < DATE('now')
          AND NOT EXISTS (
              SELECT 1 FROM appointments a2
              WHERE a2.patient_id = p.id
                AND COALESCE(a2.status, 'scheduled') = 'scheduled'
                AND a2.appointment_date >= DATE('now')
          )
        GROUP BY p.id
        ORDER BY last_appt_date ASC
        LIMIT 8
    ''').fetchall()

def _get_dashboard_waiting_patients(db):
    return db.execute('''
        SELECT p.id, p.name, p.created_at
        FROM patients p
        WHERE p.status IN ('waiting', 'waiting for scheduling')
          AND COALESCE(p.is_deleted, 0) = 0
          AND NOT EXISTS (
              SELECT 1 FROM appointments a WHERE a.patient_id = p.id
                AND COALESCE(a.status, 'scheduled') = 'scheduled'
                AND a.appointment_date >= DATE('now')
          )
        ORDER BY p.created_at ASC
        LIMIT 6
    ''').fetchall()

def _get_dashboard_recent_patients(db):
    return db.execute('''
        SELECT id, name, status, patient_type, treatment_method, created_at
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
        ORDER BY created_at DESC
        LIMIT 6
    ''').fetchall()

def _get_dashboard_recent_activity(db):
    return db.execute('''
        SELECT al.action, al.details, al.created_at,
               p.name AS patient_name, p.id AS patient_id
        FROM audit_logs al
        LEFT JOIN patients p ON p.id = al.patient_id
        ORDER BY al.created_at DESC
        LIMIT 10
    ''').fetchall()

def _get_dashboard_missing_recurring(db):
    return db.execute('''
        SELECT id, name
        FROM patients
        WHERE status = 'ongoing'
          AND COALESCE(is_deleted, 0) = 0
          AND NOT EXISTS (
              SELECT 1 FROM appointments a
              WHERE a.patient_id = patients.id
                AND a.is_recurring = 1
                AND COALESCE(a.status, 'scheduled') = 'scheduled'
          )
        ORDER BY name ASC
        LIMIT 6
    ''').fetchall()


@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """At-a-glance clinic overview for the admin."""
    if current_user.role != 'admin':
        return redirect(url_for('patient_home'))

    db = get_db()
    today = datetime.now().date()
    week_end = today + timedelta(days=6)

    today_appointments = _get_dashboard_today_appointments(db, today)
    week_appointments = _get_dashboard_week_appointments(db, today, week_end)
    counts = _get_dashboard_patient_counts(db)
    unread_count = _get_dashboard_unread_count(db, current_user.id)
    followup_patients = _get_dashboard_followup_patients(db)
    waiting_patients = _get_dashboard_waiting_patients(db)
    recent_patients = _get_dashboard_recent_patients(db)
    recent_activity = _get_dashboard_recent_activity(db)
    missing_recurring = _get_dashboard_missing_recurring(db)

    return render_template('admin_home.html',
                           today=today,
                           today_appointments=today_appointments,
                           week_appointments=week_appointments,
                           counts=counts,
                           unread_count=unread_count,
                           followup_patients=followup_patients,
                           waiting_patients=waiting_patients,
                           recent_patients=recent_patients,
                           recent_activity=recent_activity,
                           missing_recurring=missing_recurring)


@app.route('/api/patients/reorder', methods=['POST'])
@login_required
def api_patients_reorder():
    data = request.json
    if not data or 'order' not in data:
        return jsonify({'error': 'No order provided'}), 400
    db = get_db()

    for idx, patient_id in enumerate(data['order']):
        db.execute('UPDATE patients SET sort_order = ? WHERE id = ?', (idx, patient_id))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/treatment_method_options', methods=['GET'])
@login_required
def api_treatment_method_options_get():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    rows = db.execute('SELECT id, label FROM treatment_method_options ORDER BY display_order ASC, label ASC').fetchall()
    return jsonify([{'id': r['id'], 'label': r['label']} for r in rows])


@app.route('/api/treatment_method_options', methods=['POST'])
@login_required
def api_treatment_method_options_add():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.get_json(silent=True)
    label = (data or {}).get('label', '').strip()
    if not label:
        return jsonify({'error': 'Label is required'}), 400
    if len(label) > 80:
        return jsonify({'error': 'Label too long'}), 400
    db = get_db()
    try:
        db.execute('INSERT INTO treatment_method_options (label) VALUES (?)', (label,))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Option already exists'}), 409
    return jsonify({'ok': True, 'label': label}), 201


@app.route('/api/treatment_method_options/<int:option_id>', methods=['DELETE'])
@login_required
def api_treatment_method_options_delete(option_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    db.execute('DELETE FROM treatment_method_options WHERE id = ?', (option_id,))
    db.commit()
    return jsonify({'ok': True})


@app.route('/patient/home')
@login_required
def patient_home():
    if current_user.role != 'patient':
        return redirect(url_for('patients'))

    db = get_db()
    patient_id = current_user.patient_id
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()

    upcoming = build_patient_upcoming_events(db, patient_id, days_ahead=120, limit=10)

    messages = db.execute('''
        SELECT m.*, u.username as sender_name
        FROM messages m
        LEFT JOIN users u ON m.sender_id = u.id
        WHERE m.sender_id = ? OR m.recipient_id = ?
        ORDER BY m.timestamp ASC
        LIMIT 20
    ''', (current_user.id, current_user.id)).fetchall()

    assigned_resources = db.execute('''
        SELECT r.*
        FROM resources r
        JOIN patient_resources pr ON r.id = pr.resource_id
        WHERE pr.patient_id = ?
        ORDER BY pr.assigned_at DESC
    ''', (patient_id,)).fetchall()

    receipts = db.execute('''
        SELECT *
        FROM receipts
        WHERE patient_id = ?
        ORDER BY created_at DESC
    ''', (patient_id,)).fetchall()

    db.execute('UPDATE messages SET is_read = 1 WHERE recipient_id = ?', (current_user.id,))
    db.commit()

    return render_template('patient_home.html', patient=patient,
                           upcoming=upcoming, messages=messages,
                           assigned_resources=assigned_resources,
                           receipts=receipts)


@app.route('/dashboard')
@login_required
def patient_dashboard():
    """Enhanced patient engagement dashboard with stats and insights"""
    db = get_db()
    
    if current_user.role == 'admin':
        return redirect(url_for('patients'))
    
    patient_id = current_user.patient_id
    patient = db.execute(
        'SELECT * FROM patients WHERE id = ?', 
        (patient_id,)
    ).fetchone()
    
    if not patient:
        return redirect(url_for('patient_home'))
    
    # Get upcoming appointments
    today = datetime.now().date()
    upcoming_appointments = db.execute('''
        SELECT * FROM appointments
        WHERE patient_id = ?
        AND appointment_date >= ?
        AND COALESCE(status, 'scheduled') = 'scheduled'
        ORDER BY appointment_date ASC, appointment_time ASC
        LIMIT 5
    ''', (patient_id, today.isoformat())).fetchall()
    
    # Get total appointment count
    total_appointments = db.execute(
        'SELECT COUNT(*) as count FROM appointments WHERE patient_id = ?',
        (patient_id,)
    ).fetchone()['count']
    
    # Get notes/progress
    recent_notes = db.execute('''
        SELECT * FROM notes
        WHERE patient_id = ?
        ORDER BY created_at DESC
        LIMIT 3
    ''', (patient_id,)).fetchall()
    
    # Get therapy goals
    goals = db.execute('''
        SELECT * FROM goals
        WHERE patient_id = ?
        AND status = 'active'
        ORDER BY created_at DESC
    ''', (patient_id,)).fetchall()
    
    # Calculate engagement metrics
    days_since_last_session = None
    if total_appointments > 0:
        last_appointment = db.execute('''
            SELECT appointment_date FROM appointments
            WHERE patient_id = ?
            ORDER BY appointment_date DESC
            LIMIT 1
        ''', (patient_id,)).fetchone()
        
        if last_appointment:
            last_date = datetime.fromisoformat(last_appointment['appointment_date']).date()
            days_since_last_session = (today - last_date).days
    
    # Get zoom/online meetings count
    zoom_meetings = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND meeting_type IN ('zoom', 'google-meet', 'online')
    ''', (patient_id,)).fetchone()['count']
    
    engagement_data = {
        'total_appointments': total_appointments,
        'upcoming_appointments': len(upcoming_appointments),
        'days_since_last': days_since_last_session,
        'zoom_meetings': zoom_meetings,
        'active_goals': len(goals),
        'recent_notes': len(recent_notes)
    }
    
    return render_template('patient_dashboard.html',
        patient=patient,
        upcoming_appointments=upcoming_appointments,
        recent_notes=recent_notes,
        goals=goals,
        engagement=engagement_data
    )


@app.route('/api/appointments/upcoming')
@login_required
def api_upcoming_appointments():
    """API endpoint for upcoming appointments with meeting info"""
    db = get_db()
    
    today = datetime.now().date()
    appointments = db.execute('''
        SELECT a.*, p.name as patient_name
        FROM appointments a
        LEFT JOIN patients p ON p.id = a.patient_id
        WHERE a.patient_id = ?
        AND a.appointment_date >= ?
        AND COALESCE(a.status, 'scheduled') = 'scheduled'
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
        LIMIT 10
    ''', (current_user.patient_id, today.isoformat())).fetchall()
    
    result = []
    for appt in appointments:
        appt_date = datetime.fromisoformat(appt['appointment_date']).date()
        days_away = (appt_date - today).days
        
        result.append({
            'id': appt['id'],
            'date': appt['appointment_date'],
            'time': appt['appointment_time'],
            'days_away': days_away,
            'meeting_type': appt['meeting_type'] or 'in-person',
            'meeting_link': appt['meeting_link'],
            'is_today': days_away == 0,
            'is_tomorrow': days_away == 1,
            'patient_name': appt['patient_name']
        })
    
    return jsonify(result)


@app.route('/api/engagement/stats')
@login_required
def api_engagement_stats():
    """Get engagement statistics for the patient"""
    db = get_db()
    
    total_appts = db.execute(
        'SELECT COUNT(*) as count FROM appointments WHERE patient_id = ?',
        (current_user.patient_id,)
    ).fetchone()['count']
    
    completed_appts = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND COALESCE(status, 'scheduled') = 'completed'
    ''', (current_user.patient_id,)).fetchone()['count']
    
    this_month_appts = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND strftime('%Y-%m', appointment_date) = strftime('%Y-%m', 'now')
    ''', (current_user.patient_id,)).fetchone()['count']
    
    online_appts = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND meeting_type IN ('zoom', 'google-meet', 'online')
    ''', (current_user.patient_id,)).fetchone()['count']
    
    return jsonify({
        'total_appointments': total_appts,
        'completed_appointments': completed_appts,
        'appointments_this_month': this_month_appts,
        'online_appointments': online_appts,
        'completion_rate': round((completed_appts / max(total_appts, 1)) * 100) if total_appts > 0 else 0
    })


@app.route('/patient/appointment/<int:appointment_id>/request_cancel', methods=['POST'])
@login_required
def request_cancel_appointment(appointment_id):
    if current_user.role != 'patient':
        return 'Unauthorized', 403

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash('Please explain why you want to cancel.')
        return redirect(url_for('patient_home'))

    db = get_db()
    appointment = db.execute('''
        SELECT a.id, a.patient_id, a.appointment_date, a.appointment_time, a.meeting_type, p.name AS patient_name
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE a.id = ? AND a.patient_id = ?
    ''', (appointment_id, current_user.patient_id)).fetchone()
    if not appointment:
        return 'Appointment not found', 404

    appointment_dt = datetime.combine(
        parse_date_safe(appointment['appointment_date']),
        parse_time_safe(appointment['appointment_time'])
    )
    lead_time = format_lead_time_for_notice(appointment_dt)
    admin_message = (
        f"System cancellation request from {appointment['patient_name']}: "
        f"appointment on {appointment['appointment_date']} at {appointment['appointment_time']}. "
        f"Time before meeting: {lead_time}. Notes: {reason}"
    )
    patient_ack = (
        f"System: Your cancellation request for {appointment['appointment_date']} at {appointment['appointment_time']} was sent. "
        f"Time before meeting: {lead_time}. Notes: {reason}"
    )

    add_patient_chat_request(
        db,
        current_user.id,
        current_user.patient_id,
        admin_message,
        patient_ack,
        audit_action='patient-cancel-request',
        audit_details=admin_message
    )
    db.commit()
    flash('Cancellation request sent.')
    return redirect(url_for('patient_home'))


@app.route('/patient/request_booking_access', methods=['POST'])
@login_required
def request_booking_access():
    if current_user.role != 'patient':
        return 'Unauthorized', 403

    notes = (request.form.get('notes') or '').strip()
    if not notes:
        flash('Please add a note for your booking request.')
        return redirect(url_for('patient_home'))

    db = get_db()
    patient = db.execute('SELECT id, name, can_self_schedule FROM patients WHERE id = ?', (current_user.patient_id,)).fetchone()
    if not patient:
        return 'Patient not found', 404

    next_appointment = db.execute('''
        SELECT appointment_date, appointment_time
        FROM appointments
        WHERE patient_id = ? AND COALESCE(status, 'scheduled') = 'scheduled' AND datetime(appointment_date || ' ' || appointment_time) >= datetime('now')
        ORDER BY appointment_date ASC, appointment_time ASC
        LIMIT 1
    ''', (current_user.patient_id,)).fetchone()
    next_fragment = ''
    if next_appointment:
        next_fragment = f" Current scheduled meeting: {next_appointment['appointment_date']} at {next_appointment['appointment_time']}."

    admin_message = (
        f"System booking request from {patient['name']}: patient asked to open self-booking for another meeting from available slots."
        f"{next_fragment} Notes: {notes}"
    )
    patient_ack = (
        'System: Your request for another meeting was sent to the clinic. '
        'If approved, self-booking can be opened for you from the available slots. '
        f'Notes: {notes}'
    )

    add_patient_chat_request(
        db,
        current_user.id,
        current_user.patient_id,
        admin_message,
        patient_ack,
        audit_action='patient-booking-request',
        audit_details=admin_message
    )
    db.commit()
    flash('Booking request sent.')
    return redirect(url_for('patient_home'))


@app.route('/patient/receipt/<int:receipt_id>/download')
@login_required
def download_receipt(receipt_id):
    db = get_db()
    receipt = db.execute('SELECT * FROM receipts WHERE id = ?', (receipt_id,)).fetchone()
    if not receipt:
        return 'Receipt not found', 404

    if current_user.role == 'patient':
        if int(receipt['patient_id']) != int(current_user.patient_id or 0):
            return 'Unauthorized', 403
    elif current_user.role != 'admin':
        return 'Unauthorized', 403

    content = (
        'Private Clinic Service Receipt\n'
        '-----------------------------\n'
        f'Receipt ID: {receipt["id"]}\n'
        f'Patient ID: {receipt["patient_id"]}\n'
        f'Amount: {receipt["amount"]}\n'
        f'Description: {receipt["description"] or ""}\n'
        f'Created At: {receipt["created_at"] or ""}\n'
    )
    filename = f'receipt_{receipt["id"]}.txt'
    return Response(
        content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )

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

@app.route('/admin/resources/<int:resource_id>/edit', methods=['POST'])
@login_required
def edit_resource(resource_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Title is required.')
        return redirect(url_for('manage_resources'))
    description = request.form.get('description', '')
    url = request.form.get('url', '')
    is_public = 1 if request.form.get('is_public') else 0
    db = get_db()
    db.execute('UPDATE resources SET title=?, description=?, url=?, is_public=? WHERE id=?',
               (title, description, url, is_public, resource_id))
    db.commit()
    flash('Resource updated.')
    return redirect(url_for('manage_resources'))

@app.route('/admin/resources/<int:resource_id>/delete', methods=['POST'])
@login_required
def delete_resource(resource_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    db.execute('DELETE FROM patient_resources WHERE resource_id = ?', (resource_id,))
    db.execute('DELETE FROM resources WHERE id = ?', (resource_id,))
    db.commit()
    flash('Resource deleted.')
    return redirect(url_for('manage_resources'))

@app.route('/patient/<int:patient_id>/unassign_resource/<int:resource_id>', methods=['POST'])
@login_required
def unassign_resource(patient_id, resource_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    db.execute('DELETE FROM patient_resources WHERE patient_id = ? AND resource_id = ?', (patient_id, resource_id))
    db.commit()
    flash('Resource unassigned.')
    return redirect_to_patient_tab(patient_id, 'info')

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

            if _verify_totp_code(pending_user['totp_secret'], otp_code):
                session.pop('pending_2fa_user_id', None)
                session.pop('pending_2fa_username', None)
                return _login_redirect_for_user(pending_user)

            flash('Invalid authenticator code.')
            return render_template('login.html', requires_otp=True, pending_username=pending_username)

        session.pop('pending_2fa_user_id', None)
        session.pop('pending_2fa_username', None)

        username = request.form['username']
        password = request.form['password']

        client_ip = request.remote_addr or ''
        if not app.config.get('TESTING') and _is_login_rate_limited(client_ip):
            flash('Too many failed login attempts. Please try again in 15 minutes.')
            return render_template('login.html')

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user:
            password_correct = check_password_hash(user['password_hash'], password)
        else:
            check_password_hash(DUMMY_PASSWORD_HASH, password)
            password_correct = False

        if user and password_correct:
            if not user['is_active']:
                 flash('Account is disabled. Contact administrator.')
                 return render_template('login.html')

            _clear_failed_logins(client_ip)

            # REQUIRE 2FA for all admin accounts in PRODUCTION
            # IN TESTING: Allow bypass for admin logins
            if user['role'] == 'admin' and not app.config.get('TESTING'):
                # Ensure admin has TOTP configured
                if not user['totp_enabled'] or not user['totp_secret']:
                    return _login_redirect_for_user(user)
                
                session['pending_2fa_user_id'] = int(user['id'])
                session['pending_2fa_username'] = user['username']
                flash('Two-factor authentication required. Check your authenticator app.')
                return render_template('login.html', requires_otp=True, pending_username=user['username'])

            return _login_redirect_for_user(user)
        else:
            if not app.config.get('TESTING'):
                _record_failed_login(client_ip)
            flash('Invalid username or password')

    if pending_user_id:
        return render_template('login.html', requires_otp=True, pending_username=pending_username)

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
        if patient_type not in ('private', 'residency', 'initial-intake', 'diagnosee', 'group'):
            patient_type = 'private'
        has_intake_tab = 1 if patient_type in ('initial-intake', 'diagnosee') else 0
        intake_assessment = request.form.get('intake_assessment', '').strip() if patient_type in ('initial-intake', 'diagnosee') else ''
        intake_questionnaire = request.form.get('intake_questionnaire', '').strip() if patient_type in ('initial-intake', 'diagnosee') else ''
        treatment_method = request.form.get('treatment_method', '').strip() or None

        if not name:
            flash('Name is required!')
        else:
            db = get_db()
            db.execute('''INSERT INTO patients
                                  (name, status, email, phone, birth_date, id_number, patient_type, has_intake_tab, intake_assessment, intake_questionnaire, treatment_method)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                              (name, status, email, phone, birth_date, id_number, patient_type, has_intake_tab,
                               intake_assessment or None, intake_questionnaire or None, treatment_method))
            db.commit()
            return redirect(url_for('patients', status=status))

    db = get_db()
    treatment_method_options = [r['label'] for r in db.execute(
        'SELECT label FROM treatment_method_options ORDER BY display_order ASC, label ASC'
    ).fetchall()]
    return render_template('add_patient.html', treatment_method_options=treatment_method_options)

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


def _get_patient_notes(db, patient_id):
    notes = db.execute('''
        SELECT * FROM notes
        WHERE patient_id = ?
        ORDER BY COALESCE(note_date, date(created_at)) DESC,
                 CAST(COALESCE(session_number, '0') AS INTEGER) DESC,
                 created_at DESC
    ''', (patient_id,)).fetchall()

    if notes:
        seen_sessions: dict = {}
        unnumbered = []
        for note in notes:
            sn = int(note['session_number'] or 0)
            if sn == 0:
                unnumbered.append(note)
                continue
            existing = seen_sessions.get(sn)
            if existing is None:
                seen_sessions[sn] = note
            else:
                existing_has_content = bool((existing['content'] or '').strip())
                note_has_content = bool((note['content'] or '').strip())
                if note_has_content and not existing_has_content:
                    seen_sessions[sn] = note
                elif note_has_content == existing_has_content and note['id'] > existing['id']:
                    seen_sessions[sn] = note
        numbered = sorted(seen_sessions.values(),
                          key=lambda n: (-(int(n['session_number'] or 0)), -(n['id'])))
        notes = numbered + unnumbered
    return notes

def _get_patient_group_data(db, patient_id):
    group_attendance_rows = db.execute('''
        SELECT gsa.session_id,
               gsa.attendance_status,
               gsa.absence_reason,
               gsa.notified_on_time,
               gsa.attendance_note,
               gsa.updated_at,
               gs.group_id,
               gs.session_date,
               gs.session_time,
               gs.title AS session_title,
               gs.session_summary,
               g.name AS group_name
        FROM group_session_attendance gsa
        JOIN group_sessions gs ON gs.id = gsa.session_id
        JOIN groups g ON g.id = gs.group_id
        WHERE gsa.patient_id = ?
        ORDER BY gs.session_date DESC, gs.session_time DESC
    ''', (patient_id,)).fetchall()

    group_membership_rows = db.execute('''
        SELECT h.id,
               h.group_id,
               g.name AS group_name,
               h.joined_at,
               h.left_at,
               COALESCE(h.role, 'member') AS role
        FROM group_member_history h
        JOIN groups g ON g.id = h.group_id
        WHERE h.patient_id = ?
        ORDER BY h.joined_at DESC
    ''', (patient_id,)).fetchall()

    group_arrived_count = sum(1 for row in group_attendance_rows if (row['attendance_status'] or '') == 'present')
    return group_attendance_rows, group_membership_rows, group_arrived_count

def _get_patient_messages(db, user, current_user_id):
    messages = []
    unread_messages_count = 0
    if user:
        unread_messages_count = db.execute('''
            SELECT COUNT(*) AS c
            FROM messages
            WHERE sender_id = ? AND recipient_id = ? AND COALESCE(is_read, 0) = 0
        ''', (user['id'], current_user_id)).fetchone()['c']
        messages = db.execute('''
            SELECT m.*, u.username as sender_name
            FROM messages m
            LEFT JOIN users u ON m.sender_id = u.id
            WHERE (m.sender_id = ? AND m.recipient_id = ?)
               OR (m.sender_id = ? AND m.recipient_id = ?)
            ORDER BY timestamp ASC
        ''', (current_user_id, user['id'], user['id'], current_user_id)).fetchall()
    return messages, unread_messages_count

def _get_patient_behavior_info(notes):
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
    return behavior_options, latest_behavior

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

    notes = _get_patient_notes(db, patient_id)
    files = db.execute('SELECT * FROM files WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    receipts = db.execute('SELECT * FROM receipts WHERE patient_id = ? ORDER BY created_at DESC', (patient_id,)).fetchall()
    appointments = db.execute('SELECT * FROM appointments WHERE patient_id = ? ORDER BY appointment_date DESC, appointment_time DESC', (patient_id,)).fetchall()

    group_attendance_rows, group_membership_rows, group_arrived_count = _get_patient_group_data(db, patient_id)

    messages, unread_messages_count = _get_patient_messages(db, user, current_user.id)

    # Get resources for assignment
    all_resources = db.execute('SELECT * FROM resources WHERE is_public = 0 ORDER BY title ASC').fetchall()

    # Get assigned resources
    assigned_resources = db.execute('''
        SELECT r.*
        FROM resources r
        JOIN patient_resources pr ON r.id = pr.resource_id
        WHERE pr.patient_id = ?
    ''', (patient_id,)).fetchall()

    behavior_options, latest_behavior = _get_patient_behavior_info(notes)

    active_tab = request.args.get('tab', 'info')
    intake_enabled = patient['patient_type'] in ('initial-intake', 'diagnosee') or int(patient['has_intake_tab'] or 0) == 1
    if active_tab == 'intake' and not intake_enabled:
        active_tab = 'info'

    if user and active_tab == 'messages' and unread_messages_count:
        db.execute(
            'UPDATE messages SET is_read = 1 WHERE sender_id = ? AND recipient_id = ? AND COALESCE(is_read, 0) = 0',
            (user['id'], current_user.id)
        )
        db.commit()
        unread_messages_count = 0

    latest_note = notes[0] if notes else None
    intake_form_data = parse_intake_questionnaire(patient['intake_questionnaire'], patient['intake_assessment'])
    next_session_row = db.execute('''
        SELECT COALESCE(MAX(CAST(COALESCE(session_number, '0') AS INTEGER)), 0) AS max_session
        FROM notes
        WHERE patient_id = ?
    ''', (patient_id,)).fetchone()
    suggested_session_number = int(next_session_row['max_session'] or 0) + 1
    suggested_note_date = datetime.now().date().isoformat()

    supervisions = db.execute(
        'SELECT * FROM supervisions WHERE patient_id = ? ORDER BY supervision_date DESC, created_at DESC',
        (patient_id,)
    ).fetchall()

    diagnosis_documents = db.execute(
        'SELECT * FROM diagnosis_documents WHERE patient_id = ? ORDER BY created_at DESC, id DESC',
        (patient_id,)
    ).fetchall()

    goals = db.execute(
        'SELECT * FROM goals WHERE patient_id = ? ORDER BY created_at ASC',
        (patient_id,)
    ).fetchall()

    return render_template('patient_detail.html', patient=patient, notes=notes, files=files, receipts=receipts, user=user, appointments=appointments, messages=messages, all_resources=all_resources, assigned_resources=assigned_resources, active_tab=active_tab, behavior_options=behavior_options, latest_behavior=latest_behavior, latest_note=latest_note, suggested_session_number=suggested_session_number, suggested_note_date=suggested_note_date, intake_form_data=intake_form_data, unread_messages_count=unread_messages_count, group_attendance_rows=group_attendance_rows, group_membership_rows=group_membership_rows, group_arrived_count=group_arrived_count, supervisions=supervisions, diagnosis_documents=diagnosis_documents, goals=goals)


@app.route('/admin/patient/<int:patient_id>/portal_preview')
@login_required
def admin_portal_preview(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0', (patient_id,)).fetchone()
    if patient is None:
        return 'Patient not found', 404

    patient_user = db.execute('SELECT * FROM users WHERE patient_id = ? AND role = "patient"', (patient_id,)).fetchone()
    upcoming = build_patient_upcoming_events(db, patient_id, days_ahead=120, limit=10)
    assigned_resources = db.execute('''
        SELECT r.*
        FROM resources r
        JOIN patient_resources pr ON r.id = pr.resource_id
        WHERE pr.patient_id = ?
        ORDER BY pr.assigned_at DESC
    ''', (patient_id,)).fetchall()
    receipts = db.execute('''
        SELECT *
        FROM receipts
        WHERE patient_id = ?
        ORDER BY created_at DESC
    ''', (patient_id,)).fetchall()

    messages = []
    if patient_user:
        messages = db.execute('''
            SELECT m.*, u.username as sender_name
            FROM messages m
            LEFT JOIN users u ON m.sender_id = u.id
            WHERE (m.sender_id = ? AND m.recipient_id = ?)
               OR (m.sender_id = ? AND m.recipient_id = ?)
            ORDER BY m.timestamp ASC
            LIMIT 20
        ''', (current_user.id, patient_user['id'], patient_user['id'], current_user.id)).fetchall()

    return render_template(
        'patient_home.html',
        patient=patient,
        upcoming=upcoming,
        messages=messages,
        assigned_resources=assigned_resources,
        receipts=receipts,
        preview_mode=True,
        preview_patient_id=patient_id,
        unread_messages=0
    )


def redirect_to_patient_tab(patient_id, default_tab='info'):
    tab = request.form.get('active_tab') or request.args.get('tab') or default_tab
    return redirect(url_for('patient_detail', patient_id=patient_id, tab=tab))


def get_primary_admin_user(db):
    return db.execute(
        "SELECT id, COALESCE(display_name, username) AS name FROM users WHERE role = 'admin' AND COALESCE(is_active, 1) = 1 ORDER BY id ASC LIMIT 1"
    ).fetchone()


def format_lead_time_for_notice(target_dt, reference_dt=None):
    reference_dt = reference_dt or datetime.now()
    delta_seconds = int((target_dt - reference_dt).total_seconds())
    if delta_seconds <= 0:
        return 'after the meeting time'

    days, remainder = divmod(delta_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f'{days} day' + ('s' if days != 1 else ''))
    if hours:
        parts.append(f'{hours} hour' + ('s' if hours != 1 else ''))
    if minutes or not parts:
        parts.append(f'{minutes} minute' + ('s' if minutes != 1 else ''))
    return ', '.join(parts)


def add_patient_chat_request(db, patient_user_id, patient_id, admin_message, patient_ack_message, audit_action=None, audit_details=None):
    admin_user = get_primary_admin_user(db)
    if not admin_user:
        return False

    db.execute(
        'INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
        (patient_user_id, admin_user['id'], admin_message)
    )
    db.execute(
        'INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
        (admin_user['id'], patient_user_id, patient_ack_message)
    )
    db.execute('INSERT INTO notifications (message, is_read) VALUES (?, 0)', (admin_message,))
    if audit_action:
        db.execute(
            'INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)',
            (patient_id, audit_action, audit_details or admin_message)
        )
    return True


# ── Patient supervision ───────────────────────────────────────────────────────

@app.route('/patient/<int:patient_id>/supervision', methods=['POST'])
@login_required
def add_patient_supervision(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    if not db.execute('SELECT id FROM patients WHERE id = ? AND COALESCE(is_deleted,0)=0', (patient_id,)).fetchone():
        return 'Patient not found', 404
    sup_date = (request.form.get('supervision_date') or '').strip()
    supervisor = (request.form.get('supervisor_name') or '').strip()
    content = (request.form.get('content') or '').strip()
    if not sup_date or not content:
        flash('Date and content are required.')
        return redirect(url_for('patient_detail', patient_id=patient_id, tab='supervision'))
    db.execute(
        'INSERT INTO supervisions (patient_id, supervision_date, supervisor_name, content) VALUES (?,?,?,?)',
        (patient_id, sup_date, supervisor or None, content)
    )
    db.commit()
    flash('Supervision record added.')
    return redirect(url_for('patient_detail', patient_id=patient_id, tab='supervision'))


@app.route('/patient/<int:patient_id>/supervision/<int:sup_id>/delete', methods=['POST'])
@login_required
def delete_patient_supervision(patient_id, sup_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    db.execute('DELETE FROM supervisions WHERE id = ? AND patient_id = ?', (sup_id, patient_id))
    db.commit()
    flash('Supervision record deleted.')
    return redirect(url_for('patient_detail', patient_id=patient_id, tab='supervision'))


@app.route('/patient/<int:patient_id>/diagnosis_documents/add', methods=['POST'])
@login_required
def add_diagnosis_document(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    if 'diagnosis_file' not in request.files:
        flash('No file selected.')
        return redirect(url_for('patient_detail', patient_id=patient_id, tab='intake'))

    uploaded = request.files['diagnosis_file']
    if uploaded.filename == '':
        flash('No file selected.')
        return redirect(url_for('patient_detail', patient_id=patient_id, tab='intake'))

    category = (request.form.get('category') or 'test_document').strip().lower()
    if category not in {'test_document', 'final_result'}:
        category = 'test_document'

    title = (request.form.get('title') or '').strip() or None
    notes = (request.form.get('notes') or '').strip() or None
    original_filename = secure_filename(uploaded.filename)
    ext = os.path.splitext(original_filename)[1].lower()
    if not ext or ext not in ALLOWED_DIAGNOSIS_EXTENSIONS:
        flash('File type not allowed. Accepted: pdf, docx, png, jpg, jpeg, tiff.')
        return redirect(url_for('patient_detail', patient_id=patient_id, tab='intake'))
    stored_filename = f"diag_{patient_id}_{secrets.token_hex(8)}{ext}"

    diagnosis_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'diagnosis', str(patient_id))
    os.makedirs(diagnosis_dir, exist_ok=True)
    uploaded.save(os.path.join(diagnosis_dir, stored_filename))

    db = get_db()
    patient = db.execute('SELECT id FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0', (patient_id,)).fetchone()
    if not patient:
        return 'Patient not found', 404

    db.execute('''
        INSERT INTO diagnosis_documents (patient_id, category, title, original_filename, stored_filename, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (patient_id, category, title, original_filename, stored_filename, notes))
    db.commit()

    flash('Diagnostic document uploaded successfully.')
    return redirect(url_for('patient_detail', patient_id=patient_id, tab='intake'))


@app.route('/patient/<int:patient_id>/diagnosis_documents/<int:doc_id>/download', methods=['GET'])
@login_required
def download_diagnosis_document(patient_id, doc_id):
    db = get_db()
    doc = db.execute('''
        SELECT * FROM diagnosis_documents
        WHERE id = ? AND patient_id = ?
    ''', (doc_id, patient_id)).fetchone()
    if not doc:
        return 'Document not found', 404

    if current_user.role == 'patient' and current_user.patient_id != patient_id:
        return 'Unauthorized', 403

    diagnosis_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'diagnosis', str(patient_id))
    return send_from_directory(
        diagnosis_dir,
        doc['stored_filename'],
        as_attachment=True,
        download_name=doc['original_filename']
    )


@app.route('/patient/<int:patient_id>/diagnosis_documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_diagnosis_document(patient_id, doc_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    db = get_db()
    doc = db.execute('''
        SELECT * FROM diagnosis_documents
        WHERE id = ? AND patient_id = ?
    ''', (doc_id, patient_id)).fetchone()
    if not doc:
        return 'Document not found', 404

    diagnosis_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'diagnosis', str(patient_id))
    os.remove(os.path.join(diagnosis_dir, doc['stored_filename'])) if os.path.exists(os.path.join(diagnosis_dir, doc['stored_filename'])) else None
    db.execute('DELETE FROM diagnosis_documents WHERE id = ? AND patient_id = ?', (doc_id, patient_id))
    db.commit()

    flash('Diagnostic document deleted.')
    return redirect(url_for('patient_detail', patient_id=patient_id, tab='intake'))


def build_external_public_url(endpoint, **values):
    path = url_for(endpoint, _external=False, **values)
    configured_base = (app.config.get('PUBLIC_BASE_URL') or '').strip()
    if configured_base:
        return f"{configured_base.rstrip('/')}{path}"

    forwarded_proto = (request.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip()
    forwarded_host = (request.headers.get('X-Forwarded-Host') or '').split(',')[0].strip()
    forwarded_port = (request.headers.get('X-Forwarded-Port') or '').split(',')[0].strip()
    forwarded_prefix = (request.headers.get('X-Forwarded-Prefix') or '').strip()

    scheme = forwarded_proto or request.scheme
    host = forwarded_host or request.host
    if forwarded_port and forwarded_host and ':' not in forwarded_host and forwarded_port not in ('80', '443'):
        host = f'{forwarded_host}:{forwarded_port}'

    if forwarded_prefix:
        if not forwarded_prefix.startswith('/'):
            forwarded_prefix = f'/{forwarded_prefix}'
        forwarded_prefix = forwarded_prefix.rstrip('/')

    return f'{scheme}://{host}{forwarded_prefix}{path}'


@app.route('/patient/<int:patient_id>/toggle_self_booking', methods=('POST',))
@login_required
def toggle_self_booking(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    db = get_db()
    patient = db.execute('SELECT id, name, can_self_schedule FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return 'Patient not found', 404

    new_value = 0 if int(patient['can_self_schedule'] or 0) == 1 else 1
    db.execute('UPDATE patients SET can_self_schedule = ? WHERE id = ?', (new_value, patient_id))
    db.commit()
    flash(f"Self-booking {'enabled' if new_value == 1 else 'disabled'} for {patient['name']}.")
    return redirect_to_patient_tab(patient_id, 'info')


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

    try:
        excluded_raw = appt['excluded_dates'] or ''
    except (KeyError, IndexError):
        excluded_raw = ''
    excluded = {d.strip() for d in excluded_raw.split(',') if d.strip()}

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
            if occ_date.isoformat() in excluded:
                produced += 1
                if recurrence_count and produced > recurrence_count:
                    return result
                continue

            produced += 1
            if recurrence_count and produced > recurrence_count:
                return result

            if week_start <= occ_date <= week_end:
                result.append(occ_date)

        week_index += 1

    return sorted(result)


def build_recurrence_group_id():
    return secrets.token_hex(16)


def canonical_recurrence_days(appt):
    days = parse_recurrence_days(appt)
    if not days:
        base_date = parse_date_safe(appt['appointment_date'])
        if base_date:
            days = [custom_weekday(base_date)]
    return ','.join(str(day) for day in sorted(set(days)))


def estimate_recurring_series_end(appt):
    base_date = parse_date_safe(appt['appointment_date'])
    if not base_date:
        return None

    explicit_end = parse_date_safe(appt['recurrence_end_date']) if 'recurrence_end_date' in appt.keys() else None
    if explicit_end:
        return explicit_end

    recurrence_count = int(appt['recurrence_count'] or 0) if 'recurrence_count' in appt.keys() and appt['recurrence_count'] else 0
    if recurrence_count > 0:
        interval = max(int(appt['recurrence_interval'] or 1), 1)
        probe_end = base_date + timedelta(weeks=max(interval * recurrence_count, 1) + 8)
        occurrences = recurring_occurrences_between(appt, base_date, probe_end, max_occurrences=recurrence_count)
        if occurrences:
            return occurrences[-1]

    return base_date


def find_related_recurring_appointments(db, appt):
    signature_days = canonical_recurrence_days(appt)
    interval = max(int(appt['recurrence_interval'] or 1), 1)
    cadence_days = max(interval * 7, 1)

    rows = db.execute('''
        SELECT *
        FROM appointments
        WHERE patient_id = ?
          AND COALESCE(is_recurring, 0) = 1
          AND appointment_time = ?
          AND COALESCE(duration_minutes, 60) = ?
          AND COALESCE(recurrence_interval, 1) = ?
        ORDER BY appointment_date ASC, id ASC
    ''', (
        appt['patient_id'],
        appt['appointment_time'],
        int(appt['duration_minutes'] or 60),
        interval,
    )).fetchall()

    candidates = [row for row in rows if canonical_recurrence_days(row) == signature_days]
    if not candidates:
        return [appt]

    target_index = next((index for index, row in enumerate(candidates) if row['id'] == appt['id']), None)
    if target_index is None:
        return [appt]

    cluster_start = target_index
    cluster_end = target_index

    while cluster_start > 0:
        previous = candidates[cluster_start - 1]
        current = candidates[cluster_start]
        previous_end = estimate_recurring_series_end(previous)
        current_start = parse_date_safe(current['appointment_date'])
        if not previous_end or not current_start:
            break
        if (current_start - previous_end).days <= cadence_days + 1:
            cluster_start -= 1
            continue
        break

    while cluster_end < len(candidates) - 1:
        current = candidates[cluster_end]
        following = candidates[cluster_end + 1]
        current_end = estimate_recurring_series_end(current)
        following_start = parse_date_safe(following['appointment_date'])
        if not current_end or not following_start:
            break
        if (following_start - current_end).days <= cadence_days + 1:
            cluster_end += 1
            continue
        break

    return candidates[cluster_start:cluster_end + 1]


def ensure_recurrence_group_id(db, appt):
    existing_group_id = (appt['recurrence_group_id'] or '').strip() if 'recurrence_group_id' in appt.keys() and appt['recurrence_group_id'] else ''
    if existing_group_id:
        return existing_group_id

    related_rows = find_related_recurring_appointments(db, appt)
    discovered_group_id = next(
        ((row['recurrence_group_id'] or '').strip() for row in related_rows if 'recurrence_group_id' in row.keys() and row['recurrence_group_id']),
        ''
    )
    group_id = discovered_group_id or build_recurrence_group_id()
    for row in related_rows:
        db.execute('UPDATE appointments SET recurrence_group_id = ? WHERE id = ?', (group_id, row['id']))
    return group_id


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
          AND COALESCE(p.patient_type, 'private') NOT IN ('initial-intake', 'diagnosee')
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


def _ensure_patient_has_upcoming_booking(db, patient_id, patient_type, today, now_time, horizon_weeks):
    """Helper to check and create upcoming bookings for a single patient."""
    if patient_type in ('initial-intake', 'diagnosee'):
        return False

    has_future = db.execute('''
        SELECT 1
        FROM appointments
        WHERE patient_id = ?
          AND COALESCE(status, 'scheduled') = 'scheduled'
          AND (
              (COALESCE(is_recurring, 0) = 0 AND appointment_date >= ?)
              OR (COALESCE(is_recurring, 0) = 1
                  AND (recurrence_end_date IS NULL
                       OR recurrence_end_date >= DATE(?, ? || ' days')))
          )
        LIMIT 1
    ''', (patient_id, today.isoformat(), today.isoformat(), f'-{horizon_weeks * 7}')).fetchone()
    if has_future:
        return False

    latest = db.execute('''
        SELECT *
        FROM appointments
        WHERE patient_id = ?
        ORDER BY appointment_date DESC, appointment_time DESC, id DESC
        LIMIT 1
    ''', (patient_id,)).fetchone()
    if not latest:
        return False

    base_date = parse_date_safe(latest['appointment_date'])
    base_time = parse_time_safe(latest['appointment_time'])
    if not base_date or not base_time:
        return False

    day_code = custom_weekday(base_date)
    today_code = custom_weekday(today)
    offset_days = (day_code - today_code) % 7
    candidate_date = today + timedelta(days=offset_days)
    if candidate_date == today and base_time <= now_time:
        candidate_date += timedelta(days=7)

    duration = int(latest['duration_minutes'] or 60)
    if duration <= 0:
        duration = 60

    meeting_type = latest['meeting_type'] or 'in-person'
    meeting_link = latest['meeting_link'] or None
    meeting_title = latest['meeting_title'] or None
    meeting_platform = latest['meeting_platform'] if 'meeting_platform' in latest.keys() else None
    if not meeting_platform and meeting_type in ('zoom', 'google-meet'):
        meeting_platform = meeting_type
    save_to_google = int(latest['save_to_google'] or 0) if 'save_to_google' in latest.keys() else 0

    booked = False
    for week_step in range(0, max(1, horizon_weeks)):
        booking_day = candidate_date + timedelta(days=week_step * 7)
        start_dt = combine_dt(booking_day, base_time.strftime('%H:%M'))
        end_dt = start_dt + timedelta(minutes=duration)

        conflict = has_time_conflict(db, booking_day, start_dt, end_dt)
        if conflict:
            continue

        db.execute('''
            INSERT INTO appointments (
                patient_id, appointment_date, appointment_time, duration_minutes,
                meeting_type, meeting_link, meeting_platform, meeting_title,
                save_to_google, status, is_recurring, recurrence_interval,
                recurrence_days, recurrence_end_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', 1, 1, ?, ?)
        ''', (
            patient_id,
            booking_day.isoformat(),
            base_time.strftime('%H:%M'),
            duration,
            meeting_type,
            meeting_link,
            meeting_platform,
            meeting_title,
            save_to_google,
            str(day_code),
            (booking_day + timedelta(days=365)).isoformat()
        ))
        booked = True
        break

    return booked


def ensure_ongoing_patients_have_upcoming_bookings(db, reference_date=None, horizon_weeks=12):
    """Guarantee ongoing patients have at least one upcoming scheduled booking."""
    today = reference_date or datetime.now().date()
    now_time = datetime.now().time()

    rows = db.execute('''
        SELECT id, status, patient_type
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
          AND status = 'ongoing'
    ''').fetchall()

    created = 0
    for patient in rows:
        patient_id = int(patient['id'])
        patient_type = (patient['patient_type'] or 'private').strip().lower()
        if _ensure_patient_has_upcoming_booking(db, patient_id, patient_type, today, now_time, horizon_weeks):
            created += 1

    if created:
        db.commit()
    return created


def ensure_default_recurring_vacancies(db):
    """Seed baseline weekly vacancies when none exist so free slots stay visible."""
    has_future_override = db.execute('''
        SELECT 1
        FROM slots_override
        WHERE status = 'available' AND slot_date >= ?
        LIMIT 1
    ''', (datetime.now().date().isoformat(),)).fetchone()

    has_recurring = db.execute('''
        SELECT 1
        FROM vacancy_recurring
        WHERE COALESCE(is_active, 1) = 1
        LIMIT 1
    ''').fetchone()

    if has_future_override or has_recurring:
        return 0

    # Sunday-Thursday baseline availability blocks.
    default_slots = [
        (0, '09:00', 60), (0, '15:00', 60),
        (1, '09:00', 60), (1, '15:00', 60),
        (2, '09:00', 60), (2, '15:00', 60),
        (3, '09:00', 60), (3, '15:00', 60),
        (4, '09:00', 60), (4, '15:00', 60),
    ]
    for weekday, slot_time, duration in default_slots:
        db.execute('''
            INSERT INTO vacancy_recurring (weekday, slot_time, duration_minutes, is_active)
            VALUES (?, ?, ?, 1)
        ''', (weekday, slot_time, duration))

    db.commit()
    return len(default_slots)


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

    try:
        excluded_raw = appt['excluded_dates'] or ''
    except (KeyError, IndexError):
        excluded_raw = ''
    excluded = {d.strip() for d in excluded_raw.split(',') if d.strip()}

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
            if occ_date.isoformat() in excluded:
                produced += 1
                if recurrence_count and produced > recurrence_count:
                    return occurrences
                continue

            produced += 1
            if recurrence_count and produced > recurrence_count:
                return occurrences

            if range_start <= occ_date <= range_end:
                occurrences.append(occ_date)

        week_index += 1

    return sorted(occurrences)


def build_patient_upcoming_events(db, patient_id, days_ahead=120, limit=20):
    """Return upcoming patient-facing appointment occurrences including recurring series."""
    today = datetime.now().date()
    range_end = today + timedelta(days=days_ahead)

    rows = db.execute('''
        SELECT *
        FROM appointments
        WHERE patient_id = ?
          AND COALESCE(status, 'scheduled') = 'scheduled'
          AND ((COALESCE(is_recurring, 0) = 0 AND appointment_date BETWEEN ? AND ?)
               OR (COALESCE(is_recurring, 0) = 1 AND appointment_date <= ?))
        ORDER BY appointment_date ASC, appointment_time ASC
    ''', (patient_id, today.isoformat(), range_end.isoformat(), range_end.isoformat())).fetchall()

    upcoming = []
    for appt in rows:
        is_recurring = int(appt['is_recurring'] or 0) == 1
        if is_recurring:
            occ_dates = recurring_occurrences_between(appt, today, range_end)
        else:
            occ = parse_date_safe(appt['appointment_date'])
            occ_dates = [occ] if occ else []

        for occ_date in occ_dates:
            upcoming.append({
                'id': appt['id'],
                'appointment_date': occ_date.isoformat(),
                'appointment_time': appt['appointment_time'],
                'duration_minutes': int(appt['duration_minutes'] or 60),
                'meeting_type': appt['meeting_type'] or 'in-person',
                'meeting_link': appt['meeting_link'] or '',
                'meeting_title': appt['meeting_title'] or '',
                'notes': appt['meeting_title'] or '',
                'status': appt['status'] or 'scheduled',
                'is_recurring': is_recurring
            })

    now = datetime.now()
    # Filter out past occurrences (including same-day ones whose time has passed)
    upcoming = [
        row for row in upcoming
        if datetime.fromisoformat(f"{row['appointment_date']}T{row['appointment_time'] or '00:00'}") >= now
    ]
    # Deduplicate: a scope='one' move can create a standalone appointment on a date that
    # is also generated by the recurring series; keep the first occurrence found per (date, time).
    seen_keys: set = set()
    deduped: list = []
    for row in upcoming:
        k = (row['appointment_date'], (row['appointment_time'] or '')[:5])
        if k in seen_keys:
            continue
        seen_keys.add(k)
        deduped.append(row)
    deduped.sort(key=lambda row: (row['appointment_date'], row['appointment_time']))
    return deduped[:limit]


def send_appointment_reminders(db):
    """Return appointments scheduled for today or tomorrow for admin reminder display."""
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    rows = db.execute('''
        SELECT a.id, a.appointment_date, a.appointment_time, a.duration_minutes,
               a.meeting_type, a.is_recurring,
               p.id AS patient_id, p.name AS patient_name
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE COALESCE(a.status, 'scheduled') = 'scheduled'
          AND COALESCE(p.is_deleted, 0) = 0
          AND a.appointment_date IN (?, ?)
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    ''', (today.isoformat(), tomorrow.isoformat())).fetchall()

    reminders = []
    for row in rows:
        appt_date = parse_date_safe(row['appointment_date'])
        if appt_date is None:
            continue
        days_away = (appt_date - today).days
        reminders.append({
            'appointment_id': row['id'],
            'patient_id': row['patient_id'],
            'patient_name': row['patient_name'],
            'appointment_date': row['appointment_date'],
            'appointment_time': row['appointment_time'],
            'duration_minutes': int(row['duration_minutes'] or 60),
            'meeting_type': row['meeting_type'] or 'in-person',
            'is_today': days_away == 0,
            'is_tomorrow': days_away == 1,
        })
    return reminders


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

    seen_mgmt_keys: set = set()
    for appt in appointment_rows:
        is_recurring = int(appt['is_recurring'] or 0) == 1
        if is_recurring:
            occ_dates = recurring_occurrences_between(appt, range_start, range_end)
        else:
            occ_date = parse_date_safe(appt['appointment_date'])
            occ_dates = [occ_date] if occ_date else []

        for occ_date in occ_dates:
            # Deduplicate: scope='one' moves can create a standalone appointment on a date
            # that is also generated by the recurring series, causing stale double entries.
            _mgmt_key = (int(appt['patient_id']), occ_date.isoformat(), (appt['appointment_time'] or '')[:5])
            if _mgmt_key in seen_mgmt_keys:
                continue
            seen_mgmt_keys.add(_mgmt_key)
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
                'patient_id': appt['patient_id'],
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
        if block_type != 'blocked':
            block_type = 'blocked'
        items.append({
            'kind': 'block',
            'source_id': block['id'],
            'occurrence_id': f"block-{block['id']}",
            'date': block_date.isoformat(),
            'time': start_dt.strftime('%H:%M'),
            'end_time': end_dt.strftime('%H:%M'),
            'duration_minutes': duration,
            'title': block['title'] or 'Blocked Slot',
            'type_label': 'Blocked',
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
        detail_url = url_for('group_detail', group_id=row['group_id'], show_upcoming='all') + f"#session-record-{row['id']}"
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
            'detail_url': detail_url,
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
          AND NOT EXISTS (
              SELECT 1 FROM appointments a2
              WHERE a2.patient_id = p.id
                AND a2.appointment_date >= ?
                AND COALESCE(a2.status, 'scheduled') = 'scheduled'
          )
        GROUP BY p.id, p.name, p.status
    ''', (today.isoformat(), today.isoformat())).fetchall()

    for row in follow_up_rows:
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

            # Patients should not see other patients' bookings, only their own.
            if user.role == 'patient' and appt['patient_id'] != user.patient_id:
                occupied.append((start_dt, end_dt))
                continue

            title = appt['patient_name']

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
                    'can_delete': can_delete,
                    'can_edit': can_delete
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

        # Keep group slots occupied for availability math, but hide group events from patients.
        if user.role != 'admin':
            occupied.append((session_start, session_end))
            continue

        detail_url = url_for('group_detail', group_id=group_session['group_id'], show_upcoming='all') + f"#session-record-{group_session['id']}"

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
                'detail_url': detail_url,
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
        if block_type != 'blocked':
            block_type = 'blocked'
        raw_title = block['title'] or 'Blocked Slot'
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
            'color': '#dc2626',
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

    # Available slots are restricted to admin-enabled vacancy overrides and recurring vacancy templates.
    vacancy_rows = db.execute('''
        SELECT id, slot_date, slot_time, duration_minutes
        FROM slots_override
        WHERE status = 'available' AND slot_date BETWEEN ? AND ?
        ORDER BY slot_date ASC, slot_time ASC
    ''', (week_start.isoformat(), week_end.isoformat())).fetchall()

    recurring_rows = db.execute('''
        SELECT id, weekday, slot_time, duration_minutes
        FROM vacancy_recurring
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY weekday ASC, slot_time ASC
    ''').fetchall()

    virtual_vacancies = []
    for row in vacancy_rows:
        virtual_vacancies.append({
            'source_kind': 'one-time',
            'source_id': row['id'],
            'slot_date': row['slot_date'],
            'slot_time': row['slot_time'],
            'duration_minutes': row['duration_minutes']
        })

    for row in recurring_rows:
        weekday = int(row['weekday'])
        for day in daterange(week_start, week_end):
            if custom_weekday(day) != weekday:
                continue
            virtual_vacancies.append({
                'source_kind': 'weekly',
                'source_id': row['id'],
                'slot_date': day.isoformat(),
                'slot_time': row['slot_time'],
                'duration_minutes': row['duration_minutes']
            })

    available_slots = []
    seen_slots = set()
    for row in virtual_vacancies:
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
                    'meta': {
                        'type': 'vacancy',
                        'slot_id': row['source_id'] if row['source_kind'] == 'one-time' else None,
                        'slot_kind': row['source_kind'],
                        'recurring_id': row['source_id'] if row['source_kind'] == 'weekly' else None,
                        'duration_minutes': duration,
                        'can_delete': True
                    }
                })

    # Fetch external Google Calendar events (calendar events not tracked in our DB)
    external_events = []
    if gcal and gcal.GOOGLE_LIBS_AVAILABLE and user.role == 'admin':
        try:
            all_gcal = gcal.list_events_for_week(db, week_start.isoformat(), week_end.isoformat())
            our_event_ids = {
                row['google_event_id']
                for row in db.execute(
                    'SELECT google_event_id FROM appointments WHERE google_event_id IS NOT NULL'
                ).fetchall()
            }
            our_event_ids.update(
                row['google_event_id']
                for row in db.execute(
                    'SELECT google_event_id FROM group_sessions WHERE google_event_id IS NOT NULL'
                ).fetchall()
            )
            for evt in all_gcal:
                if evt['google_event_id'] and evt['google_event_id'] not in our_event_ids:
                    external_events.append(evt)
        except Exception:
            pass

    return {
        'week_start': week_start.isoformat(),
        'week_end': week_end.isoformat(),
        'events': events,
        'external_events': external_events,
        'weekend_specials': weekend_specials,
        'available_slots': available_slots,
        'follow_up_alerts': follow_up_alerts
    }


def collect_public_available_slots(db, weeks_ahead=10):
    today = datetime.now().date()
    week_start = today - timedelta(days=custom_weekday(today))
    proxy_user = User(0, 'public', 'admin', None, 'public')
    seen = set()
    slots = []

    for offset in range(max(1, weeks_ahead)):
        target_week = week_start + timedelta(days=7 * offset)
        snapshot = build_week_calendar_snapshot(db, target_week, proxy_user)
        for slot in snapshot['available_slots']:
            slot_date = parse_date_safe(slot.get('date'))
            slot_time = parse_time_safe(slot.get('time'))
            duration = int(slot.get('duration_minutes') or 60)
            if not slot_date or not slot_time:
                continue
            if slot_date < today:
                continue
            key = (slot_date.isoformat(), slot_time.strftime('%H:%M'), duration)
            if key in seen:
                continue
            seen.add(key)
            end_dt = datetime.combine(slot_date, slot_time) + timedelta(minutes=duration)
            slots.append({
                'date': slot_date.isoformat(),
                'time': slot_time.strftime('%H:%M'),
                'duration_minutes': duration,
                'end_time': end_dt.strftime('%H:%M'),
                'label': f"{slot_date.isoformat()} {slot_time.strftime('%H:%M')} - {end_dt.strftime('%H:%M')} ({duration} min)"
            })

    slots.sort(key=lambda s: (s['date'], s['time']))
    return slots


def _nearest_calendar_anchor_date(db, user):
    """Pick the best initial date for calendar view so users land on visible events."""
    today = datetime.now().date()
    params = []
    patient_clause = ''
    if user.role == 'patient' and user.patient_id:
        patient_clause = ' AND patient_id = ?'
        params.append(user.patient_id)

    future_appt = db.execute(
        f'''
        SELECT appointment_date
        FROM appointments
                WHERE appointment_date >= ?
          {patient_clause}
        ORDER BY appointment_date ASC, appointment_time ASC
        LIMIT 1
        ''',
        [today.isoformat(), *params]
    ).fetchone()
    if future_appt and parse_date_safe(future_appt['appointment_date']):
        return parse_date_safe(future_appt['appointment_date'])

    past_appt = db.execute(
        f'''
        SELECT appointment_date
        FROM appointments
        WHERE appointment_date < ?
          {patient_clause}
        ORDER BY appointment_date DESC, appointment_time DESC
        LIMIT 1
        ''',
        [today.isoformat(), *params]
    ).fetchone()
    if past_appt and parse_date_safe(past_appt['appointment_date']):
        return parse_date_safe(past_appt['appointment_date'])

    # For admin, fall back to other calendar entities if no appointments exist.
    if user.role == 'admin':
        future_group = db.execute(
            '''
            SELECT session_date AS day
            FROM group_sessions
            WHERE session_date >= ?
            ORDER BY session_date ASC, session_time ASC
            LIMIT 1
            ''',
            (today.isoformat(),)
        ).fetchone()
        if future_group and parse_date_safe(future_group['day']):
            return parse_date_safe(future_group['day'])

        past_group = db.execute(
            '''
            SELECT session_date AS day
            FROM group_sessions
            WHERE session_date < ?
            ORDER BY session_date DESC, session_time DESC
            LIMIT 1
            ''',
            (today.isoformat(),)
        ).fetchone()
        if past_group and parse_date_safe(past_group['day']):
            return parse_date_safe(past_group['day'])

        future_block = db.execute(
            '''
            SELECT blocked_date AS day
            FROM blocked_slots
            WHERE blocked_date >= ?
            ORDER BY blocked_date ASC, blocked_time ASC
            LIMIT 1
            ''',
            (today.isoformat(),)
        ).fetchone()
        if future_block and parse_date_safe(future_block['day']):
            return parse_date_safe(future_block['day'])

        past_block = db.execute(
            '''
            SELECT blocked_date AS day
            FROM blocked_slots
            WHERE blocked_date < ?
            ORDER BY blocked_date DESC, blocked_time DESC
            LIMIT 1
            ''',
            (today.isoformat(),)
        ).fetchone()
        if past_block and parse_date_safe(past_block['day']):
            return parse_date_safe(past_block['day'])

    return today


def _week_start_for_date(day_obj):
    return day_obj - timedelta(days=custom_weekday(day_obj))


@app.route('/calendar')
@login_required
def weekly_calendar():
    db = get_db()
    if current_user.role == 'admin':
        ensure_ongoing_recurrence_from_previous_week(db)
        ensure_ongoing_patients_have_upcoming_bookings(db)
        ensure_default_recurring_vacancies(db)
    patient_options = []
    can_self_schedule = False
    if current_user.role == 'admin':
        patient_options = db.execute(
            'SELECT id, name, status, patient_type FROM patients WHERE COALESCE(is_deleted, 0) = 0 ORDER BY COALESCE(patient_type, "private") ASC, name ASC'
        ).fetchall()
    else:
        patient = db.execute('SELECT can_self_schedule FROM patients WHERE id = ?', (current_user.patient_id,)).fetchone()
        can_self_schedule = bool(patient and int(patient['can_self_schedule'] or 0) == 1)
        if not can_self_schedule:
            flash('Self-booking is currently disabled by your therapist.')
            return redirect(url_for('patient_home'))

    initial_anchor = _nearest_calendar_anchor_date(db, current_user)
    initial_week_start = _week_start_for_date(initial_anchor).isoformat()

    return render_template('calendar.html', patient_options=patient_options, can_self_schedule=can_self_schedule,
                           is_admin=(current_user.role == 'admin'),
                           initial_week_start=initial_week_start)


@app.route('/api/calendar/public-link', methods=['POST'])
@login_required
def api_create_public_booking_link():
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    token = None
    for _ in range(10):
        candidate = secrets.token_urlsafe(16)
        exists = db.execute('SELECT 1 FROM public_booking_links WHERE token = ?', (candidate,)).fetchone()
        if not exists:
            token = candidate
            break
    if not token:
        return jsonify({'status': 'error', 'message': 'Could not create booking link.'}), 500

    db.execute(
        'INSERT INTO public_booking_links (token, created_by, is_active) VALUES (?, ?, 1)',
        (token, current_user.id)
    )
    db.commit()

    public_url = build_external_public_url('open_public_booking_calendar', token=token)
    subject = quote('Self-booking calendar link')
    body = quote(f'You can book an available slot using this secure link:\n{public_url}')
    return jsonify({
        'status': 'success',
        'token': token,
        'url': public_url,
        'mailto': f'mailto:?subject={subject}&body={body}'
    })


def build_group_recurrence_dates(start_date, recurrence_interval_weeks=1, recurrence_end_date=None, recurrence_count=None):
    """Generate a bounded list of recurring group session dates."""
    interval = max(1, int(recurrence_interval_weeks or 1))
    cap = 104
    max_count = int(recurrence_count or 0)
    if max_count <= 0:
        max_count = 8
    max_count = min(max_count, cap)

    dates = []
    current = start_date
    for _ in range(cap):
        if recurrence_end_date and current > recurrence_end_date:
            break
        dates.append(current)
        if len(dates) >= max_count:
            break
        current = current + timedelta(days=interval * 7)
    return dates


def archive_patient_record(db, patient_id):
    patient = db.execute('SELECT id, name FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return None

    db.execute('''
        UPDATE patients
        SET is_deleted = 1,
            deleted_at = CURRENT_TIMESTAMP,
            status = 'archived'
        WHERE id = ?
    ''', (patient_id,))
    db.execute('UPDATE users SET is_active = 0 WHERE patient_id = ?', (patient_id,))
    return patient


def delete_patient_files(patient_id):
    upload_root = app.config.get('UPLOAD_FOLDER') or ''
    if not upload_root:
        return

    base_dir = Path(upload_root)
    treatment_dir = base_dir / 'treatments' / str(patient_id)
    if treatment_dir.exists():
        shutil.rmtree(treatment_dir, ignore_errors=True)


def permanently_delete_patient_record(db, patient_id):
    patient = db.execute('SELECT id, name FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return None

    file_rows = db.execute('SELECT filename FROM files WHERE patient_id = ?', (patient_id,)).fetchall()
    user_ids = [int(row['id']) for row in db.execute('SELECT id FROM users WHERE patient_id = ?', (patient_id,)).fetchall()]

    upload_root = Path(app.config.get('UPLOAD_FOLDER') or '.')
    for row in file_rows:
        filename = (row['filename'] or '').strip()
        if not filename:
            continue
        for candidate in (
            upload_root / filename,
            upload_root / 'treatments' / str(patient_id) / filename,
        ):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass

    delete_patient_files(patient_id)

    if user_ids:
        placeholders = ','.join(['?'] * len(user_ids))
        db.execute(f'DELETE FROM messages WHERE sender_id IN ({placeholders}) OR recipient_id IN ({placeholders})', tuple(user_ids + user_ids))

    db.execute('DELETE FROM group_session_attendance WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM group_member_history WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM group_members WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM patient_resources WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM goals WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM notes WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM receipts WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM appointments WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM files WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM audit_logs WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM users WHERE patient_id = ?', (patient_id,))
    db.execute('DELETE FROM patients WHERE id = ?', (patient_id,))
    return patient


def build_group_session_collections(group_sessions, show_all_past=False, show_all_upcoming=False):
    now = datetime.now()
    past_sessions = []
    upcoming_sessions = []

    for row in group_sessions:
        session = dict(row)
        session_date = parse_date_safe(session['session_date'])
        session_time = parse_time_safe(session['session_time'])
        if session_date and session_time:
            start_dt = datetime.combine(session_date, session_time)
            end_dt = start_dt + timedelta(minutes=int(session['duration_minutes'] or 60))
        else:
            start_dt = None
            end_dt = None
        session['starts_at'] = start_dt
        session['ends_at'] = end_dt

        if end_dt and end_dt < now:
            past_sessions.append(session)
        else:
            upcoming_sessions.append(session)

    past_sessions.sort(key=lambda item: item['starts_at'] or datetime.min, reverse=True)
    upcoming_sessions.sort(key=lambda item: item['starts_at'] or datetime.max)

    visible_past = past_sessions if show_all_past else past_sessions[:2]
    visible_upcoming = upcoming_sessions if show_all_upcoming else upcoming_sessions[:2]

    return {
        'past_sessions_all': past_sessions,
        'upcoming_sessions_all': upcoming_sessions,
        'visible_past_sessions': visible_past,
        'visible_upcoming_sessions': visible_upcoming,
        'hidden_past_count': max(0, len(past_sessions) - len(visible_past)),
        'hidden_upcoming_count': max(0, len(upcoming_sessions) - len(visible_upcoming)),
        'show_all_past': bool(show_all_past),
        'show_all_upcoming': bool(show_all_upcoming),
    }


def get_group_members_for_session(db, group_id, session_date_iso):
    """Resolve members by membership periods active on the session date."""
    rows = db.execute('''
        SELECT p.id AS patient_id,
               p.name AS patient_name,
               h.joined_at,
               h.left_at,
               COALESCE(h.role, 'member') AS role
        FROM group_member_history h
        JOIN patients p ON p.id = h.patient_id
        WHERE h.group_id = ?
          AND date(h.joined_at) <= date(?)
          AND (h.left_at IS NULL OR date(h.left_at) >= date(?))
          AND COALESCE(p.is_deleted, 0) = 0
        ORDER BY p.name ASC
    ''', (group_id, session_date_iso, session_date_iso)).fetchall()
    members = [dict(row) for row in rows]
    if members:
        return members

    fallback = db.execute('''
        SELECT p.id AS patient_id,
               p.name AS patient_name,
               gm.joined_at,
               gm.left_at,
               COALESCE(gm.role, 'member') AS role
        FROM group_members gm
        JOIN patients p ON p.id = gm.patient_id
        WHERE gm.group_id = ?
          AND date(gm.joined_at) <= date(?)
          AND (gm.left_at IS NULL OR date(gm.left_at) >= date(?))
          AND COALESCE(p.is_deleted, 0) = 0
        ORDER BY p.name ASC
    ''', (group_id, session_date_iso, session_date_iso)).fetchall()
    return [dict(row) for row in fallback]


@app.route('/calendar/public/<token>')
def open_public_booking_calendar(token):
    db = get_db()
    link_row = db.execute(
        'SELECT id FROM public_booking_links WHERE token = ? AND COALESCE(is_active, 1) = 1',
        (token,)
    ).fetchone()

    if not link_row:
        page_lang = (request.args.get('lang') or session.get('lang') or 'en').strip().lower()
        if page_lang not in {'en', 'he'}:
            page_lang = 'en'
        return render_template('open_booking_calendar.html', token=token, slots=[], link_invalid=True, page_lang=page_lang)

    slots = collect_public_available_slots(db, weeks_ahead=10)
    page_lang = (request.args.get('lang') or session.get('lang') or 'en').strip().lower()
    if page_lang not in {'en', 'he'}:
        page_lang = 'en'
    return render_template('open_booking_calendar.html', token=token, slots=slots, link_invalid=False, page_lang=page_lang)


@app.route('/api/calendar/public/<token>/book', methods=['POST'])
@csrf.exempt
def api_public_calendar_book(token):
    db = get_db()
    link_row = db.execute(
        'SELECT id FROM public_booking_links WHERE token = ? AND COALESCE(is_active, 1) = 1',
        (token,)
    ).fetchone()
    if not link_row:
        return jsonify({'status': 'error', 'message': 'Booking link is invalid or expired.'}), 404

    name = (request.form.get('name') or '').strip()
    birth_date_raw = (request.form.get('birth_date') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    email = (request.form.get('email') or '').strip()
    booking_notes = (request.form.get('notes') or '').strip()
    selected_date = (request.form.get('date') or '').strip()
    selected_time = (request.form.get('time') or '').strip()
    selected_duration_raw = (request.form.get('duration_minutes') or '').strip()

    if not name:
        return jsonify({'status': 'error', 'message': 'Name is required.'}), 400
    if not phone and not email:
        return jsonify({'status': 'error', 'message': 'Phone or email is required.'}), 400

    birth_date = None
    if birth_date_raw:
        birth_date = parse_date_safe(birth_date_raw)
        if not birth_date:
            return jsonify({'status': 'error', 'message': 'Birth date is invalid.'}), 400

    booking_date = parse_date_safe(selected_date)
    booking_time = parse_time_safe(selected_time)
    try:
        duration = int(selected_duration_raw or '60')
    except ValueError:
        duration = 60
    if duration <= 0:
        duration = 60

    if not booking_date or not booking_time:
        return jsonify({'status': 'error', 'message': 'Please choose an available slot.'}), 400

    available_keys = {
        (slot['date'], slot['time'], int(slot['duration_minutes'] or 60))
        for slot in collect_public_available_slots(db, weeks_ahead=10)
    }
    request_key = (booking_date.isoformat(), booking_time.strftime('%H:%M'), duration)
    if request_key not in available_keys:
        return jsonify({'status': 'error', 'message': 'Selected slot is no longer available.'}), 409

    slot_start = datetime.combine(booking_date, booking_time)
    slot_end = slot_start + timedelta(minutes=duration)
    conflict = has_time_conflict(db, booking_date, slot_start, slot_end)
    if conflict:
        return jsonify({'status': 'error', 'message': 'Selected slot is no longer available.'}), 409

    patient_cur = db.execute('''
        INSERT INTO patients (name, status, email, phone, birth_date, patient_type)
        VALUES (?, 'waiting', ?, ?, ?, 'private')
    ''', (name, email or None, phone or None, birth_date.isoformat() if birth_date else None))
    patient_id = patient_cur.lastrowid

    db.execute('''
        INSERT INTO appointments (
            patient_id, appointment_date, appointment_time, duration_minutes,
            meeting_type, meeting_title, status, is_recurring
        ) VALUES (?, ?, ?, ?, 'in-person', 'Self-booked via public link', 'scheduled', 0)
    ''', (patient_id, booking_date.isoformat(), booking_time.strftime('%H:%M'), duration))

    db.execute('''
        UPDATE slots_override
        SET status = 'booked', booked_by_name = ?, booked_by_phone = ?, booked_notes = ?, booked_at = ?
        WHERE slot_date = ? AND slot_time = ? AND status = 'available'
    ''', (
        name,
        phone or email,
        booking_notes or None,
        datetime.now().isoformat(),
        booking_date.isoformat(),
        booking_time.strftime('%H:%M')
    ))

    contact_text = phone or email
    notes_suffix = f' Notes: {booking_notes}.' if booking_notes else ''
    message = f'New pending patient: {name} booked {booking_date.isoformat()} at {booking_time.strftime("%H:%M")}. Contact: {contact_text}.{notes_suffix}'
    db.execute('INSERT INTO notifications (message, is_read) VALUES (?, 0)', (message,))
    db.execute(
        'INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)',
        (patient_id, 'public-self-book', message)
    )
    db.commit()

    return jsonify({
        'status': 'success',
        'message': 'Booking received. We created a pending patient record and reserved the slot.'
    })


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
        SELECT g.*, COUNT(gm.patient_id) AS member_count,
               (
                 SELECT COUNT(*)
                 FROM group_sessions gs
                 WHERE gs.group_id = g.id
               ) AS session_count,
               (
                 SELECT MIN(gs2.session_date)
                 FROM group_sessions gs2
                 WHERE gs2.group_id = g.id AND COALESCE(gs2.status, 'scheduled') = 'scheduled'
               ) AS next_session_date
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id AND gm.left_at IS NULL
        GROUP BY g.id
        ORDER BY g.created_at DESC, g.name ASC
    ''').fetchall()

    return render_template('groups_overview.html', groups=groups)



def _get_group_member_history(db, group_id):
    member_history_rows = db.execute('''
         SELECT h.id,
             h.group_id,
               h.patient_id,
               p.name AS patient_name,
               h.joined_at,
               h.left_at,
               COALESCE(h.role, 'member') AS role
        FROM group_member_history h
        JOIN patients p ON p.id = h.patient_id
                WHERE h.group_id = ?
                    AND COALESCE(p.is_deleted, 0) = 0
        ORDER BY h.group_id ASC, h.joined_at DESC
        ''', (group_id,)).fetchall()

    member_history_rows = [dict(row) for row in member_history_rows]
    now_date = datetime.now().date()
    for row in member_history_rows:
        joined_date = parse_date_safe((row.get('joined_at') or '')[:10])
        left_date = parse_date_safe((row.get('left_at') or '')[:10]) if row.get('left_at') else None
        if joined_date:
            end_date = left_date or now_date
            row['membership_days'] = max(0, (end_date - joined_date).days)
        else:
            row['membership_days'] = None
    return member_history_rows


def _get_group_attendance_data(db, group_sessions):
    session_member_map = {}
    attendance_by_session = {}
    session_ids = [int(row['id']) for row in group_sessions]

    for gs_row in group_sessions:
        session_date_iso = gs_row['session_date']

        members = []
        for row in history_list:
            joined_date = row['joined_at'][:10] if row['joined_at'] else ''
            left_date = row['left_at'][:10] if row['left_at'] else None

            if joined_date <= session_date_iso and (left_date is None or left_date >= session_date_iso):
                members.append(row.copy())

        if not members:
            for row in fallback_list:
                joined_date = row['joined_at'][:10] if row['joined_at'] else ''
                left_date = row['left_at'][:10] if row['left_at'] else None

                if joined_date <= session_date_iso and (left_date is None or left_date >= session_date_iso):
                    members.append(row.copy())

        session_member_map[int(gs_row['id'])] = members

    if session_ids:
        marks = db.execute(f'''
            SELECT session_id, patient_id, attendance_status, absence_reason, notified_on_time, attendance_note
            FROM group_session_attendance
            WHERE session_id IN ({','.join(['?'] * len(session_ids))})
        ''', session_ids).fetchall()
        for row in marks:
            session_key = int(row['session_id'])
            attendance_by_session.setdefault(session_key, {})[int(row['patient_id'])] = {
                'attendance_status': row['attendance_status'] or 'pending',
                'absence_reason': row['absence_reason'] or '',
                'notified_on_time': int(row['notified_on_time'] or 0),
                'attendance_note': row['attendance_note'] or ''
            }

    return session_member_map, attendance_by_session


def _get_patient_arrived_counts(db):
    arrived_rows = db.execute('''
        SELECT patient_id, COUNT(*) AS arrived_count
        FROM group_session_attendance
        WHERE attendance_status = 'present'
        GROUP BY patient_id
    ''').fetchall()
    return {int(row['patient_id']): int(row['arrived_count'] or 0) for row in arrived_rows}


def _get_available_group_patients(db):
    return db.execute('''
        SELECT id, name
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
          AND COALESCE(patient_type, 'private') = 'group'
        ORDER BY name ASC
    ''').fetchall()


def build_group_detail_payload(db, group_id, show_all_past=False, show_all_upcoming=False):
    group = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        return None

    group_members = db.execute('''
        SELECT gm.group_id, p.id AS patient_id, p.name AS patient_name, gm.joined_at, gm.left_at
        FROM group_members gm
        JOIN patients p ON p.id = gm.patient_id
                WHERE gm.group_id = ?
                    AND gm.left_at IS NULL
                    AND COALESCE(p.is_deleted, 0) = 0
        ORDER BY p.name ASC
        ''', (group_id,)).fetchall()

    group_sessions = db.execute('''
        SELECT gs.*, g.name AS group_name,
               ss.recurrence_interval_weeks,
               ss.recurrence_end_date,
               ss.recurrence_count
        FROM group_sessions gs
        JOIN groups g ON g.id = gs.group_id
        LEFT JOIN group_session_series ss ON ss.id = gs.series_id
        WHERE gs.group_id = ?
        ORDER BY gs.session_date ASC, gs.session_time ASC
    ''', (group_id,)).fetchall()

    member_history_rows = _get_group_member_history(db, group_id)
    session_member_map, attendance_by_session = _get_group_attendance_data(db, group_sessions)
    arrived_count_map = _get_patient_arrived_counts(db)
    patients = _get_available_group_patients(db)

    session_collections = build_group_session_collections(
        group_sessions,
        show_all_past=show_all_past,
        show_all_upcoming=show_all_upcoming
    )

    group_supervisions = db.execute(
        'SELECT * FROM supervisions WHERE group_id = ? ORDER BY supervision_date DESC, created_at DESC',
        (group_id,)
    ).fetchall()

    return {
        'group': group,
        'group_members': group_members,
        'group_sessions': group_sessions,
        'patients': patients,
        'member_history_rows': member_history_rows,
        'session_member_map': session_member_map,
        'attendance_by_session': attendance_by_session,
        'arrived_count_map': arrived_count_map,
        'group_supervisions': group_supervisions,
        **session_collections
    }


@app.route('/groups/<int:group_id>', methods=['GET'])
@login_required
def group_detail(group_id):
    if current_user.role != 'admin':
        return redirect(url_for('patient_home'))

    db = get_db()
    show_all_past = (request.args.get('show_past') or '').strip().lower() == 'all'
    show_all_upcoming = (request.args.get('show_upcoming') or '').strip().lower() == 'all'
    payload = build_group_detail_payload(
        db,
        group_id,
        show_all_past=show_all_past,
        show_all_upcoming=show_all_upcoming
    )
    if payload is None:
        flash('Group not found.')
        return redirect(url_for('groups_dashboard'))
    return render_template('groups.html', **payload)


@app.route('/groups/<int:group_id>/delete', methods=['POST'])
@login_required
def delete_group(group_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    delete_mode = (request.form.get('delete_mode') or 'archive').strip().lower()
    return_to = (request.form.get('return_to') or 'dashboard').strip().lower()

    db = get_db()
    group = db.execute('SELECT id, name FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        flash('Group not found.')
        return redirect(url_for('groups_dashboard'))

    if delete_mode == 'delete':
        session_ids = [int(row['id']) for row in db.execute('SELECT id FROM group_sessions WHERE group_id = ?', (group_id,)).fetchall()]
        if session_ids:
            placeholders = ','.join(['?'] * len(session_ids))
            db.execute(f'DELETE FROM group_session_attendance WHERE session_id IN ({placeholders})', session_ids)
        db.execute('DELETE FROM group_sessions WHERE group_id = ?', (group_id,))
        db.execute('DELETE FROM group_session_series WHERE group_id = ?', (group_id,))
        db.execute('DELETE FROM group_member_history WHERE group_id = ?', (group_id,))
        db.execute('DELETE FROM group_members WHERE group_id = ?', (group_id,))
        db.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        db.commit()
        flash('Group and all related data deleted.')
        return redirect(url_for('groups_dashboard'))

    db.execute('UPDATE groups SET is_active = 0 WHERE id = ?', (group_id,))
    db.commit()
    flash('Group moved to history.')
    if return_to == 'detail':
        return redirect(url_for('groups_dashboard'))
    return redirect(url_for('groups_dashboard'))


@app.route('/groups/<int:group_id>/update', methods=['POST'])
@login_required
def update_group_info(group_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    name = (request.form.get('name') or '').strip()
    group_type = (request.form.get('group_type') or 'support').strip() or 'support'
    description = (request.form.get('description') or '').strip()
    is_active = 1 if request.form.get('is_active') in ('1', 'true', 'on') else 0
    return_to = (request.form.get('return_to') or 'detail').strip().lower()

    if not name:
        flash('Group name is required.')
        if return_to == 'dashboard':
            return redirect(url_for('groups_dashboard'))
        return redirect(url_for('group_detail', group_id=group_id))

    db = get_db()
    db.execute('''
        UPDATE groups
        SET name = ?, group_type = ?, description = ?, is_active = ?
        WHERE id = ?
    ''', (name, group_type, description or None, is_active, group_id))
    db.commit()
    flash('Group information updated.')
    if return_to == 'dashboard':
        return redirect(url_for('groups_dashboard'))
    return redirect(url_for('group_detail', group_id=group_id))


# ── Group supervision ─────────────────────────────────────────────────────────

@app.route('/groups/<int:group_id>/supervision', methods=['POST'])
@login_required
def add_group_supervision(group_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    if not db.execute('SELECT id FROM groups WHERE id = ?', (group_id,)).fetchone():
        return 'Group not found', 404
    sup_date = (request.form.get('supervision_date') or '').strip()
    supervisor = (request.form.get('supervisor_name') or '').strip()
    content = (request.form.get('content') or '').strip()
    if not sup_date or not content:
        flash('Date and content are required.')
        return redirect(url_for('group_detail', group_id=group_id))
    db.execute(
        'INSERT INTO supervisions (group_id, supervision_date, supervisor_name, content) VALUES (?,?,?,?)',
        (group_id, sup_date, supervisor or None, content)
    )
    db.commit()
    flash('Supervision record added.')
    return redirect(url_for('group_detail', group_id=group_id))


@app.route('/groups/<int:group_id>/supervision/<int:sup_id>/delete', methods=['POST'])
@login_required
def delete_group_supervision(group_id, sup_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    db.execute('DELETE FROM supervisions WHERE id = ? AND group_id = ?', (sup_id, group_id))
    db.commit()
    flash('Supervision record deleted.')
    return redirect(url_for('group_detail', group_id=group_id))


@app.route('/groups/<int:group_id>/members', methods=['POST'])
@login_required
def add_group_member(group_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    patient_id_raw = (request.form.get('patient_id') or '').strip()
    if not patient_id_raw.isdigit():
        flash('Valid patient is required.')
        return redirect(url_for('group_detail', group_id=group_id))

    db = get_db()
    patient_id = int(patient_id_raw)
    patient_row = db.execute('SELECT id, patient_type FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0', (patient_id,)).fetchone()
    if not patient_row:
        flash('Patient not found.')
        return redirect(url_for('group_detail', group_id=group_id))
    if (patient_row['patient_type'] or 'private') != 'group':
        flash('Only group-type patients can be added to groups.')
        return redirect(url_for('group_detail', group_id=group_id))

    existing_active = db.execute('''
        SELECT 1
        FROM group_members
        WHERE group_id = ? AND patient_id = ? AND left_at IS NULL
        LIMIT 1
    ''', (group_id, patient_id)).fetchone()
    if existing_active:
        flash('Patient is already an active member in this group.')
        return redirect(url_for('group_detail', group_id=group_id))

    db.execute('''
        INSERT INTO group_members (group_id, patient_id, joined_at, left_at, role)
        VALUES (?, ?, CURRENT_TIMESTAMP, NULL, 'member')
        ON CONFLICT(group_id, patient_id)
        DO UPDATE SET joined_at = CURRENT_TIMESTAMP, left_at = NULL, role = 'member'
    ''', (group_id, patient_id))

    existing_open_history = db.execute('''
        SELECT id
        FROM group_member_history
        WHERE group_id = ? AND patient_id = ? AND left_at IS NULL
        ORDER BY joined_at DESC
        LIMIT 1
    ''', (group_id, patient_id)).fetchone()
    if not existing_open_history:
        db.execute('''
            INSERT INTO group_member_history (group_id, patient_id, joined_at, role)
            VALUES (?, ?, CURRENT_TIMESTAMP, 'member')
        ''', (group_id, patient_id))

    db.commit()
    flash('Patient added to group.')
    return redirect(url_for('group_detail', group_id=group_id))


@app.route('/groups/<int:group_id>/members/<int:patient_id>/remove', methods=['POST'])
@login_required
def remove_group_member(group_id, patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    removal_mode = (request.form.get('removal_mode') or 'keep').strip().lower()

    db = get_db()
    group = db.execute('SELECT id, name FROM groups WHERE id = ?', (group_id,)).fetchone()
    patient = db.execute('SELECT id, name FROM patients WHERE id = ?', (patient_id,)).fetchone()
    active_membership = db.execute('''
        SELECT 1
        FROM group_members
        WHERE group_id = ? AND patient_id = ? AND left_at IS NULL
    ''', (group_id, patient_id)).fetchone()

    if not group or not patient:
        flash('Group member not found.')
        return redirect(url_for('group_detail', group_id=group_id))
    if not active_membership:
        flash('Patient is not an active member in this group.')
        return redirect(url_for('group_detail', group_id=group_id))

    db.execute('''
        UPDATE group_members
        SET left_at = CURRENT_TIMESTAMP
        WHERE group_id = ? AND patient_id = ? AND left_at IS NULL
    ''', (group_id, patient_id))

    open_history = db.execute('''
        SELECT id
        FROM group_member_history
        WHERE group_id = ? AND patient_id = ? AND left_at IS NULL
        ORDER BY joined_at DESC
        LIMIT 1
    ''', (group_id, patient_id)).fetchone()
    if open_history:
        db.execute('UPDATE group_member_history SET left_at = CURRENT_TIMESTAMP WHERE id = ?', (open_history['id'],))

    if removal_mode == 'archive':
        archive_patient_record(db, patient_id)
        message = 'Patient removed from group and moved to archived records.'
    elif removal_mode == 'delete':
        permanently_delete_patient_record(db, patient_id)
        message = 'Patient removed from group and deleted with all related data.'
    else:
        message = 'Patient removed from group.'

    db.commit()
    flash(message)
    return redirect(url_for('group_detail', group_id=group_id))


def sync_group_member_current_record(db, group_id, patient_id):
    """Keep group_members aligned with the latest history state."""
    open_row = db.execute('''
        SELECT joined_at
        FROM group_member_history
        WHERE group_id = ? AND patient_id = ? AND left_at IS NULL
        ORDER BY joined_at DESC
        LIMIT 1
    ''', (group_id, patient_id)).fetchone()

    if open_row:
        db.execute('''
            INSERT INTO group_members (group_id, patient_id, joined_at, left_at, role)
            VALUES (?, ?, ?, NULL, 'member')
            ON CONFLICT(group_id, patient_id)
            DO UPDATE SET joined_at = excluded.joined_at, left_at = NULL, role = 'member'
        ''', (group_id, patient_id, open_row['joined_at']))
        return

    latest_row = db.execute('''
        SELECT joined_at, left_at
        FROM group_member_history
        WHERE group_id = ? AND patient_id = ?
        ORDER BY joined_at DESC
        LIMIT 1
    ''', (group_id, patient_id)).fetchone()
    if latest_row:
        db.execute('''
            INSERT INTO group_members (group_id, patient_id, joined_at, left_at, role)
            VALUES (?, ?, ?, ?, 'member')
            ON CONFLICT(group_id, patient_id)
            DO UPDATE SET joined_at = excluded.joined_at, left_at = excluded.left_at, role = 'member'
        ''', (group_id, patient_id, latest_row['joined_at'], latest_row['left_at']))


@app.route('/groups/history/<int:history_id>/dates', methods=['POST'])
@login_required
def update_group_member_history_dates(history_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    joined_date_raw = (request.form.get('joined_date') or '').strip()
    left_date_raw = (request.form.get('left_date') or '').strip()
    return_patient_id_raw = (request.form.get('return_patient_id') or '').strip()
    return_group_id_raw = (request.form.get('return_group_id') or '').strip()

    def redirect_target():
        if return_patient_id_raw.isdigit():
            return redirect_to_patient_tab(int(return_patient_id_raw), 'info')
        if return_group_id_raw.isdigit():
            return redirect(url_for('group_detail', group_id=int(return_group_id_raw)))
        return redirect(url_for('groups_dashboard'))

    joined_date = parse_date_safe(joined_date_raw)
    left_date = parse_date_safe(left_date_raw) if left_date_raw else None
    if not joined_date:
        flash('Joined date is required and must be valid.')
        return redirect_target()
    if left_date and left_date < joined_date:
        flash('Left date cannot be before joined date.')
        return redirect_target()

    db = get_db()
    history = db.execute('''
        SELECT id, group_id, patient_id
        FROM group_member_history
        WHERE id = ?
    ''', (history_id,)).fetchone()
    if not history:
        flash('Membership history row not found.')
        return redirect_target()

    joined_ts = f"{joined_date.isoformat()} 00:00:00"
    left_ts = f"{left_date.isoformat()} 23:59:59" if left_date else None
    db.execute('''
        UPDATE group_member_history
        SET joined_at = ?, left_at = ?
        WHERE id = ?
    ''', (joined_ts, left_ts, history_id))

    sync_group_member_current_record(db, int(history['group_id']), int(history['patient_id']))
    db.commit()
    flash('Membership dates updated.')
    return redirect_target()


def _parse_group_session_form(form):
    return {
        'session_date': (form.get('session_date') or '').strip(),
        'session_time': (form.get('session_time') or '').strip(),
        'end_time_raw': (form.get('end_time') or '').strip(),
        'title': (form.get('title') or '').strip(),
        'facilitator': (form.get('facilitator') or '').strip(),
        'meeting_type': (form.get('meeting_type') or 'in-person').strip(),
        'meeting_link': (form.get('meeting_link') or '').strip(),
        'recurrence_mode': (form.get('recurrence_mode') or 'one-time').strip().lower(),
        'recurrence_interval_raw': (form.get('recurrence_interval_weeks') or '1').strip(),
        'recurrence_end_mode': (form.get('recurrence_end_mode') or 'count').strip().lower(),
        'recurrence_end_raw': (form.get('recurrence_end_date') or '').strip(),
        'recurrence_count_raw': (form.get('recurrence_count') or '').strip()
    }


def _calculate_group_session_duration(parsed_time, parsed_end):
    duration = 60
    if parsed_end:
        start_minutes = parsed_time.hour * 60 + parsed_time.minute
        end_minutes = parsed_end.hour * 60 + parsed_end.minute
        if end_minutes > start_minutes:
            duration = end_minutes - start_minutes
    return duration


def _resolve_group_recurrence_params(recurrence_mode, recurrence_interval_raw, recurrence_end_mode, recurrence_end_raw, recurrence_count_raw):
    try:
        recurrence_interval_weeks = max(1, int(recurrence_interval_raw or '1'))
    except ValueError:
        recurrence_interval_weeks = 1

    recurrence_end_date = parse_date_safe(recurrence_end_raw) if recurrence_end_raw else None
    recurrence_count = None
    if recurrence_count_raw:
        try:
            recurrence_count = max(1, min(104, int(recurrence_count_raw)))
        except ValueError:
            recurrence_count = None

    error_msg = None
    if recurrence_mode == 'weekly':
        if recurrence_end_mode == 'date':
            recurrence_count = None
            if not recurrence_end_date:
                error_msg = 'Please choose an end date for the recurring meetings.'
        else:
            recurrence_end_date = None
            if recurrence_count is None:
                error_msg = 'Please choose how many meetings to create.'

    return recurrence_interval_weeks, recurrence_end_date, recurrence_count, error_msg


def _insert_group_sessions(db, group_id, parsed_date, parsed_time, duration, recurrence_dates, recurrence_mode, recurrence_interval_weeks, recurrence_end_date, recurrence_count, title, facilitator, meeting_type, meeting_link):
    series_id = None
    if recurrence_mode == 'weekly' and len(recurrence_dates) > 1:
        cur = db.execute('''
            INSERT INTO group_session_series (
                group_id, start_date, start_time, duration_minutes,
                recurrence_interval_weeks, recurrence_end_date, recurrence_count,
                title, facilitator, meeting_type, meeting_link, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (
            group_id,
            parsed_date.isoformat(),
            parsed_time.strftime('%H:%M'),
            duration,
            recurrence_interval_weeks,
            recurrence_end_date.isoformat() if recurrence_end_date else None,
            recurrence_count,
            title or None,
            facilitator or None,
            meeting_type or 'in-person',
            meeting_link or None
        ))
        series_id = cur.lastrowid

    last_session_id = None
    for idx, date_item in enumerate(recurrence_dates, start=1):
        cur = db.execute('''
            INSERT INTO group_sessions
                (group_id, session_date, session_time, duration_minutes, title, facilitator, meeting_type, meeting_link, series_id, occurrence_index, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled')
        ''', (
            group_id,
            date_item.isoformat(),
            parsed_time.strftime('%H:%M'),
            duration,
            title or None,
            facilitator or None,
            meeting_type or 'in-person',
            meeting_link or None,
            series_id,
            idx if series_id else None
        ))
        last_session_id = cur.lastrowid

    return series_id, last_session_id


@app.route('/groups/<int:group_id>/sessions', methods=['POST'])
@login_required
def add_group_session(group_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    data = _parse_group_session_form(request.form)

    parsed_date = parse_date_safe(data['session_date'])
    parsed_time = parse_time_safe(data['session_time'])
    parsed_end = parse_time_safe(data['end_time_raw'])

    if not parsed_date or not parsed_time:
        flash('Valid session date and start time are required.')
        return redirect(url_for('group_detail', group_id=group_id))

    duration = _calculate_group_session_duration(parsed_time, parsed_end)
    db = get_db()

    recurrence_interval_weeks, recurrence_end_date, recurrence_count, error_msg = _resolve_group_recurrence_params(
        data['recurrence_mode'], data['recurrence_interval_raw'],
        data['recurrence_end_mode'], data['recurrence_end_raw'], data['recurrence_count_raw']
    )

    if error_msg:
        flash(error_msg)
        return redirect(url_for('group_detail', group_id=group_id))

    recurrence_dates = [parsed_date]
    if data['recurrence_mode'] == 'weekly':
        recurrence_dates = build_group_recurrence_dates(
            parsed_date,
            recurrence_interval_weeks=recurrence_interval_weeks,
            recurrence_end_date=recurrence_end_date,
            recurrence_count=recurrence_count
        )

    for date_item in recurrence_dates:
        start_at = datetime.combine(date_item, parsed_time)
        end_at = start_at + timedelta(minutes=duration)
        conflict_message = has_time_conflict(db, date_item, start_at, end_at)
        if conflict_message:
            flash(f'{conflict_message} ({date_item.isoformat()})')
            return redirect(url_for('group_detail', group_id=group_id))

    series_id, last_session_id = _insert_group_sessions(
        db, group_id, parsed_date, parsed_time, duration, recurrence_dates,
        data['recurrence_mode'], recurrence_interval_weeks, recurrence_end_date, recurrence_count,
        data['title'], data['facilitator'], data['meeting_type'], data['meeting_link']
    )

    db.commit()

    if series_id:
        flash(f"Group recurrence added ({len(recurrence_dates)} sessions).")
    else:
        flash('Group session added.')

    destination = url_for('group_detail', group_id=group_id, show_upcoming='all')
    if last_session_id:
        destination = f'{destination}#session-record-{last_session_id}'
    return redirect(destination)


@app.route('/groups/sessions/<int:session_id>/record', methods=['POST'])
@login_required
def record_group_session(session_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    session_row = db.execute('SELECT * FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
    if not session_row:
        flash('Group session not found.')
        return redirect(url_for('groups_dashboard'))

    session_summary = (request.form.get('session_summary') or '').strip()
    session_status = (request.form.get('session_status') or 'completed').strip().lower()
    if session_status not in ('scheduled', 'completed', 'cancelled'):
        session_status = 'completed'

    db.execute('''
        UPDATE group_sessions
        SET session_summary = ?, status = ?
        WHERE id = ?
    ''', (session_summary or None, session_status, session_id))

    members = get_group_members_for_session(db, int(session_row['group_id']), session_row['session_date'])

    def upsert_missed_group_note(pid, missed_reason_text):
        marker = f"[Group Session #{session_id}]"
        note_content = f"{marker} Missed group session on {session_row['session_date']} ({session_row['session_time']})."
        if missed_reason_text:
            note_content = f"{note_content} Reason: {missed_reason_text}"
        existing_note = db.execute('''
            SELECT id
            FROM notes
            WHERE patient_id = ?
              AND content LIKE ?
            ORDER BY id DESC
            LIMIT 1
        ''', (pid, f'{marker}%')).fetchone()
        if existing_note:
            db.execute('''
                UPDATE notes
                SET note_date = ?, content = ?, is_missed_meeting = 1, missed_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (session_row['session_date'], note_content, missed_reason_text or None, existing_note['id']))
        else:
            db.execute('''
                INSERT INTO notes (patient_id, note_date, content, is_missed_meeting, missed_reason)
                VALUES (?, ?, ?, 1, ?)
            ''', (pid, session_row['session_date'], note_content, missed_reason_text or None))

    for member in members:
        pid = int(member['patient_id'])
        status_value = (request.form.get(f'attendance_{pid}') or 'pending').strip().lower()
        if status_value not in ('present', 'missed', 'pending'):
            status_value = 'pending'
        absence_reason = (request.form.get(f'absence_reason_{pid}') or '').strip()
        notified_on_time = 1 if request.form.get(f'notified_on_time_{pid}') in ('1', 'true', 'on') else 0
        attendance_note = (request.form.get(f'attendance_note_{pid}') or '').strip()
        if status_value != 'missed':
            absence_reason = ''
            notified_on_time = 0

        db.execute('''
            INSERT INTO group_session_attendance (session_id, patient_id, attendance_status, absence_reason, notified_on_time, attendance_note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id, patient_id)
            DO UPDATE SET attendance_status = excluded.attendance_status,
                          absence_reason = excluded.absence_reason,
                          notified_on_time = excluded.notified_on_time,
                          attendance_note = excluded.attendance_note,
                          updated_at = CURRENT_TIMESTAMP
        ''', (session_id, pid, status_value, absence_reason or None, notified_on_time, attendance_note or None))

        if status_value == 'missed':
            upsert_missed_group_note(pid, absence_reason)

    db.commit()
    flash('Session record saved.')
    destination_args = {'group_id': int(session_row['group_id'])}
    session_date = parse_date_safe(session_row['session_date'])
    session_time = parse_time_safe(session_row['session_time'])
    if session_date and session_time:
        session_end = datetime.combine(session_date, session_time) + timedelta(minutes=int(session_row['duration_minutes'] or 60))
        if session_end < datetime.now():
            destination_args['show_past'] = 'all'
        else:
            destination_args['show_upcoming'] = 'all'
    destination = url_for('group_detail', **destination_args)
    return redirect(f'{destination}#session-record-{session_id}')


@app.route('/patient/<int:patient_id>/group_attendance/<int:session_id>/update', methods=['POST'])
@login_required
def update_patient_group_attendance(patient_id, session_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    session_row = db.execute('SELECT * FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
    patient_row = db.execute('SELECT id FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0', (patient_id,)).fetchone()
    if not session_row or not patient_row:
        flash('Attendance row could not be updated.')
        return redirect_to_patient_tab(patient_id, 'info')

    status_value = (request.form.get('attendance_status') or 'pending').strip().lower()
    if status_value not in ('present', 'missed', 'pending'):
        status_value = 'pending'
    absence_reason = (request.form.get('absence_reason') or '').strip()
    notified_on_time = 1 if request.form.get('notified_on_time') in ('1', 'true', 'on') else 0
    attendance_note = (request.form.get('attendance_note') or '').strip()
    session_summary = (request.form.get('session_summary') or '').strip()

    if status_value != 'missed':
        absence_reason = ''
        notified_on_time = 0

    db.execute('''
        UPDATE group_sessions
        SET session_summary = ?
        WHERE id = ?
    ''', (session_summary or None, session_id))

    db.execute('''
        INSERT INTO group_session_attendance (session_id, patient_id, attendance_status, absence_reason, notified_on_time, attendance_note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(session_id, patient_id)
        DO UPDATE SET attendance_status = excluded.attendance_status,
                      absence_reason = excluded.absence_reason,
                      notified_on_time = excluded.notified_on_time,
                      attendance_note = excluded.attendance_note,
                      updated_at = CURRENT_TIMESTAMP
    ''', (session_id, patient_id, status_value, absence_reason or None, notified_on_time, attendance_note or None))

    if status_value == 'missed':
        marker = f"[Group Session #{session_id}]"
        note_content = f"{marker} Missed group session on {session_row['session_date']} ({session_row['session_time']})."
        if absence_reason:
            note_content = f"{note_content} Reason: {absence_reason}"
        existing_note = db.execute('''
            SELECT id
            FROM notes
            WHERE patient_id = ?
              AND content LIKE ?
            ORDER BY id DESC
            LIMIT 1
        ''', (patient_id, f'{marker}%')).fetchone()
        if existing_note:
            db.execute('''
                UPDATE notes
                SET note_date = ?, content = ?, is_missed_meeting = 1, missed_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (session_row['session_date'], note_content, absence_reason or None, existing_note['id']))
        else:
            db.execute('''
                INSERT INTO notes (patient_id, note_date, content, is_missed_meeting, missed_reason)
                VALUES (?, ?, ?, 1, ?)
            ''', (patient_id, session_row['session_date'], note_content, absence_reason or None))

    db.commit()
    flash('Patient group attendance updated.')
    return redirect_to_patient_tab(patient_id, 'info')


@app.route('/api/calendar/snapshot')
@login_required
def api_calendar_snapshot():
    start_raw = request.args.get('week_start', '').strip()
    anchor = parse_date_safe(start_raw) or datetime.now().date()
    week_start = anchor - timedelta(days=custom_weekday(anchor))
    db = get_db()
    if current_user.role == 'admin':
        ensure_ongoing_recurrence_from_previous_week(db, anchor)
        ensure_ongoing_patients_have_upcoming_bookings(db, anchor)
        ensure_default_recurring_vacancies(db)
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

    if dates_to_create:
        now_iso = datetime.now().isoformat()

        blocked_slots_data = [
            (block_day.isoformat(), parsed_start.strftime('%H:%M'), duration_value, title or None, is_private, block_type, current_user.id)
            for block_day in dates_to_create
        ]

        slots_override_data = [
            (title or 'Blocked Slot', now_iso, block_day.isoformat(), parsed_start.strftime('%H:%M'))
            for block_day in dates_to_create
        ]

        db.executemany('''
            INSERT INTO blocked_slots
            (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', blocked_slots_data)

        db.executemany('''
            UPDATE slots_override
            SET status = 'booked', booked_by_name = ?, booked_at = ?
            WHERE slot_date = ? AND slot_time = ? AND status = 'available'
        ''', slots_override_data)

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
    recurrence_pattern = (request.form.get('recurrence_pattern') or 'weekly').strip().lower()
    if recurrence_pattern not in ('one-time', 'weekly'):
        recurrence_pattern = 'one-time'

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

    if recurrence_pattern == 'weekly':
        weekday = custom_weekday(date_obj)
        db.execute('''
            DELETE FROM vacancy_recurring
            WHERE weekday = ? AND slot_time = ?
        ''', (weekday, start_time.strftime('%H:%M')))
        insert_cur = db.execute('''
            INSERT INTO vacancy_recurring (weekday, slot_time, duration_minutes, is_active)
            VALUES (?, ?, ?, 1)
        ''', (weekday, start_time.strftime('%H:%M'), duration))
        db.commit()
        return jsonify({
            'status': 'success',
            'recurrence_pattern': 'weekly',
            'recurring_id': insert_cur.lastrowid
        })

    db.execute('''
        DELETE FROM slots_override
        WHERE slot_date = ? AND slot_time = ? AND status = 'available'
    ''', (slot_date, start_time.strftime('%H:%M')))
    insert_cur = db.execute('''
        INSERT INTO slots_override (slot_date, slot_time, status, duration_minutes)
        VALUES (?, ?, 'available', ?)
    ''', (slot_date, start_time.strftime('%H:%M'), duration))
    db.commit()
    return jsonify({
        'status': 'success',
        'recurrence_pattern': 'one-time',
        'override_id': insert_cur.lastrowid
    })


@app.route('/calendar/open/<token>')
def open_booking_page(token):
    """Public booking page – no login required. Patients use this to book a shared vacancy slot."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM slots_override WHERE share_token = ? AND status = 'available'",
        (token,)
    ).fetchone()

    if not row:
        booked_row = db.execute(
            "SELECT * FROM slots_override WHERE share_token = ?",
            (token,)
        ).fetchone()
        if booked_row:
            return render_template('open_booking.html', slot=None, already_booked=True, token=token)
        return render_template('open_booking.html', slot=None, already_booked=False, token=token, not_found=True)

    date_obj = parse_date_safe(row['slot_date'])
    t_obj = parse_time_safe(row['slot_time'])
    duration = int(row['duration_minutes'] or 60)
    end_dt = datetime.combine(date_obj, t_obj) + timedelta(minutes=duration) if date_obj and t_obj else None
    slot = {
        'id': row['id'],
        'date': date_obj.strftime('%A, %B %d, %Y') if date_obj else row['slot_date'],
        'date_iso': row['slot_date'],
        'time': t_obj.strftime('%H:%M') if t_obj else row['slot_time'],
        'end_time': end_dt.strftime('%H:%M') if end_dt else '',
        'duration_minutes': duration,
    }
    return render_template('open_booking.html', slot=slot, already_booked=False, not_found=False, token=token)


@app.route('/api/calendar/open/<token>/book', methods=['POST'])
@csrf.exempt
def api_open_slot_book(token):
    """Public endpoint – books a shared vacancy slot. No authentication required."""
    booker_name = (request.form.get('name') or '').strip()
    booker_phone = (request.form.get('phone') or '').strip()
    booker_notes = (request.form.get('notes') or '').strip()

    if not booker_name:
        return jsonify({'status': 'error', 'message': 'Name is required.'}), 400

    db = get_db()
    row = db.execute(
        "SELECT * FROM slots_override WHERE share_token = ? AND status = 'available'",
        (token,)
    ).fetchone()

    if not row:
        return jsonify({'status': 'error', 'message': 'This slot is no longer available.'}), 409

    date_obj = parse_date_safe(row['slot_date'])
    t_obj = parse_time_safe(row['slot_time'])
    if not date_obj or not t_obj:
        return jsonify({'status': 'error', 'message': 'Invalid slot data.'}), 500

    duration = int(row['duration_minutes'] or 60)
    slot_start = datetime.combine(date_obj, t_obj)
    slot_end = slot_start + timedelta(minutes=duration)

    conflict = has_time_conflict(db, date_obj, slot_start, slot_end)
    if conflict:
        return jsonify({'status': 'error', 'message': 'This slot is no longer available – another booking was just made.'}), 409

    full_title = booker_name
    if booker_notes:
        full_title = f"{booker_name} – {booker_notes}"

    db.execute('''
        INSERT INTO blocked_slots (blocked_date, blocked_time, duration_minutes, title, is_private, block_type)
        VALUES (?, ?, ?, ?, 0, 'blocked')
    ''', (row['slot_date'], row['slot_time'], duration, full_title))

    db.execute('''
        UPDATE slots_override
        SET status = 'booked', booked_by_name = ?, booked_by_phone = ?, booked_at = ?
        WHERE id = ?
    ''', (booker_name, booker_phone, datetime.now().isoformat(), row['id']))
    db.commit()
    return jsonify({'status': 'success', 'message': f'Your booking for {row["slot_date"]} at {row["slot_time"]} has been confirmed!'})


@app.route('/api/calendar/vacancy/<int:override_id>/occupy', methods=['POST'])
@login_required
def api_calendar_vacancy_occupy(override_id):
    """Admin manually occupies a vacant slot – assigns a patient or enters a name."""
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    row = db.execute(
        "SELECT * FROM slots_override WHERE id = ? AND status = 'available'",
        (override_id,)
    ).fetchone()

    if not row:
        return jsonify({'status': 'error', 'message': 'Slot not found or already occupied.'}), 404

    patient_id_raw = (request.form.get('patient_id') or '').strip()
    occupant_name = (request.form.get('occupant_name') or '').strip()

    if not patient_id_raw and not occupant_name:
        return jsonify({'status': 'error', 'message': 'Provide a patient or a name.'}), 400

    date_obj = parse_date_safe(row['slot_date'])
    t_obj = parse_time_safe(row['slot_time'])
    if not date_obj or not t_obj:
        return jsonify({'status': 'error', 'message': 'Invalid slot data.'}), 500

    duration = int(row['duration_minutes'] or 60)
    slot_start = datetime.combine(date_obj, t_obj)
    slot_end = slot_start + timedelta(minutes=duration)

    conflict = has_time_conflict(db, date_obj, slot_start, slot_end)
    if conflict:
        return jsonify({'status': 'error', 'message': f'Cannot occupy slot: {conflict}'}), 409

    if patient_id_raw:
        try:
            patient_id = int(patient_id_raw)
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Invalid patient id.'}), 400
        patient = db.execute('SELECT id, name, status FROM patients WHERE id = ?', (patient_id,)).fetchone()
        if not patient:
            return jsonify({'status': 'error', 'message': 'Patient not found.'}), 404
        is_ongoing = (patient['status'] or '').lower() == 'ongoing'
        db.execute('''
            INSERT INTO appointments
            (patient_id, appointment_date, appointment_time, status, duration_minutes,
             is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_title)
            VALUES (?, ?, ?, 'scheduled', ?, ?, ?, ?, 'in-person', '### private meeting')
        ''', (
            patient_id,
            row['slot_date'],
            row['slot_time'],
            duration,
            1 if is_ongoing else 0,
            1 if is_ongoing else None,
            str(custom_weekday(date_obj)) if is_ongoing else None
        ))
        booked_label = patient['name']
    else:
        db.execute('''
            INSERT INTO blocked_slots (blocked_date, blocked_time, duration_minutes, title, is_private, block_type)
            VALUES (?, ?, ?, ?, 0, 'special')
        ''', (row['slot_date'], row['slot_time'], duration, occupant_name))
        booked_label = occupant_name

    db.execute('''
        UPDATE slots_override
        SET status = 'booked', booked_by_name = ?, booked_at = ?
        WHERE id = ?
    ''', (booked_label, datetime.now().isoformat(), override_id))
    db.commit()
    return jsonify({'status': 'success', 'message': f'Slot occupied by {booked_label}.'})


@app.route('/api/calendar/vacancies')
@login_required
def api_calendar_vacancies():
    """Admin: list all vacancy slots (open + recently booked)."""
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    today = datetime.now().date()
    rows = db.execute('''
        SELECT id, slot_date, slot_time, duration_minutes, status,
               booked_by_name, booked_by_phone, booked_at
        FROM slots_override
        WHERE slot_date >= ?
        ORDER BY slot_date ASC, slot_time ASC
    ''', ((today - timedelta(days=7)).isoformat(),)).fetchall()

    recurring_rows = db.execute('''
        SELECT id, weekday, slot_time, duration_minutes
        FROM vacancy_recurring
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY weekday ASC, slot_time ASC
    ''').fetchall()

    weekday_names = {
        0: 'Sunday',
        1: 'Monday',
        2: 'Tuesday',
        3: 'Wednesday',
        4: 'Thursday',
        5: 'Friday',
        6: 'Saturday'
    }

    items = []
    for row in rows:
        date_obj = parse_date_safe(row['slot_date'])
        t_obj = parse_time_safe(row['slot_time'])
        duration = int(row['duration_minutes'] or 60)
        end_dt = datetime.combine(date_obj, t_obj) + timedelta(minutes=duration) if date_obj and t_obj else None
        items.append({
            'id': row['id'],
            'kind': 'one-time',
            'date': row['slot_date'],
            'time': t_obj.strftime('%H:%M') if t_obj else row['slot_time'],
            'end_time': end_dt.strftime('%H:%M') if end_dt else '',
            'duration_minutes': duration,
            'status': row['status'],
            'booked_by_name': row['booked_by_name'] or '',
            'booked_by_phone': row['booked_by_phone'] or '',
            'booked_at': row['booked_at'] or '',
        })

    for row in recurring_rows:
        t_obj = parse_time_safe(row['slot_time'])
        duration = int(row['duration_minutes'] or 60)
        end_dt = None
        if t_obj:
            tmp_start = datetime.combine(today, t_obj)
            end_dt = tmp_start + timedelta(minutes=duration)
        weekday = int(row['weekday'])
        weekday_label = weekday_names.get(weekday, str(weekday))
        items.append({
            'id': row['id'],
            'kind': 'weekly',
            'date': f'Weekly ({weekday_label})',
            'time': t_obj.strftime('%H:%M') if t_obj else row['slot_time'],
            'end_time': end_dt.strftime('%H:%M') if end_dt else '',
            'duration_minutes': duration,
            'status': 'active',
            'booked_by_name': '',
            'booked_by_phone': '',
            'booked_at': '',
        })

    return jsonify({'items': items})


@app.route('/api/calendar/vacancy/<int:override_id>/delete', methods=['POST'])
@login_required
def api_calendar_vacancy_delete(override_id):
    """Admin: delete a vacancy slot."""
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    delete_kind = (request.form.get('kind') or 'one-time').strip().lower()

    db = get_db()
    if delete_kind == 'weekly':
        db.execute('DELETE FROM vacancy_recurring WHERE id = ?', (override_id,))
    else:
        db.execute('DELETE FROM slots_override WHERE id = ?', (override_id,))
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
    meeting_remarks = request.form.get('meeting_remarks', '').strip() or request.form.get('meeting_title', '').strip()
    save_to_google = 1 if request.form.get('save_to_google') in ('1', 'true', 'on') else 0
    is_recurring_explicit = request.form.get('is_recurring')
    recurrence_end_date_form = request.form.get('recurrence_end_date', '').strip()
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

    patient_status = None
    if booking_type != 'special' and patient_id:
        patient_row = db.execute('SELECT patient_type, status FROM patients WHERE id = ?', (patient_id,)).fetchone()
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
                  VALUES (?, ?, ?, ?, 1, 'blocked', ?)
            ''', (d.isoformat(), parse_time_safe(booking_time).strftime('%H:%M'), duration,
                  special_title or 'Special Occasion', current_user.id))
            db.execute('''
                UPDATE slots_override
                SET status = 'booked', booked_by_name = ?, booked_at = ?
                WHERE slot_date = ? AND slot_time = ? AND status = 'available'
            ''', (
                special_title or 'Special Occasion',
                datetime.now().isoformat(),
                d.isoformat(),
                parse_time_safe(booking_time).strftime('%H:%M')
            ))
        db.commit()
        return jsonify({'status': 'success'})

    # Business rule: honour explicit form value first, then default by patient status.
    # Ongoing patients default to weekly recurring; others default to one-time.
    if is_recurring_explicit == '1' or is_recurring_explicit == 'on' or is_recurring_explicit == 'true':
        is_recurring = 1
    elif is_recurring_explicit == '0':
        is_recurring = 0  # explicit one-time override, even for ongoing patients
    else:
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
        if recurrence_end_date_form:
            recurrence_end_date = recurrence_end_date_form
        else:
            recurrence_end_date = (anchor + timedelta(days=365)).isoformat()
    recurrence_group_id = build_recurrence_group_id() if is_recurring else None

    db.execute('''
        INSERT INTO appointments
        (patient_id, appointment_date, appointment_time, duration_minutes, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google, status, is_recurring, recurrence_interval, recurrence_days, recurrence_end_date, recurrence_group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?)
    ''', (
        patient_id,
        booking_date,
        parsed_booking_time.strftime('%H:%M'),
        duration,
        meeting_type,
        meeting_link or None,
        meeting_platform or None,
        meeting_remarks or None,
        save_to_google,
        is_recurring,
        recurrence_interval,
        recurrence_days,
        recurrence_end_date,
        recurrence_group_id
    ))

    booked_label = 'Appointment'
    if patient_id:
        patient = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
        if patient and patient['name']:
            booked_label = patient['name']
    db.execute('''
        UPDATE slots_override
        SET status = 'booked', booked_by_name = ?, booked_at = ?
        WHERE slot_date = ? AND slot_time = ? AND status = 'available'
    ''', (booked_label, datetime.now().isoformat(), booking_date, parsed_booking_time.strftime('%H:%M')))
    db.commit()

    # Sync to Google Calendar if save_to_google flag is set and admin is connected
    if save_to_google and gcal and patient_id:
        new_appt = db.execute('SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ? AND appointment_time = ? ORDER BY id DESC LIMIT 1',
                              (patient_id, booking_date, parsed_booking_time.strftime('%H:%M'))).fetchone()
        if new_appt:
            patient_row = db.execute('SELECT name FROM patients WHERE id = ?', (patient_id,)).fetchone()
            gcal.sync_appointment_to_google(
                db,
                appointment_id=new_appt['id'],
                patient_name=(patient_row['name'] if patient_row else booked_label),
                date_iso=booking_date,
                time_str=parsed_booking_time.strftime('%H:%M'),
                duration_minutes=duration,
                meeting_type=meeting_type,
                meeting_link=meeting_link or '',
            )

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
    recurrence_mode = (request.form.get('recurrence_mode') or 'auto').strip().lower()
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
    default_recurring = 1 if patient_status == 'ongoing' and patient_type not in ('initial-intake', 'diagnosee') else 0
    if recurrence_mode not in ('auto', 'one-time', 'recurring'):
        recurrence_mode = 'auto'

    if recurrence_mode == 'one-time':
        is_recurring = 0
    elif recurrence_mode == 'recurring':
        if patient_type in ('initial-intake', 'diagnosee'):
            flash('Initial-intake patients can only be booked as one-time meetings.', 'error')
            return redirect_to_patient_tab(patient_id, 'info')
        is_recurring = 1
    else:
        is_recurring = default_recurring

    recurrence_interval = 1 if is_recurring else None
    recurrence_days = str(custom_weekday(booking_date)) if is_recurring else None
    recurrence_end_date = (booking_date + timedelta(days=365)).isoformat() if is_recurring else None
    recurrence_group_id = build_recurrence_group_id() if is_recurring else None
    meeting_platform = meeting_type if meeting_type in ('zoom', 'google-meet') else None

    db.execute('''
        INSERT INTO appointments (
            patient_id, appointment_date, appointment_time, duration_minutes,
            meeting_type, meeting_link, meeting_platform, meeting_title,
            save_to_google, status, is_recurring, recurrence_interval,
            recurrence_days, recurrence_end_date, recurrence_group_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?)
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
        recurrence_end_date,
        recurrence_group_id
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

    is_recurring = int(appt['is_recurring'] or 0) == 1
    scope = request.form.get('scope', 'all').strip()
    occurrence_date_raw = request.form.get('occurrence_date', '').strip()
    recurrence_group_id = None
    related_rows = [appt]

    if is_recurring:
        recurrence_group_id = ensure_recurrence_group_id(db, appt)
        if recurrence_group_id:
            related_rows = db.execute(
                'SELECT * FROM appointments WHERE recurrence_group_id = ? ORDER BY appointment_date ASC, id ASC',
                (recurrence_group_id,)
            ).fetchall()

    if not is_recurring or scope == 'all':
        if is_recurring and recurrence_group_id:
            db.execute('DELETE FROM appointments WHERE recurrence_group_id = ?', (recurrence_group_id,))
        else:
            db.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))
        db.commit()
        return jsonify({'status': 'success'})

    if scope == 'one':
        occ_date = parse_date_safe(occurrence_date_raw)
        if not occ_date:
            return jsonify({'status': 'error', 'message': 'Invalid occurrence date.'}), 400
        try:
            existing_excluded = appt['excluded_dates'] or ''
        except (KeyError, IndexError):
            existing_excluded = ''
        excluded_list = [d for d in existing_excluded.split(',') if d.strip()]
        if occ_date.isoformat() not in excluded_list:
            excluded_list.append(occ_date.isoformat())
        db.execute('UPDATE appointments SET excluded_dates = ? WHERE id = ?',
                   (','.join(excluded_list), appointment_id))
        db.commit()
        return jsonify({'status': 'success'})

    if scope == 'upcoming':
        occ_date = parse_date_safe(occurrence_date_raw)
        if not occ_date:
            if recurrence_group_id:
                db.execute('DELETE FROM appointments WHERE recurrence_group_id = ?', (recurrence_group_id,))
            else:
                db.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))
            db.commit()
            return jsonify({'status': 'success'})

        for row in related_rows:
            base_date = parse_date_safe(row['appointment_date'])
            if not base_date:
                continue
            
            is_occurrence_in_series = False
            if base_date > occ_date:
                is_occurrence_in_series = False
            else:
                row_occurrences = recurring_occurrences_between(row, occ_date, occ_date)
                is_occurrence_in_series = len(row_occurrences) > 0
            
            if is_occurrence_in_series:
                if base_date >= occ_date:
                    # Truncating to occ_date-1 would make end < start — delete instead.
                    db.execute('DELETE FROM appointments WHERE id = ?', (row['id'],))
                else:
                    cutoff = (occ_date - timedelta(days=1)).isoformat()
                    db.execute('UPDATE appointments SET recurrence_end_date = ? WHERE id = ?', (cutoff, row['id']))
            elif base_date >= occ_date:
                db.execute('DELETE FROM appointments WHERE id = ?', (row['id'],))
        db.commit()
        return jsonify({'status': 'success'})

    # Fallback
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
    is_missed_meeting = 1 if request.form.get('is_missed_meeting') in ('1', 'true', 'on') else 0
    missed_reason = request.form.get('missed_reason', '').strip()
    if not is_missed_meeting:
        missed_reason = ''

    if content or is_missed_meeting:
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
                                  patient_appearance, behavior_checklist, mood_summary, behavior_notes,
                                  is_missed_meeting, missed_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                patient_id,
                appointment_id,
                session_number or None,
                note_date or None,
                content or 'Missed meeting documented.',
                patient_appearance or None,
                behavior_flags or None,
                mood_summary or None,
                behavior_notes or None,
                is_missed_meeting,
                missed_reason or None
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
        flash('Content is required unless this is marked as a missed meeting.')

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
    is_missed_meeting = 1 if request.form.get('is_missed_meeting') in ('1', 'true', 'on') else 0
    missed_reason = request.form.get('missed_reason', '').strip()
    if not is_missed_meeting:
        missed_reason = ''

    db = get_db()
    note = db.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
    if note:
        db.execute(
            '''UPDATE notes
               SET content = ?, session_number = ?, note_date = ?, patient_appearance = ?,
                   behavior_checklist = ?, mood_summary = ?, behavior_notes = ?,
                   is_missed_meeting = ?, missed_reason = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (
                content or 'Missed meeting documented.',
                session_number or None,
                note_date or None,
                patient_appearance or None,
                behavior_flags or None,
                mood_summary or None,
                behavior_notes or None,
                is_missed_meeting,
                missed_reason or None,
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

@app.route('/goal/<int:goal_id>/delete', methods=('POST',))
@login_required
def delete_goal(goal_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    goal = db.execute('SELECT * FROM goals WHERE id = ?', (goal_id,)).fetchone()
    if not goal:
        return "Goal not found", 404
    patient_id = goal['patient_id']
    db.execute('DELETE FROM goals WHERE id = ?', (goal_id,))
    db.commit()
    return redirect_to_patient_tab(patient_id, 'info')

@app.route('/goal/<int:goal_id>/edit', methods=('POST',))
@login_required
def edit_goal(goal_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    description = (request.form.get('description') or '').strip()
    db = get_db()
    goal = db.execute('SELECT * FROM goals WHERE id = ?', (goal_id,)).fetchone()
    if not goal:
        return "Goal not found", 404
    if description:
        db.execute('UPDATE goals SET description = ? WHERE id = ?', (description, goal_id))
        db.commit()
    else:
        flash('Goal description cannot be empty.')
    return redirect_to_patient_tab(goal['patient_id'], 'info')

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
        if not _allowed_upload(filename, ALLOWED_UPLOAD_EXTENSIONS):
            flash('File type not allowed. Accepted: docx, pdf, txt, png, jpg, gif, xlsx, csv.')
            return redirect_to_patient_tab(patient_id, 'notes')
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

    data = [dict(row) for row in appointments]
    response = Response(json.dumps(data, indent=4), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename=calendar_export.json'
    return response

def _seed_ongoing_patient(db, admin_id, today):
    db.execute(
        """INSERT INTO patients (name, status, email, phone, background, treatment_info)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            'Maya Cohen',
            'ongoing',
            'maya.cohen@example.com',
            '050-1234567',
            'Mid-30s professional. Referred by GP following prolonged work-related stress. '
            'Presents with symptoms of generalized anxiety and mild sleep disturbance.',
            'CBT formulation agreed. Exploring cognitive distortions related to performance at work. '
            'Engagement is strong, regular homework compliance.'
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


def _seed_candidate_patient(db, admin_id):
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


def _seed_waiting_patient(db, admin_id, today):
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


def _seed_archived_patient(db, today):
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


@app.route('/admin/seed_data', methods=('POST',))
@login_required
def seed_data():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    # Ensure latest schema/migrations are applied before inserting example records.
    init_db()
    db = get_db()

    # Keep sample data loading safe and repeatable — skip if any patients exist.
    existing_total = db.execute("SELECT COUNT(*) AS count FROM patients").fetchone()['count']
    if existing_total > 0:
        flash('Patient records already exist in the database. Seed data was not added.', 'info')
        return redirect(url_for('patients'))

    try:
        today = datetime.now()
        admin_user = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        admin_id = admin_user['id'] if admin_user else None

        _seed_ongoing_patient(db, admin_id, today)
        _seed_candidate_patient(db, admin_id)
        _seed_waiting_patient(db, admin_id, today)
        _seed_archived_patient(db, today)

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
        try:
            data = json.load(file)
            db = get_db()

            appointments_added = 0
            notes_added = 0
            receipts_added = 0

            if isinstance(data, list):
                appointments_added, notes_added, receipts_added = _import_flat_patient_history(db, patient_id, data)
            else:
                appointments_added, notes_added, receipts_added = _import_structured_patient_history(db, patient_id, data)

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

@app.route('/appointment/<int:appointment_id>/set_status', methods=['POST'])
@login_required
def set_appointment_status(appointment_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    status = (request.form.get('status') or '').strip()
    allowed_statuses = {'completed', 'no_show', 'scheduled', 'cancelled'}
    if status not in allowed_statuses:
        return "Invalid status", 400
    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if not appt:
        return "Appointment not found", 404
    db.execute('UPDATE appointments SET status = ? WHERE id = ?', (status, appointment_id))
    db.execute(
        'INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)',
        (appt['patient_id'], 'appointment-status', f'Appointment {appointment_id} marked {status}')
    )
    db.commit()
    return redirect_to_patient_tab(appt['patient_id'], 'notes')

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

        if patient_type in ('private', 'residency', 'initial-intake', 'diagnosee', 'group'):
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
            cursor = db.execute(
                'UPDATE messages SET is_read = 1 WHERE recipient_id = ? AND sender_id = ? AND COALESCE(is_read, 0) = 0',
                (current_user.id, requested_user)
            )
            if cursor.rowcount > 0:
                db.commit()

            normalized = []
            for c in conversations:
                c_dict = dict(c)
                if c_dict.get('user_id') == requested_user:
                    c_dict['unread_count'] = 0
                normalized.append(c_dict)
            conversations = normalized

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
    existing = db.execute('SELECT id, group_id FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
    if not existing:
        flash('Group session not found.')
        return redirect(url_for('groups_dashboard'))

    db.execute('DELETE FROM group_session_attendance WHERE session_id = ?', (session_id,))
    db.execute('DELETE FROM group_sessions WHERE id = ?', (session_id,))
    db.commit()
    flash('Group session deleted.')
    return redirect(url_for('group_detail', group_id=int(existing['group_id'])))


@app.route('/api/groups/sessions/<int:session_id>/delete', methods=['POST'])
@login_required
def api_delete_group_session(session_id):
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    existing = db.execute('SELECT id FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
    if not existing:
        return jsonify({'status': 'error', 'message': 'Group session not found.'}), 404

    db.execute('DELETE FROM group_session_attendance WHERE session_id = ?', (session_id,))
    db.execute('DELETE FROM group_sessions WHERE id = ?', (session_id,))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/api/groups/sessions/<int:session_id>/link_supervision', methods=['POST'])
@login_required
def api_link_group_session_supervision(session_id):
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    db = get_db()
    session_row = db.execute('SELECT id, group_id FROM group_sessions WHERE id = ?', (session_id,)).fetchone()
    if not session_row:
        return jsonify({'status': 'error', 'message': 'Group session not found.'}), 404

    sup_id_raw = (request.form.get('supervision_id') or '').strip()
    if not sup_id_raw:
        db.execute('UPDATE group_sessions SET supervision_id = NULL WHERE id = ?', (session_id,))
        db.commit()
        return jsonify({'status': 'success'})

    try:
        sup_id = int(sup_id_raw)
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid supervision id.'}), 400

    supervision_row = db.execute(
        'SELECT id FROM supervisions WHERE id = ? AND group_id = ?',
        (sup_id, int(session_row['group_id']))
    ).fetchone()
    if not supervision_row:
        return jsonify({'status': 'error', 'message': 'Supervision record not found for this group.'}), 404

    db.execute('UPDATE group_sessions SET supervision_id = ? WHERE id = ?', (sup_id, session_id))
    db.commit()
    return jsonify({'status': 'success'})


# ---------------------------------------------------------------------------
# Google Calendar OAuth routes
# ---------------------------------------------------------------------------

@app.route('/admin/google-calendar/status')
@login_required
def google_calendar_status():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    if not gcal:
        return jsonify({'connected': False, 'reason': 'Google libraries not installed.'})
    connected = gcal.is_connected(db)
    calendars = gcal.list_calendars(db) if connected else []
    calendar_id = gcal.get_calendar_id(db) if connected else None
    return jsonify({
        'connected': connected,
        'google_libs': gcal.GOOGLE_LIBS_AVAILABLE,
        'client_configured': gcal._client_secrets_available() if gcal else False,
        'calendar_id': calendar_id,
        'calendars': calendars,
    })


@app.route('/admin/google-calendar/connect')
@login_required
def google_calendar_connect():
    if current_user.role != 'admin':
        flash('Unauthorized.')
        return redirect(url_for('admin_profile'))
    if not gcal:
        flash('Google API libraries are not installed. Run: pip install google-auth-oauthlib google-api-python-client')
        return redirect(url_for('admin_profile'))
    if not gcal._client_secrets_available():
        flash('Google OAuth credentials are not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.')
        return redirect(url_for('admin_profile'))
    try:
        auth_url, state, code_verifier = gcal.get_authorization_url()
        session['gcal_oauth_state'] = state
        if code_verifier:
            session['gcal_code_verifier'] = code_verifier
        return redirect(auth_url)
    except Exception as exc:
        flash(f'Failed to initiate Google Calendar connection: {exc}')
        return redirect(url_for('admin_profile'))


@app.route('/admin/google-calendar/callback')
@login_required
def google_calendar_callback():
    if current_user.role != 'admin':
        flash('Unauthorized.')
        return redirect(url_for('admin_profile'))
    code = request.args.get('code')
    state = request.args.get('state')
    stored_state = session.pop('gcal_oauth_state', None)
    if not code:
        flash('Google authorisation was cancelled or failed.')
        return redirect(url_for('admin_profile'))
    if stored_state and state != stored_state:
        flash('OAuth state mismatch – please try connecting again.')
        return redirect(url_for('admin_profile'))
    try:
        code_verifier = session.pop('gcal_code_verifier', None)
        creds = gcal.exchange_code_for_tokens(code, state, code_verifier=code_verifier)
        db = get_db()
        calendar_id = request.args.get('calendar_id', 'primary')
        gcal.save_credentials(db, creds, calendar_id=calendar_id)
        flash('Google Calendar connected successfully!')
    except Exception as exc:
        flash(f'Failed to complete Google Calendar connection: {exc}')
    return redirect(url_for('admin_profile'))


@app.route('/admin/google-calendar/disconnect', methods=['POST'])
@login_required
def google_calendar_disconnect():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    if gcal:
        gcal.delete_credentials(db)
    flash('Google Calendar disconnected.')
    return redirect(url_for('admin_profile'))


@app.route('/admin/google-calendar/set-calendar', methods=['POST'])
@login_required
def google_calendar_set_calendar():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    calendar_id = (request.form.get('calendar_id') or 'primary').strip()
    db = get_db()
    if gcal and gcal.is_connected(db):
        creds = gcal.load_credentials(db)
        if creds:
            gcal.save_credentials(db, creds, calendar_id=calendar_id)
            return jsonify({'status': 'success', 'calendar_id': calendar_id})
    return jsonify({'status': 'error', 'message': 'Not connected to Google Calendar'}), 400


# ---------------------------------------------------------------------------
# Google Docs helper
# ---------------------------------------------------------------------------

def _pull_gdoc_notes(db, patient):
    """
    Read the linked Google Doc, parse session blocks, and upsert into the
    notes table.  Returns (synced_count, error_string_or_None).

    - [note:new] blocks  → INSERT; carry forward mood/appearance/checklist
      from most recent existing note (or blank); stamp doc with [note:id=N].
    - [note:id=N] blocks → UPDATE content if it has changed.
    """
    if not gdocs:
        return 0, 'google_docs module not available'
    creds = gcal.load_credentials(db) if gcal else None
    if not creds:
        return 0, 'Not connected to Google'
    creds = gcal._refresh_and_save(db, creds)

    doc_id = patient['gdoc_id']
    try:
        full_text = gdocs.read_doc_text(creds, doc_id)
    except Exception as exc:
        return 0, str(exc)

    parsed = gdocs.parse_doc_into_notes(full_text)

    # Carry-forward values from the most recent existing DB note
    prev = db.execute(
        'SELECT mood_summary, patient_appearance, behavior_checklist '
        'FROM notes WHERE patient_id = ? ORDER BY note_date DESC, id DESC LIMIT 1',
        (patient['id'],)
    ).fetchone()
    carry = {
        'mood_summary':       (prev['mood_summary']       if prev else '') or '',
        'patient_appearance': (prev['patient_appearance'] if prev else '') or '',
        'behavior_checklist': (prev['behavior_checklist'] if prev else '') or '',
    }

    synced = 0
    for item in parsed:
        if item['note_tag'] == 'new':
            row = db.execute(
                'INSERT INTO notes '
                '(patient_id, note_date, session_number, content, '
                ' mood_summary, patient_appearance, behavior_checklist) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (patient['id'], item['note_date'], item['session_number'],
                 item['content'],
                 carry['mood_summary'], carry['patient_appearance'],
                 carry['behavior_checklist'])
            )
            new_id = row.lastrowid
            db.commit()
            try:
                gdocs.stamp_note_id_in_doc(creds, doc_id, new_id)
            except Exception:
                pass
            synced += 1
        elif isinstance(item['note_tag'], int):
            note_id = item['note_tag']
            existing = db.execute(
                'SELECT id, content FROM notes WHERE id = ? AND patient_id = ?',
                (note_id, patient['id'])
            ).fetchone()
            if existing and existing['content'] != item['content']:
                db.execute('UPDATE notes SET content = ? WHERE id = ?',
                           (item['content'], note_id))
                db.commit()
                synced += 1

    return synced, None


# ---------------------------------------------------------------------------
# Google Docs routes
# ---------------------------------------------------------------------------

@app.route('/patient/<int:patient_id>/link-gdoc', methods=['POST'])
@login_required
def link_gdoc(patient_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    if not gdocs:
        return jsonify({'error': 'google_docs module not available'}), 500
    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    if not gcal:
        return jsonify({'error': 'Google libraries not installed'}), 500
    creds = gcal.load_credentials(db)
    if not creds:
        return jsonify({'error': 'Google not connected — connect via Admin Profile first'}), 400
    creds = gcal._refresh_and_save(db, creds)
    try:
        doc_id = gdocs.create_patient_doc(creds, patient['name'])
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500

    # Optionally register a Drive Watch webhook
    webhook_url = (request.form.get('webhook_url') or '').strip()
    channel_id, expiry = None, None
    if webhook_url:
        try:
            channel_id, expiry = gdocs.register_drive_watch(creds, doc_id, webhook_url)
        except Exception:
            pass  # webhook is optional; manual sync still works

    db.execute(
        'UPDATE patients SET gdoc_id = ?, gdoc_watch_channel = ?, gdoc_watch_expiry = ? WHERE id = ?',
        (doc_id, channel_id, expiry, patient_id)
    )
    db.commit()
    return jsonify({
        'status':  'ok',
        'doc_id':  doc_id,
        'doc_url': f'https://docs.google.com/document/d/{doc_id}/edit',
    })


@app.route('/patient/<int:patient_id>/attach-gdoc', methods=['POST'])
@login_required
def attach_gdoc(patient_id):
    """Link an existing Google Doc to a patient by URL or document ID."""
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    doc_url = request.form.get('doc_url', '').strip()
    if not doc_url:
        return jsonify({'error': 'No document URL provided'}), 400
    import re as _re
    m = _re.search(r'/document/d/([a-zA-Z0-9_-]+)', doc_url)
    doc_id = m.group(1) if m else doc_url.strip()
    if not doc_id:
        return jsonify({'error': 'Invalid document URL or ID'}), 400
    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    db.execute('UPDATE patients SET gdoc_id = ? WHERE id = ?', (doc_id, patient_id))
    db.commit()
    return jsonify({
        'status': 'ok',
        'doc_id': doc_id,
        'doc_url': f'https://docs.google.com/document/d/{doc_id}/edit',
    })


@app.route('/patient/<int:patient_id>/detach-gdoc', methods=['POST'])
@login_required
def detach_gdoc(patient_id):
    """Unlink the Google Doc from a patient (does not delete the doc itself)."""
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    db.execute(
        'UPDATE patients SET gdoc_id = NULL, gdoc_watch_channel = NULL, gdoc_watch_expiry = NULL WHERE id = ?',
        (patient_id,)
    )
    db.commit()
    return jsonify({'status': 'ok'})


@app.route('/patient/<int:patient_id>/open-gdoc')
@login_required
def open_gdoc(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    patient = db.execute('SELECT gdoc_id FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient or not patient['gdoc_id']:
        flash('No Google Doc linked for this patient.')
        return redirect(url_for('patient_detail', patient_id=patient_id))
    return redirect(f'https://docs.google.com/document/d/{patient["gdoc_id"]}/edit')


@app.route('/patient/<int:patient_id>/sync-from-gdoc', methods=['POST'])
@login_required
def sync_from_gdoc(patient_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    if not gdocs:
        return jsonify({'error': 'google_docs module not available'}), 500
    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient or not patient['gdoc_id']:
        return jsonify({'error': 'No Google Doc linked'}), 400
    count, err = _pull_gdoc_notes(db, patient)
    if err:
        return jsonify({'error': err}), 500
    return jsonify({'status': 'ok', 'synced': count})


@app.route('/api/gdoc/webhook', methods=['POST'])
@csrf.exempt
def gdoc_webhook():
    channel_id = request.headers.get('X-Goog-Channel-ID')
    if not channel_id:
        return '', 200
    db = get_db()
    patient = db.execute(
        'SELECT * FROM patients WHERE gdoc_watch_channel = ?', (channel_id,)
    ).fetchone()
    if patient and patient['gdoc_id'] and gdocs:
        try:
            _pull_gdoc_notes(db, patient)
        except Exception:
            pass
    return '', 200


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
    pending_secret = session.get('pending_totp_secret')
    totp_uri = _admin_totp_uri(admin, pending_secret) if pending_secret else None
    return render_template(
        'admin_profile.html',
        admin=admin,
        backup_files=backup_files,
        pending_totp_secret=pending_secret,
        totp_uri=totp_uri,
        totp_qr_url=f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote(totp_uri)}" if totp_uri else None
    )


@app.route('/admin/setup_authenticator', methods=['POST'])
@login_required
def setup_authenticator():
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    db = get_db()
    admin = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    if not admin:
        return 'Admin not found', 404

    action = (request.form.get('action') or '').strip().lower()
    if action == 'start':
        session['pending_totp_secret'] = pyotp.random_base32()
        flash('Authenticator setup started. Scan the QR code and verify with a code.')
        return redirect(url_for('admin_profile'))

    if action == 'disable':
        db.execute('UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?', (current_user.id,))
        db.commit()
        session.pop('pending_totp_secret', None)
        flash('Authenticator login has been disabled.')
        return redirect(url_for('admin_profile'))

    if action == 'verify':
        pending_secret = session.get('pending_totp_secret')
        otp_code = (request.form.get('otp_code') or '').strip()
        if not pending_secret:
            flash('Start setup first, then verify your code.')
            return redirect(url_for('admin_profile'))
        if not _verify_totp_code(pending_secret, otp_code):
            flash('Invalid authenticator code. Please try again.')
            return redirect(url_for('admin_profile'))

        db.execute('UPDATE users SET totp_secret = ?, totp_enabled = 1 WHERE id = ?', (pending_secret, current_user.id))
        db.commit()
        session.pop('pending_totp_secret', None)
        flash('Authenticator has been enabled for admin login.')
        return redirect(url_for('admin_profile'))

    flash('Invalid authenticator action.')
    return redirect(url_for('admin_profile'))


@app.route('/admin/change_password', methods=['POST'])
@login_required
def admin_change_password():
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    db = get_db()
    admin = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    if not admin:
        return 'Admin not found', 404

    current_password = (request.form.get('current_password') or '').strip()
    new_password = (request.form.get('new_password') or '').strip()
    confirm_password = (request.form.get('confirm_password') or '').strip()
    otp_code = (request.form.get('otp_code') or '').strip()

    if not check_password_hash(admin['password_hash'], current_password):
        flash('Current password is incorrect.')
        return redirect(url_for('admin_profile'))

    if len(new_password) < 5:
        flash('New password must include at least 5 characters.')
        return redirect(url_for('admin_profile'))

    if new_password != confirm_password:
        flash('New password confirmation does not match.')
        return redirect(url_for('admin_profile'))

    if not admin['totp_enabled'] or not admin['totp_secret']:
        flash('Enable authenticator first to change the admin password.')
        return redirect(url_for('admin_profile'))

    if not _verify_totp_code(admin['totp_secret'], otp_code):
        flash('Invalid authenticator code. Password was not changed.')
        return redirect(url_for('admin_profile'))

    db.execute(
        'UPDATE users SET password_hash = ?, force_password_change = 0 WHERE id = ?',
        (generate_password_hash(new_password), current_user.id)
    )
    db.commit()
    flash('Admin password updated successfully.')
    return redirect(url_for('admin_profile'))


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
                                             recurrence_end_date, recurrence_count, recurrence_group_id)
                                            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)''',
                   (patient_id, start_date, time, cost, duration, interval, days_str, 
                                        meeting_type, meeting_link, recurrence_end_date, recurrence_count, build_recurrence_group_id()))

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

def _handle_appointment_update_one(db, appt, appointment_id, occurrence_date_raw, booking_date, booking_time, duration, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google):
    occ_date = parse_date_safe(occurrence_date_raw)
    if not occ_date:
        return jsonify({'status': 'error', 'message': 'Invalid occurrence date.'}), 400
    new_day = parse_date_safe(booking_date)
    new_start_dt = combine_dt(new_day, parse_time_safe(booking_time).strftime('%H:%M'))
    new_end_dt = new_start_dt + timedelta(minutes=duration)
    conflict = has_time_conflict(db, new_day, new_start_dt, new_end_dt, exclude_appointment_id=appointment_id)
    if conflict:
        return jsonify({'status': 'error', 'message': conflict}), 409
    existing_excluded = appt['excluded_dates'] or ''
    excluded_list = [d for d in existing_excluded.split(',') if d.strip()]
    if occ_date.isoformat() not in excluded_list:
        excluded_list.append(occ_date.isoformat())
    # Prevent duplicate: if the new date is also a valid occurrence of the recurring series,
    # exclude it from the series too so the moved standalone is the only event on that day.
    if new_day and new_day.isoformat() != occ_date.isoformat():
        series_days = parse_recurrence_days(appt)
        series_base = parse_date_safe(appt['appointment_date'])
        series_end = parse_date_safe(appt['recurrence_end_date'] or '') if appt['recurrence_end_date'] else None
        if (custom_weekday(new_day) in series_days
                and series_base and new_day >= series_base
                and (not series_end or new_day <= series_end)
                and new_day.isoformat() not in excluded_list):
            excluded_list.append(new_day.isoformat())
    db.execute('UPDATE appointments SET excluded_dates = ? WHERE id = ?',
               (','.join(excluded_list), appointment_id))
    db.execute('''
        INSERT INTO appointments
        (patient_id, appointment_date, appointment_time, duration_minutes,
         is_recurring, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google)
        VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
    ''', (appt['patient_id'], new_day.isoformat(),
          parse_time_safe(booking_time).strftime('%H:%M'), duration,
          meeting_type, meeting_link or None, meeting_platform or None,
          meeting_title or None, save_to_google))
    db.commit()
    return jsonify({'status': 'success'})

def _handle_appointment_update_upcoming(db, appt, related_rows, occurrence_date_raw, booking_date, booking_time, duration, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google, recurrence_group_id):
    occ_date = parse_date_safe(occurrence_date_raw)
    if not occ_date:
        return jsonify({'status': 'error', 'message': 'Invalid occurrence date.'}), 400

    affects_series = False
    inherited_end = None
    cutoff = (occ_date - timedelta(days=1)).isoformat()
    for row in related_rows:
        row_base = parse_date_safe(row['appointment_date'])
        if not row_base:
            continue

        row_end = parse_date_safe(row['recurrence_end_date']) if row['recurrence_end_date'] else None
        if row_end and (inherited_end is None or row_end > inherited_end):
            inherited_end = row_end

        if row_base >= occ_date:
            affects_series = True
            db.execute('DELETE FROM appointments WHERE id = ?', (row['id'],))
            continue

        row_occurs_on_cutoff = recurring_occurrences_between(row, occ_date, occ_date)
        if row_occurs_on_cutoff:
            affects_series = True
            db.execute('UPDATE appointments SET recurrence_end_date = ? WHERE id = ?', (cutoff, row['id']))

    if not affects_series:
        return jsonify({'status': 'error', 'message': 'Occurrence does not belong to this recurring series.'}), 400

    new_day = parse_date_safe(booking_date)
    new_start_dt = combine_dt(new_day, parse_time_safe(booking_time).strftime('%H:%M'))
    new_end_dt = new_start_dt + timedelta(minutes=duration)
    conflict = has_time_conflict(db, new_day, new_start_dt, new_end_dt)
    if conflict:
        db.rollback()
        return jsonify({'status': 'error', 'message': conflict}), 409
    # Use the new date's weekday for the new series so occurrences land on the new day.
    rec_days = str(custom_weekday(new_day)) if new_day else (
        appt['recurrence_days'] if 'recurrence_days' in appt.keys() else None
    )
    rec_interval = max(int(appt['recurrence_interval'] or 1), 1)
    rec_end = inherited_end.isoformat() if inherited_end and inherited_end >= new_day else None
    db.execute('''
        INSERT INTO appointments
        (patient_id, appointment_date, appointment_time, duration_minutes,
         is_recurring, recurrence_days, recurrence_interval, recurrence_end_date,
         meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google, recurrence_group_id)
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (appt['patient_id'], new_day.isoformat(),
          parse_time_safe(booking_time).strftime('%H:%M'), duration,
          rec_days, rec_interval, rec_end,
          meeting_type, meeting_link or None, meeting_platform or None,
          meeting_title or None, save_to_google, recurrence_group_id or build_recurrence_group_id()))
    db.commit()
    return jsonify({'status': 'success'})

def _handle_appointment_update_all(db, appt, related_rows, occurrence_date_raw, booking_date, booking_time, duration, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google):
    new_day = parse_date_safe(booking_date)
    occ_date = parse_date_safe(occurrence_date_raw) or parse_date_safe(appt['appointment_date'])
    delta_days = (new_day - occ_date).days if new_day and occ_date else 0
    new_rec_days = str(custom_weekday(new_day)) if new_day else (
        appt['recurrence_days'] if 'recurrence_days' in appt.keys() else None
    )

    for row in related_rows:
        row_base = parse_date_safe(row['appointment_date'])
        if not row_base:
            continue
        shifted_day = row_base + timedelta(days=delta_days)
        shifted_start = combine_dt(shifted_day, parse_time_safe(booking_time).strftime('%H:%M'))
        shifted_end = shifted_start + timedelta(minutes=duration)
        conflict_message = has_time_conflict(
            db,
            shifted_day,
            shifted_start,
            shifted_end,
            exclude_appointment_id=row['id']
        )
        if conflict_message:
            return jsonify({'status': 'error', 'message': conflict_message}), 409

    for row in related_rows:
        row_base = parse_date_safe(row['appointment_date'])
        if not row_base:
            continue
        shifted_day = row_base + timedelta(days=delta_days)
        db.execute('''
            UPDATE appointments
            SET appointment_date = ?, appointment_time = ?, duration_minutes = ?,
                meeting_type = ?, meeting_link = ?, meeting_platform = ?,
                meeting_title = ?, save_to_google = ?, recurrence_days = ?
            WHERE id = ?
        ''', (shifted_day.isoformat(), parse_time_safe(booking_time).strftime('%H:%M'), duration,
              meeting_type, meeting_link or None, meeting_platform or None,
              meeting_title or None, save_to_google, new_rec_days, row['id']))
    db.commit()
    return jsonify({'status': 'success'})


@app.route('/api/calendar/appointment/<int:appointment_id>/update', methods=['POST'])
@login_required
def api_calendar_appointment_update(appointment_id):
    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if not appt:
        return jsonify({'status': 'error', 'message': 'Appointment not found.'}), 404

    if current_user.role == 'patient' and appt['patient_id'] != current_user.patient_id:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    scope = request.form.get('scope', 'all').strip()
    occurrence_date_raw = request.form.get('occurrence_date', '').strip()
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

    is_recurring = int(appt['is_recurring'] or 0) == 1
    recurrence_group_id = None
    related_rows = [appt]
    if is_recurring:
        recurrence_group_id = ensure_recurrence_group_id(db, appt)
        appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
        if recurrence_group_id:
            related_rows = db.execute(
                'SELECT * FROM appointments WHERE recurrence_group_id = ? ORDER BY appointment_date ASC, id ASC',
                (recurrence_group_id,)
            ).fetchall()

    # --- Scope: this occurrence only ---
    if is_recurring and scope == 'one':
        return _handle_appointment_update_one(db, appt, appointment_id, occurrence_date_raw, booking_date, booking_time, duration, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google)

    # --- Scope: this and all upcoming ---
    if is_recurring and scope == 'upcoming':
        return _handle_appointment_update_upcoming(db, appt, related_rows, occurrence_date_raw, booking_date, booking_time, duration, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google, recurrence_group_id)

    if is_recurring and scope == 'all':
        return _handle_appointment_update_all(db, appt, related_rows, occurrence_date_raw, booking_date, booking_time, duration, meeting_type, meeting_link, meeting_platform, meeting_title, save_to_google)

    # --- Default / scope='all': update the record directly ---
    day_obj = parse_date_safe(booking_date)
    start_dt = combine_dt(day_obj, parse_time_safe(booking_time).strftime('%H:%M'))
    end_dt = start_dt + timedelta(minutes=duration)
    conflict_message = has_time_conflict(db, day_obj, start_dt, end_dt, exclude_appointment_id=appointment_id)
    if conflict_message:
        return jsonify({'status': 'error', 'message': conflict_message}), 409

    # For recurring appointments, update recurrence_days to match the new date's weekday
    # so the entire series shifts to the new day rather than still generating old-weekday occurrences.
    new_rec_days = str(custom_weekday(day_obj)) if (is_recurring and day_obj) else (
        appt['recurrence_days'] if 'recurrence_days' in appt.keys() else None
    )
    db.execute('''
        UPDATE appointments
        SET appointment_date = ?, appointment_time = ?, duration_minutes = ?,
            meeting_type = ?, meeting_link = ?, meeting_platform = ?,
            meeting_title = ?, save_to_google = ?, recurrence_days = ?
        WHERE id = ?
    ''', (booking_date, parse_time_safe(booking_time).strftime('%H:%M'), duration,
          meeting_type, meeting_link or None, meeting_platform or None, meeting_title or None,
          save_to_google, new_rec_days, appointment_id))
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
    apply_scope = (request.form.get('apply_scope') or 'single').strip().lower()

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

    existing_date = parse_date_safe(existing['session_date'])
    if not existing_date:
        return jsonify({'status': 'error', 'message': 'Stored session date is invalid.'}), 500

    apply_future = apply_scope == 'future' and existing['series_id']
    target_rows = [existing]
    if apply_future:
        target_rows = db.execute('''
            SELECT *
            FROM group_sessions
            WHERE series_id = ? AND session_date >= ?
            ORDER BY session_date ASC, session_time ASC
        ''', (existing['series_id'], existing['session_date'])).fetchall()

    day_delta = (parsed_date - existing_date).days
    for row in target_rows:
        row_date = parse_date_safe(row['session_date'])
        if not row_date:
            return jsonify({'status': 'error', 'message': 'Existing recurrence row has invalid date.'}), 500
        updated_date = row_date + timedelta(days=day_delta) if apply_future else parsed_date
        start_dt = datetime.combine(updated_date, parsed_time)
        end_dt = start_dt + timedelta(minutes=duration)
        conflict_message = has_time_conflict(
            db,
            updated_date,
            start_dt,
            end_dt,
            exclude_group_session_id=int(row['id'])
        )
        if conflict_message:
            return jsonify({'status': 'error', 'message': f"{conflict_message} ({updated_date.isoformat()})"}), 409

    for row in target_rows:
        row_date = parse_date_safe(row['session_date'])
        updated_date = row_date + timedelta(days=day_delta) if apply_future else parsed_date
        db.execute('''
            UPDATE group_sessions
            SET session_date = ?, session_time = ?, duration_minutes = ?,
                title = ?, facilitator = ?, meeting_type = ?, meeting_link = ?
            WHERE id = ?
        ''', (
            updated_date.isoformat(),
            parsed_time.strftime('%H:%M'),
            duration,
            title or None,
            facilitator or None,
            meeting_type,
            meeting_link or None,
            row['id']
        ))

    if apply_future and existing['series_id']:
        db.execute('''
            UPDATE group_session_series
            SET start_date = ?, start_time = ?, duration_minutes = ?,
                title = ?, facilitator = ?, meeting_type = ?, meeting_link = ?
            WHERE id = ?
        ''', (
            parsed_date.isoformat(),
            parsed_time.strftime('%H:%M'),
            duration,
            title or None,
            facilitator or None,
            meeting_type,
            meeting_link or None,
            existing['series_id']
        ))

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
    patient = db.execute('SELECT id, name, intake_questionnaire, intake_assessment FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if patient is None:
        return "Patient not found", 404

    intake_data = parse_intake_questionnaire(patient['intake_questionnaire'], patient['intake_assessment'])
    if not intake_data:
        flash('No intake form data found for export.')
        return redirect_to_patient_tab(patient_id, 'intake')

    language = (request.args.get('lang') or 'en').strip().lower()
    if language not in {'en', 'he'}:
        language = 'en'

    document = build_intake_docx(patient['name'], intake_data, language=language)
    safe_name = secure_filename(patient['name'] or f'patient_{patient_id}')
    if not safe_name:
        safe_name = f'patient_{patient_id}'
    output_name = f'intake_{safe_name}.docx'
    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=output_name,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


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
        if patient_type not in ('private', 'residency', 'initial-intake', 'diagnosee', 'group'):
            patient_type = 'private'
        has_intake_tab = int(patient['has_intake_tab'] or 0)
        if patient_type in ('initial-intake', 'diagnosee'):
            has_intake_tab = 1
        if patient_type in ('initial-intake', 'diagnosee'):
            intake_assessment = request.form.get('intake_assessment')
            intake_questionnaire = request.form.get('intake_questionnaire')
            if intake_assessment is None:
                intake_assessment = patient['intake_assessment'] or ''
            else:
                intake_assessment = intake_assessment.strip()
            if intake_questionnaire is None:
                intake_questionnaire = patient['intake_questionnaire'] or ''
            else:
                intake_questionnaire = intake_questionnaire.strip()
        else:
            intake_assessment = ''
            intake_questionnaire = ''

        if not name:
            flash('Name is required!')
        else:
            treatment_method = request.form.get('treatment_method', '').strip() or None
            db.execute('''UPDATE patients
                          SET name = ?, status = ?, email = ?, phone = ?, birth_date = ?, id_number = ?, can_self_schedule = ?,
                              patient_type = ?, has_intake_tab = ?, intake_assessment = ?, intake_questionnaire = ?,
                              treatment_method = ?
                          WHERE id = ?''',
                       (name, status, email, phone, birth_date, id_number, can_self_schedule, patient_type,
                        has_intake_tab, intake_assessment or None, intake_questionnaire or None, treatment_method, patient_id))
            db.commit()
            flash('Patient updated successfully.')
            return redirect(url_for('patient_detail', patient_id=patient_id))

    db_r = get_db()
    treatment_method_options = [r['label'] for r in db_r.execute(
        'SELECT label FROM treatment_method_options ORDER BY display_order ASC, label ASC'
    ).fetchall()]
    return render_template('edit_patient.html', patient=patient, treatment_method_options=treatment_method_options)

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
    if patient_type in ('initial-intake', 'diagnosee'):
        is_recurring = 0

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
                                                                        recurrence_end_date, recurrence_count, meeting_title, save_to_google, recurrence_group_id) 
                                                                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (patient_id, date, time, cost, duration, recurrence_interval, 
                                recurrence_days, meeting_type, meeting_link, recurrence_end_date, recurrence_count,
                                                                meeting_title or None, save_to_google, build_recurrence_group_id()))
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
        ical_content += "LOCATION:Clinic\r\n"

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

    if notifications:
        notification_ids = [n['id'] for n in notifications]
        placeholders = ','.join(['?'] * len(notification_ids))
        db.execute(f'UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})', notification_ids)
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
    ensure_runtime_paths()
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
