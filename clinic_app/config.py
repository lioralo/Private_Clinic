import os
import sys
import importlib
import threading
from pathlib import Path
from werkzeug.security import generate_password_hash


def _import_optional_module(*module_names):
    scripts_dir = Path(__file__).resolve().parent.parent / 'scripts'
    scripts_dir_str = str(scripts_dir)
    if scripts_dir.is_dir() and scripts_dir_str not in sys.path:
        sys.path.insert(0, scripts_dir_str)

    for module_name in module_names:
        try:
            return importlib.import_module(module_name)
        except ImportError:
            continue

    for module_name in module_names:
        if module_name.startswith('scripts.'):
            bare_name = module_name.split('.', 1)[1]
            try:
                return importlib.import_module(bare_name)
            except ImportError:
                continue

    return None


gcal = _import_optional_module('google_calendar', 'scripts.google_calendar')
gdocs = _import_optional_module('google_docs', 'scripts.google_docs')


TRANSLATION_OVERRIDES_FILE = Path(__file__).resolve().parent.parent / 'translations' / 'he.json'


DATABASE = os.environ.get('DATABASE', 'clinic.db')
BACKUP_DIR = os.environ.get('BACKUP_DIR', 'secure_backups')
KEY_DIR = os.environ.get('KEY_DIR', '.clinic_keys')
BACKUP_INTERVAL_HOURS = 12
ALLOWED_UPLOAD_EXTENSIONS = {'.docx', '.pdf', '.txt', '.png', '.jpg', '.jpeg', '.gif', '.xlsx', '.csv'}
ALLOWED_DIAGNOSIS_EXTENSIONS = {'.pdf', '.docx', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}
DUMMY_PASSWORD_HASH = generate_password_hash('dummy_password_for_timing_attack_mitigation')


GDOC_AUTO_SYNC_INTERVAL_SECONDS = {
    'twice_daily': 12 * 60 * 60,
    'daily': 24 * 60 * 60,
    'twice_weekly': int(3.5 * 24 * 60 * 60),
    'weekly': 7 * 24 * 60 * 60,
    'biweekly': 14 * 24 * 60 * 60,
    'monthly': 30 * 24 * 60 * 60,
}
GDOC_AUTO_SYNC_GROUP_MODES = {'pull', 'both'}


_GDOC_AUTO_SYNC_LOCK = threading.Lock()
_GDOC_AUTO_SYNC_LAST_CHECK_TS = 0.0
_GDOC_AUTO_SYNC_WORKER_STATE_LOCK = threading.Lock()
_GDOC_AUTO_SYNC_WORKER_STARTED = False
_GDOC_AUTO_SYNC_STOP_EVENT = threading.Event()
_GDOC_MANUAL_SYNC_JOB_LOCK = threading.Lock()
_GDOC_MANUAL_SYNC_JOBS = {}
_GDOC_MANUAL_SYNC_ACTIVE_JOB_ID = None
_GDOC_MANUAL_SYNC_MAX_JOBS = 40
_REMINDER_WORKER_STATE_LOCK = threading.Lock()
_REMINDER_WORKER_STARTED = False
_REMINDER_WORKER_STOP_EVENT = threading.Event()
_SECURITY_RETENTION_LOCK = threading.Lock()
_SECURITY_RETENTION_LAST_CHECK_TS = 0.0


HEBREW_NUMBER_WORDS = {
    'אחד': '1', 'אחת': '1',
    'שני': '2', 'שניים': '2', 'שתיים': '2', 'שתי': '2',
    'שלושה': '3', 'שלוש': '3',
    'ארבעה': '4', 'ארבע': '4',
    'חמישה': '5', 'חמש': '5',
}

BACKGROUND_REASON_TOPICS = {
    'אבל ואובדן': ['נפטר', 'פטירה', 'שבעה', 'אבל', 'אלמן', 'אלמנה'],
    'חרדה ומתח': ['חרד', 'חרדה', 'פחד', 'חשש', 'דאג', 'לחץ'],
    'קשיים במשפחה וביחסים קרובים': ['ילדים', 'ילד', 'בת', 'בן', 'בעל', 'אמא', 'אבא', 'משפחה', 'זוג'],
    'קשיי תפקוד בעבודה או בלימודים': ['עבודה', 'מנהל', 'בוס', 'מפעל', 'מכללה', 'לומד', 'לומדת', 'צבא'],
    'בושה, חריגות ודימוי עצמי': ['בושה', 'חריג', 'לא בסדר', 'אשם', 'לא נחמדה', 'רעה'],
    'מחשבות אובססיביות או ירידה נפשית': ['אובסס', 'דיכא', 'בדידות', 'אין לו כח', 'אין לה כח', 'שעמום'],
}

BACKGROUND_THEME_TOPICS = {
    'יחסי קרבה, תלות ועצמאות': ['עצמאי', 'עצמאית', 'תלוי', 'תלות', 'להיעזר', 'להיתמך', 'לעזור', 'מרחק', 'קרובה'],
    'ביקורת עצמית ותחושת חריגות': ['בושה', 'חריג', 'לא בסדר', 'אשם', 'רעה', 'לא נחמדה'],
    'חרדה, דריכות וציפייה לפגיעה': ['חרד', 'פחד', 'חשש', 'לא בטוח', 'סכנה', 'מאיים', 'דריכות'],
    'אבל, בדידות וחוויית אובדן': ['נפטר', 'פטירה', 'בדידות', 'שכול', 'שבעה', 'אובדן'],
    'גבולות, עימותים וקונפליקטים': ['גבול', 'ריב', 'כעס', 'תוקף', 'אסרטיב', 'מריבה', 'ויכוח'],
    'עומס תפקודי בעבודה, לימודים או שירות': ['עבודה', 'מכללה', 'לימוד', 'צבא', 'משמרת', 'תפקיד', 'מפעל'],
}

LEGACY_WAITING_STATUSES = {'candidate', 'waiting', 'waiting for scheduling'}

DEFAULT_SITE_SETTINGS = {
    'about_enabled': '0',
    'about_phone': '',
    'about_email': '',
    'about_text': '',
    'about_map_url': '',
    'questionnaires_source_sheet_url': '',
    'gdocs_auto_sync_enabled': '0',
    'gdocs_auto_sync_interval': 'daily',
    'gdocs_auto_sync_targets_json': '[]',
    'gdocs_auto_sync_targets_config_json': '[]',
    'gdocs_auto_sync_last_run_at': '',
    'google_enabled_integrations': '["calendar","docs","sheets"]',
    'security_scan_enabled': '0',
    'security_scan_interval': 'daily',
    'security_scan_last_run_at': '',
    'security_scan_last_status': '',
    'security_scan_last_results_json': '{}',
}

HEBREW_TRANSLATIONS = {}
