import os
import sqlite3
import pyotp
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import datetime

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

@app.template_filter('from_iso_date')
def from_iso_date(value):
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return value

@app.template_filter('from_iso_datetime')
def from_iso_datetime(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return value

@app.template_filter('strftime')
def strftime_filter(value, format_string):
    try:
        return value.strftime(format_string)
    except AttributeError:
        return value

@app.template_filter('date')
def date_filter(value):
    try:
        return value.date()
    except AttributeError:
        return value

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
    backup_dir = 'archive/backups'
    if not os.path.exists(backup_dir):
        return []
    backups = []
    for f in os.listdir(backup_dir):
        if f.endswith('.enc'):
            path = os.path.join(backup_dir, f)
            backups.append({'name': f, 'size': os.path.getsize(path), 'date': datetime.fromtimestamp(os.path.getmtime(path))})
    return sorted(backups, key=lambda x: x['date'], reverse=True)


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

        # Migrate existing users table to add otp_secret if it doesn't exist
        try:
            db.execute("ALTER TABLE users ADD COLUMN otp_secret TEXT")
            db.commit()
        except sqlite3.OperationalError:
            pass # Column already exists

        # Check if admin exists
        admin = db.execute("SELECT * FROM users WHERE role = 'admin'").fetchone()
        if not admin:
            print("Creating default admin user...")
            hashed_pw = generate_password_hash('admin')
            # Generate a 16-character base32 secret for TOTP
            otp_secret = pyotp.random_base32()
            db.execute("INSERT INTO users (username, password_hash, role, otp_secret) VALUES (?, ?, ?, ?)",
                       ('admin', hashed_pw, 'admin', otp_secret))
            db.commit()
            print("Admin user created (username: admin, password: admin).")
            print("=" * 60)
            print(f"Admin 2FA Secret: {otp_secret}")
            totp_uri = pyotp.totp.TOTP(otp_secret).provisioning_uri(name='admin', issuer_name='Private Clinic')
            print(f"Admin 2FA URI (use this in an Authenticator app, or copy the secret): {totp_uri}")
            print("=" * 60)
        else:
            if not admin['otp_secret']:
                print("Generating 2FA secret for existing admin user...")
                otp_secret = pyotp.random_base32()
                db.execute("UPDATE users SET otp_secret = ? WHERE id = ?", (otp_secret, admin['id']))
                db.commit()
                print("=" * 60)
                print(f"Admin 2FA Secret: {otp_secret}")
                totp_uri = pyotp.totp.TOTP(otp_secret).provisioning_uri(name=admin['username'], issuer_name='Private Clinic')
                print(f"Admin 2FA URI (use this in an Authenticator app, or copy the secret): {totp_uri}")
                print("=" * 60)

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
    try:
        get_db()
    except sqlite3.OperationalError:
        init_db()

    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == 'patient':
            return redirect(url_for('patient_home'))
    return render_template('landing.html')


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
        except (ValueError, TypeError):
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
    update_data = []
    for idx, patient_id in enumerate(data["order"]):
        if not isinstance(patient_id, int):
            return jsonify({'error': 'Invalid patient id'}), 400
        update_data.append((idx, patient_id))
    db.executemany('UPDATE patients SET sort_order = ? WHERE id = ? AND COALESCE(is_deleted,0) = 0', update_data)

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
        engagement=engagement_data,
        now=datetime.now()
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
        otp_token = request.form.get('otp_token')
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

            if user['role'] == 'admin':
                if not otp_token:
                    flash('2FA token is required for admin login')
                    return render_template('login.html')

                if user['otp_secret']:
                    totp = pyotp.TOTP(user['otp_secret'])
                    if not totp.verify(otp_token):
                        flash('Invalid 2FA token')
                        return render_template('login.html')
                else:
                    flash('Admin account is missing 2FA configuration')
                    return render_template('login.html')

            user_obj = User(user['id'], user['username'], user['role'], user['patient_id'])
            login_user(user_obj)
            if user['role'] == 'admin':
                return redirect(url_for('patients'))
            else:
                return redirect(url_for('dashboard'))
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
        return redirect(url_for('dashboard'))

    status = request.args.get('status', 'ongoing')
    db = get_db()

    # Modified query to include unread message count
    patients = db.execute('''
        SELECT p.*,
        (SELECT COUNT(*) FROM messages m
         JOIN users u ON m.sender_id = u.id
         WHERE u.patient_id = p.id AND m.is_read = 0 AND m.recipient_id = ?) as unread_count
        FROM patients p
        WHERE p.status = ?
    ''', (current_user.id, status)).fetchall()

    return render_template('index.html', patients=patients, status=status)

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
    schedules = db.execute('SELECT * FROM schedules WHERE patient_id = ? ORDER BY day_of_week, appointment_time', (patient_id,)).fetchall()

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
                    flash(escape(f'DOCX parsed. {notes_created} notes created, {notes_review} marked for review.'))
                else:
                    flash(escape(f'DOCX parsed successfully. {notes_created} notes created.'))
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
        flash(escape(f'Sample data already exists or an error occurred: {str(e)}'), 'error')
    except Exception as e:
        db.rollback()
        flash(escape(f'Error seeding data: {str(e)}'), 'error')

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
            flash(escape(f'Successfully imported {count} appointments.'))
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


                # Import appointments
                appt_id_map = {}
                # Sort appointments by date and time
                sorted_appts = sorted(data.get('appointments', []), key=lambda x: (x.get('appointment_date', ''), x.get('appointment_time', '')))

                # Pre-fetch existing appointments for this patient
                existing_appts_query = db.execute(
                    'SELECT id, appointment_date, appointment_time FROM appointments WHERE patient_id = ?',
                    (patient_id,)
                ).fetchall()

                existing_appts_dict = {
                    (row['appointment_date'], row['appointment_time']): row['id']
                    for row in existing_appts_query
                }

                for appt in sorted_appts:
                    appt_date = appt.get('appointment_date')
                    appt_time = appt.get('appointment_time')

                    # Check for existing
                    existing_id = existing_appts_dict.get((appt_date, appt_time))

                    if not existing_id:
                        cursor = db.execute('''INSERT INTO appointments
                            (patient_id, appointment_date, appointment_time, cost, duration_minutes, is_recurring, recurrence_interval, recurrence_days, meeting_type, meeting_link, status, recurrence_end_date, recurrence_count)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (patient_id, appt_date, appt_time, appt.get('cost'), appt.get('duration_minutes'),
                             appt.get('is_recurring'), appt.get('recurrence_interval'), appt.get('recurrence_days'), appt.get('meeting_type'),
                             appt.get('meeting_link'), appt.get('status'), appt.get('recurrence_end_date'), appt.get('recurrence_count')))
                        appt_id_map[appt.get('id')] = cursor.lastrowid
                        existing_appts_dict[(appt_date, appt_time)] = cursor.lastrowid
                        appointments_added += 1
                    else:
                        appt_id_map[appt.get('id')] = existing_id

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
                receipts_data = data.get('receipts', [])
                if receipts_data:
                    receipt_tuples = [
                        (patient_id, r.get('amount'), r.get('description'), r.get('created_at'))
                        for r in receipts_data
                    ]
                    db.executemany('''INSERT INTO receipts
                        (patient_id, amount, description, created_at)
                        VALUES (?, ?, ?, ?)''', receipt_tuples)
                    receipts_added += len(receipts_data)
                appointments_added, notes_added, receipts_added = _import_structured_patient_history(db, patient_id, data)

            db.commit()
            flash(escape(f'History imported: {appointments_added} appointments, {notes_added} notes, {receipts_added} receipts added.'))
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
    name = secure_filename(name)

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

def _get_admin_messages(db):
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

    if requested_user is not None and not any(c['user_id'] == requested_user for c in conversations if c['user_id'] is not None):
        requested_user = None

    if requested_user is not None:
        db.execute(
            'UPDATE messages SET is_read = 1 WHERE recipient_id = ? AND sender_id = ?',
            (current_user.id, requested_user)
        )
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

def _get_patient_messages(db):
    messages = db.execute('''
        SELECT m.*, u.username as sender_name
        FROM messages m
        LEFT JOIN users u ON m.sender_id = u.id
        WHERE m.sender_id = ? OR m.recipient_id = ?
        ORDER BY m.timestamp ASC
    ''', (current_user.id, current_user.id)).fetchall()

    return jsonify([dict(m) for m in messages])

@app.route('/api/messages', methods=['GET'])
@login_required
def api_get_messages():
    db = get_db()
    if current_user.role == 'admin':
        return _get_admin_messages(db)
    else:
        return _get_patient_messages(db)

@app.route('/api/messages/send', methods=['POST'])
@login_required
def api_send_message():
    content = request.form.get('content')
    if not content:
        return jsonify({'status': 'error'})

    db = get_db()

    recipient_id = None

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
        flash(escape(f"Access {'enabled' if new_status else 'disabled'}."))
    else:
        flash('No user account found for this patient.')

    return redirect_to_patient_tab(patient_id, 'info')

def _validate_appointment_datetime(date_str, time_str):
    if not date_str or not time_str:
        return None, 'Date and time are required!'

    try:
        datetime.fromisoformat(date_str)
    except ValueError:
        return None, 'Invalid date format!'

    try:
        time_obj = datetime.strptime(time_str, '%H:%M')
        formatted_time = time_obj.strftime('%H:%M')
        return formatted_time, None
    except ValueError:
        return None, 'Invalid time format! Expected HH:MM'

def _extract_recurrence_data(form):
    recurrence_interval = int(form.get('interval', 1))
    recurrence_days = None
    recurrence_end_date = None
    recurrence_count = None

    limit_type = form.get('recurrence_limit_type')
    if limit_type == 'date':
        recurrence_end_date = form.get('recurrence_end_date', '').strip()
        if recurrence_end_date:
            try:
                datetime.fromisoformat(recurrence_end_date)
            except ValueError:
                return None, None, None, None, 'Invalid recurrence end date!'
    elif limit_type == 'count':
        try:
            recurrence_count = int(form.get('recurrence_count', 12))
            if recurrence_count <= 0:
                recurrence_count = 12
        except ValueError:
            recurrence_count = 12

    days_list = form.getlist('days')
    if days_list:
        recurrence_days = ','.join(str(d) for d in days_list if d.strip().isdigit())

    return recurrence_interval, recurrence_days, recurrence_end_date, recurrence_count, None

def _insert_appointment_db(db, patient_id, date, time, cost, duration, is_recurring,
                           recurrence_interval, recurrence_days, meeting_type, meeting_link,
                           recurrence_end_date, recurrence_count, meeting_title, save_to_google):
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

    formatted_time, dt_error = _validate_appointment_datetime(date, time)
    if dt_error:
        flash(dt_error, 'error')
        return redirect(url_for('patient_detail', patient_id=patient_id))
    time = formatted_time

    db = get_db()
    patient_row = db.execute('SELECT patient_type FROM patients WHERE id = ?', (patient_id,)).fetchone()
    patient_type = (patient_row['patient_type'] if patient_row else 'private') or 'private'
    if patient_type in ('initial-intake', 'diagnosee'):
        is_recurring = 0

    recurrence_interval = None
    recurrence_days = None
    recurrence_end_date = None
    recurrence_count = None

    if is_recurring:
        recurrence_interval, recurrence_days, recurrence_end_date, recurrence_count, rec_error = _extract_recurrence_data(request.form)
        if rec_error:
            flash(rec_error, 'error')
            return redirect(url_for('patient_detail', patient_id=patient_id))

    try:
        _insert_appointment_db(db, patient_id, date, time, cost, duration, is_recurring,
                               recurrence_interval, recurrence_days, meeting_type, meeting_link,
                               recurrence_end_date, recurrence_count, meeting_title, save_to_google)
        db.commit()
        appt_msg = "Recurring appointment series added successfully." if is_recurring else "Single appointment added."
        flash(appt_msg)
    except sqlite3.IntegrityError as e:
        flash(escape(f'Error adding appointment: {str(e)}'), 'error')
    except Exception as e:
        flash(escape(f'Unexpected error: {str(e)}'), 'error')

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

@app.route('/agenda')
@login_required
def agenda():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    week_offset = request.args.get('week_offset', 0, type=int)

    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    end_of_week = start_of_week + datetime.timedelta(days=6)

    db = get_db()

    # Fetch one-time appointments for the week
    appointments = db.execute('''
        SELECT a.*, p.name as patient_name
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        WHERE a.appointment_date BETWEEN ? AND ?
    ''', (start_of_week, end_of_week)).fetchall()

    # Fetch recurring schedules
    # We need to map day_of_week (0-6) to the actual dates in the current week view
    schedules = db.execute('''
        SELECT s.*, p.name as patient_name
        FROM schedules s
        JOIN patients p ON s.patient_id = p.id
        WHERE p.status = 'ongoing'
    ''').fetchall()

    # Construct the calendar data
    days = []
    for i in range(7):
        current_date = start_of_week + datetime.timedelta(days=i)
        day_name = current_date.strftime("%A")
        date_str = current_date.strftime("%b %d")

        day_appointments = []

        # Add one-time appointments
        for appt in appointments:
            appt_date = datetime.datetime.strptime(appt['appointment_date'], '%Y-%m-%d').date()
            if appt_date == current_date:
                # Parse time to get hour for positioning (simplified)
                hour = int(appt['appointment_time'].split(':')[0])
                day_appointments.append({
                    'time': appt['appointment_time'],
                    'patient_name': appt['patient_name'],
                    'type': 'one-time',
                    'hour': hour
                })

        # Add recurring schedules
        # Note: In Python weekday() Monday is 0. DB should match this.
        for sch in schedules:
            if sch['day_of_week'] == i:
                hour = int(sch['appointment_time'].split(':')[0])
                day_appointments.append({
                    'time': sch['appointment_time'],
                    'patient_name': sch['patient_name'],
                    'type': 'recurring',
                    'hour': hour
                })

        days.append({
            'name': day_name,
            'date': date_str,
            'appointments': day_appointments
        })

    return render_template('agenda.html',
                           days=days,
                           week_start=start_of_week.strftime("%b %d"),
                           week_end=end_of_week.strftime("%b %d"),
                           week_offset=week_offset)

@app.route('/patient/<int:patient_id>/add_schedule', methods=('POST',))
@login_required
def add_schedule(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    day = request.form['day']
    time = request.form['time']

    if day and time:
        db = get_db()
        db.execute('INSERT INTO schedules (patient_id, day_of_week, appointment_time) VALUES (?, ?, ?)',
                   (patient_id, day, time))
        db.commit()
        flash('Recurring schedule added.')

    return redirect(url_for('patient_detail', patient_id=patient_id))

@app.route('/schedule/<int:schedule_id>/delete', methods=('POST',))
@login_required
def delete_schedule(schedule_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    sch = db.execute('SELECT patient_id FROM schedules WHERE id = ?', (schedule_id,)).fetchone()
    if sch:
        db.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
        db.commit()
        flash('Recurring schedule removed.')
        return redirect(url_for('patient_detail', patient_id=sch['patient_id']))

    return "Schedule not found", 404

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
