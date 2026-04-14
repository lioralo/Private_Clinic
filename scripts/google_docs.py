"""
Google Docs integration for the Private Clinic app.

Provides:
- create_patient_doc()       – create a templated treatment-log Google Doc
- read_doc_text()            – fetch plain text from a Doc
- stamp_note_id_in_doc()     – replace [note:new] with [note:id=N] after saving
- register_drive_watch()     – register Drive push-notification channel
- parse_doc_into_notes()     – bilingual (EN + HE) session-block parser

Parser format (English):
    SESSION #1 | 2026-04-01 [note:new]
    Free text content…

Parser format (Hebrew, pipe style):
    פגישה #1 | 2026-04-01 [note:new]
    תוכן חופשי…

Parser format (Hebrew, dash style – real-world):
    פגישה 1- 05/08/25
    פגישה 1- 05/08/2025
    פגישה #1- 05/08/25
    ~פגישה 6- 23/02/26
    (# is optional, a leading ~ is allowed, date is DD/MM/YY or DD/MM/YYYY, separator is a dash)

Identity tags:
    [note:new]    – not yet saved; will be inserted and stamped with [note:id=N]
    [note:id=N]   – already saved; content will be compared and updated if changed

Fields NOT parsed from doc (mood_summary, patient_appearance, behavior_checklist)
are handled by the caller (carried forward from the most recent DB note, or blank).
"""

import re
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Soft-import Google libs so the app still starts without them
# ---------------------------------------------------------------------------
try:
    from googleapiclient.discovery import build
    GDOCS_LIBS_AVAILABLE = True
except ImportError:
    GDOCS_LIBS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Bilingual session-header regex
#
# Matches all known formats:
#   SESSION #3 | 2026-04-01 [note:new]       (English, ISO date, pipe)
#   פגישה #3 | 2026-04-01 [note:id=7]        (Hebrew, ISO date, pipe)
#   פגישה 1- 05/08/25                         (Hebrew, DD/MM/YY, dash)
#   פגישה 1- 05/08/2025                       (Hebrew, DD/MM/YYYY, dash)
#   פגישה #1- 05/06/25                        (Hebrew, optional #, dash)
#   ~פגישה 6- 23/02/26                        (Hebrew, leading tilde marker)
# ---------------------------------------------------------------------------
_SESSION_RE = re.compile(
    r'^\s*[~•*\-–—]?\s*(?:SESSION|פגישה)\s*#?(\d+)\s*'   # optional marker + keyword + optional # + number
    r'(?:'
        r'\|\s*(\d{4}-\d{2}-\d{2})'                           # pipe + ISO date (YYYY-MM-DD)
        r'|'
        r'[-־–—]\s*(\d{1,2}/\d{1,2}/\d{2,4})'                  # dash variants + DD/MM/YY(YY)
    r')'
    r'(?:\s*(\[note:[^\]]+\]))?',                              # optional [note:…] tag
    re.MULTILINE | re.IGNORECASE,
)

_NOTE_ID_RE = re.compile(r'\[note:id=(\d+)\]')


def _parse_date(iso_group, slash_group):
    """Return a YYYY-MM-DD string from whichever capture group matched."""
    if iso_group:
        return iso_group  # already ISO
    # slash_group: DD/MM/YY or DD/MM/YYYY
    parts = slash_group.split('/')
    if len(parts) != 3:
        return None
    day, month, year = parts
    if len(year) == 2:
        year = '20' + year  # 25 → 2025
    try:
        dt = datetime(int(year), int(month), int(day))
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_doc_into_notes(text):
    """
    Parse a Google Doc's plain text into a list of session dicts.

    Returns:
        list of {session_number, note_date, content, note_tag}
        note_tag is 'new', an integer (existing note id), or 'new' as fallback.
    """
    results = []
    matches = list(_SESSION_RE.finditer(text))
    for i, m in enumerate(matches):
        session_num = int(m.group(1))
        # group(2) = ISO date from pipe-style; group(3) = DD/MM/YY from dash-style
        note_date   = _parse_date(m.group(2), m.group(3))
        raw_tag     = (m.group(4) or '').strip()

        block_start = m.end()
        block_end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content     = text[block_start:block_end].strip()

        if '[note:new]' in raw_tag:
            note_tag = 'new'
        else:
            id_match = _NOTE_ID_RE.search(raw_tag)
            note_tag = int(id_match.group(1)) if id_match else 'new'

        results.append({
            'session_number': session_num,
            'note_date':      note_date,
            'content':        content,
            'note_tag':       note_tag,
        })
    return results


# ---------------------------------------------------------------------------
# Google API helpers
# ---------------------------------------------------------------------------

def _docs_service(creds):
    return build('docs', 'v1', credentials=creds, cache_discovery=False)


def _drive_service(creds):
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def create_patient_doc(creds, patient_name):
    """
    Create a new Google Doc with a bilingual treatment-log template.
    Returns the doc_id (string).
    """
    svc = _docs_service(creds)
    doc = svc.documents().create(body={
        'title': f'Treatment Log \u2014 {patient_name}'
    }).execute()
    doc_id = doc['documentId']

    template = (
        f"Treatment Log \u2014 {patient_name}\n\n"
        "Add sessions using either format below.\n\n"
        "SESSION #1 | YYYY-MM-DD [note:new]\n"
        "Write session notes here\u2026\n\n"
        "\u05e4\u05d2\u05d9\u05e9\u05d4 #1 | YYYY-MM-DD [note:new]\n"
        "\u05db\u05ea\u05d5\u05d1 \u05d4\u05e2\u05e8\u05d5\u05ea \u05db\u05d0\u05df\u2026\n"
    )
    svc.documents().batchUpdate(documentId=doc_id, body={
        'requests': [{'insertText': {'location': {'index': 1}, 'text': template}}]
    }).execute()
    return doc_id


def read_doc_text(creds, doc_id):
    """Return the full plain text of a Google Doc."""
    svc = _docs_service(creds)
    doc = svc.documents().get(documentId=doc_id).execute()
    parts = []
    for el in doc.get('body', {}).get('content', []):
        for pe in el.get('paragraph', {}).get('elements', []):
            parts.append(pe.get('textRun', {}).get('content', ''))
    return ''.join(parts)


def stamp_note_id_in_doc(creds, doc_id, new_id):
    """
    Replace the first occurrence of '[note:new]' in the doc with '[note:id=N]'.
    Called immediately after inserting a new note row into the DB.
    """
    new_tag = f'[note:id={new_id}]'
    svc = _docs_service(creds)
    svc.documents().batchUpdate(documentId=doc_id, body={
        'requests': [{'replaceAllText': {
            'containsText': {'text': '[note:new]', 'matchCase': True},
            'replaceText': new_tag,
        }}]
    }).execute()


def register_drive_watch(creds, doc_id, webhook_url):
    """
    Register a Drive push-notification channel on the given file.
    Returns (channel_id, expiry_iso_string).
    Channel expires in 7 days; callers should refresh periodically.
    """
    svc = _drive_service(creds)
    channel_id = str(uuid.uuid4())
    expiry_ms  = int((datetime.now(timezone.utc).timestamp() + 7 * 86400) * 1000)
    resp = svc.files().watch(fileId=doc_id, body={
        'id':         channel_id,
        'type':       'web_hook',
        'address':    webhook_url,
        'expiration': expiry_ms,
    }).execute()
    expiry_iso = datetime.fromtimestamp(
        int(resp['expiration']) / 1000, tz=timezone.utc
    ).isoformat()
    return channel_id, expiry_iso
