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

Parser format (Hebrew):
    פגישה #1 | 2026-04-01 [note:new]
    תוכן חופשי…

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
# Matches:  SESSION #3 | 2026-04-01 [note:new]
#           פגישה #3 | 2026-04-01 [note:id=7]
# ---------------------------------------------------------------------------
_SESSION_RE = re.compile(
    r'^(?:SESSION|פגישה)\s*#(\d+)\s*\|\s*(\d{4}-\d{2}-\d{2})'
    r'(?:\s*(\[note:[^\]]+\]))?',
    re.MULTILINE | re.IGNORECASE,
)

_NOTE_ID_RE = re.compile(r'\[note:id=(\d+)\]')


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
        note_date   = m.group(2)
        raw_tag     = (m.group(3) or '').strip()

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
