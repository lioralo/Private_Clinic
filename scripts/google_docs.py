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
#   SESSION 10: 2026-04-01                    (English, colon, large number)
#   פגישה #3 | 2026-04-01 [note:id=7]        (Hebrew, ISO date, pipe)
#   פגישה 1- 05/08/25                         (Hebrew, DD/MM/YY, dash)
#   פגישה 10- 05/08/2025                      (Hebrew, DD/MM/YYYY, dash, large number)
#   פגישה #10- 05/06/25                       (Hebrew, optional #, dash, large number)
#   ~פגישה 20- 23/02/26                       (Hebrew, leading tilde, large number)
#   מפגש 3 | 2026-04-01 [note:new]            (Hebrew alternative label)
#   מפגש 10- 05/08/25                          (Hebrew alternative, dash, large number)
#   מפגש 20 | 05/08/25                         (Hebrew, pipe with slash date)
#   SESSION 1: 2026-04-01                      (English, colon separator)
#   פגישה 10: 05/08/25                         (Hebrew, colon separator)
#   מפגש 1 05/08/25                             (Hebrew, space separator)
#   SESSION #1 - 2026-04-01                    (English, hash + dash)
# ---------------------------------------------------------------------------
_SESSION_RE = re.compile(
    r'^\s*[~•*\-–—]?\s*(?P<label>SESSION|פגישה|מפגש|ישיבה)\s*(?:#\s*)?'
    r'(?P<number>\d+)\s*'
    r'(?:'
        r'[:|\-־–—]\s*(?P<iso>\d{4}-\d{2}-\d{2})'
        r'|'
        r'[:|\-־–—]\s*(?P<slash>\d{1,2}/\d{1,2}/\d{2,4})'
        r'|'
        r'\s+(?P<space_date>\d{1,2}/\d{1,2}/\d{2,4})'
        r')?'
    r'(?:\s*(?P<tag>\[note:[^\]]+\]))?\s*$',
    re.MULTILINE | re.IGNORECASE,
)

_NOTE_ID_RE = re.compile(r'\[note:id=(\d+)\]')


def _extract_name_and_note(text):
    """Split 'Name - inline note' into (name, note).
    Handles separators with or without leading space (real-world doc format)."""
    t = (text or '').strip()
    m = re.match(r'^(.*?)\s*[-–—:]\s+(.+)$', t, re.DOTALL)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return t, ''


def _split_named_entries(text):
    """Split a participant/missing line into logical entries.

    Semicolons are the preferred delimiter for multiple name+note entries on one line.
    Commas remain supported for plain name lists with no inline notes.
    """
    raw_text = (text or '').strip()
    if not raw_text:
        return []
    if ';' in raw_text:
        return [part.strip() for part in raw_text.split(';') if part.strip()]
    return [raw_text]


def _split_hebrew_group_sections(block_text):
    """Parse a group-session block into participants, missing, and content sections.

    Returns:
        participants – list of names (backward-compatible)
        missing      – list of names (backward-compatible)
        content      – plain-text string
        participant_entries – list of {'name': str, 'note': str}
        missing_entries – list of {'name': str, 'note': str}
    """
    participants = []
    missing = []
    participant_entries = []
    missing_entries = []
    content_parts = []

    def _normalized_section_header(raw_line):
        normalized = (raw_line or '').strip()
        normalized = re.sub(r'^[|#>*\-–—\s]+', '', normalized)
        normalized = normalized.rstrip(':.-–—*_`').strip().lower()
        return normalized

    current_section = None
    for raw_line in (block_text or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized_header = _normalized_section_header(line)
        if normalized_header in ('משתתפים', 'participants'):
            current_section = 'participants'
            continue
        if normalized_header in ('חסרים', 'missing'):
            current_section = 'missing'
            continue
        if normalized_header in ('תוכן', 'content'):
            current_section = 'content'
            continue

        if current_section == 'participants':
            line_no_bullet = line.lstrip('-•*').strip()
            for raw_entry in _split_named_entries(line_no_bullet):
                if re.search(r'\s*[-–—:]\s+', raw_entry):
                    name, note = _extract_name_and_note(raw_entry)
                    if name:
                        participants.append(name)
                        participant_entries.append({'name': name, 'note': note})
                    continue

                # May be comma-separated or ו-separated names with no inline note.
                for token in re.split(r'[,]', raw_entry):
                    cleaned = token.strip().strip('-').strip()
                    if not cleaned:
                        continue
                    split_by_and = re.split(r'\s+ו(?=[\u0590-\u05FFA-Za-z])', cleaned)
                    if len(split_by_and) > 1:
                        for part in split_by_and:
                            item = part.strip().strip('-').strip()
                            if item:
                                participants.append(item)
                                participant_entries.append({'name': item, 'note': ''})
                    else:
                        participants.append(cleaned)
                        participant_entries.append({'name': cleaned, 'note': ''})
            continue

        if current_section == 'missing':
            cleaned = line.lstrip('-•*').strip()
            for raw_entry in _split_named_entries(cleaned):
                name, note = _extract_name_and_note(raw_entry)
                if name:
                    missing.append(name)
                    missing_entries.append({'name': name, 'note': note})
            continue

        if current_section == 'content':
            content_parts.append(line)

    content = '\n'.join(content_parts).strip()
    if content:
        cleaned_content_lines = []
        for raw_line in content.splitlines():
            if _normalized_section_header(raw_line) in ('משתתפים', 'participants', 'חסרים', 'missing', 'תוכן', 'content'):
                continue
            cleaned_content_lines.append(raw_line)
        content = '\n'.join(cleaned_content_lines).strip()

    has_structured_headers = any(
        marker in (block_text or '').lower()
        for marker in ('משתתפים', 'חסרים', 'תוכן', 'participants', 'missing', 'content')
    )
    has_content_header = any(
        _normalized_section_header(raw_line) in ('תוכן', 'content')
        for raw_line in (block_text or '').splitlines()
    )

    if has_structured_headers and not has_content_header:
        content = ''
    elif not has_structured_headers:
        content = (block_text or '').strip()

    return participants, missing, content, participant_entries, missing_entries


def _parse_date(iso_group, slash_group):
    """Return a YYYY-MM-DD string from whichever capture group matched."""
    if iso_group:
        return iso_group  # already ISO
    if not slash_group:
        return None
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
        number_group = (m.group('number') or '').strip()
        session_num = int(number_group) if number_group.isdigit() else None
        note_date = _parse_date(m.group('iso'), m.group('slash') or m.group('space_date'))
        raw_tag = (m.group('tag') or '').strip()

        raw_header = (text[m.start():m.end()] or '').strip()
        raw_header = re.sub(r'\s*\[note:[^\]]+\]\s*$', '', raw_header).strip()
        meeting_title = re.sub(r'\s+', ' ', raw_header)

        block_start = m.end()
        block_end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block_text  = text[block_start:block_end].strip()
        participants, missing, content, participant_entries, missing_entries = _split_hebrew_group_sections(block_text)

        if '[note:new]' in raw_tag:
            note_tag = 'new'
        else:
            id_match = _NOTE_ID_RE.search(raw_tag)
            note_tag = int(id_match.group(1)) if id_match else 'new'

        results.append({
            'session_number': session_num,
            'note_date':      note_date,
            'content':        content,
            'participants':   participants,
            'missing':        missing,
            'participant_entries': participant_entries,
            'missing_entries': missing_entries,
            'meeting_title':  meeting_title,
            'note_tag':       note_tag,
            'raw_header':     m.group(0).strip(),
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


def _iter_text_runs(content_elements):
    """Yield (doc_start_index, text) for every textRun in document order,
    recursing into table cells. ``doc_start_index`` is the Google Docs
    character index of the first character of the run."""
    for element in content_elements or []:
        if not isinstance(element, dict):
            continue
        paragraph = element.get('paragraph')
        if paragraph:
            for pe in paragraph.get('elements', []):
                text_run = pe.get('textRun')
                if not text_run:
                    continue
                start_index = pe.get('startIndex')
                if start_index is None:
                    continue
                yield start_index, text_run.get('content', '')
        table = element.get('table')
        if table:
            for row in table.get('tableRows', []):
                for cell in row.get('tableCells', []):
                    yield from _iter_text_runs(cell.get('content', []))


def _build_doc_index_map(content_elements):
    """Return ``(full_text, index_map)`` for a document body.

    ``full_text`` is the concatenation of every textRun (identical to what
    :func:`read_doc_text` returns) and ``index_map[i]`` is the Google Docs
    character index of ``full_text[i]``, so an offset located in ``full_text``
    can be translated back to a concrete edit location in the document.
    """
    chars = []
    index_map = []
    for start_index, text in _iter_text_runs(content_elements):
        for offset, ch in enumerate(text):
            chars.append(ch)
            index_map.append(start_index + offset)
    return ''.join(chars), index_map


def _normalize_header_ws(value):
    """Collapse all whitespace to single spaces for tolerant header matching."""
    return re.sub(r'\s+', ' ', (value or '')).strip()


def _locate_session_tag_edit(full_text, session_header):
    """Decide where/how to write a note-id tag for a specific session header.

    Returns one of:
        None              – the header could not be located (caller falls back)
        ('noop', None)    – the header already carries a [note:id=...] tag
        ('replace', pos)  – replace the [note:new] marker at offset ``pos``
        ('append', pos)   – append the id tag at offset ``pos`` (untagged header)

    Offsets are positions within ``full_text``.
    """
    target = _normalize_header_ws(session_header)
    if not target:
        return None
    for match in _SESSION_RE.finditer(full_text):
        if _normalize_header_ws(match.group(0)) != target:
            continue
        line_start = full_text.rfind('\n', 0, match.start()) + 1
        line_end = full_text.find('\n', match.start())
        if line_end == -1:
            line_end = len(full_text)
        existing_new = full_text.find('[note:new]', line_start, line_end)
        if existing_new != -1:
            return ('replace', existing_new)
        if _NOTE_ID_RE.search(full_text[line_start:line_end]):
            return ('noop', None)
        append_pos = line_end
        while append_pos > line_start and full_text[append_pos - 1] in ' \t\r':
            append_pos -= 1
        return ('append', append_pos)
    return None


def stamp_note_id_in_doc(creds, doc_id, new_id, session_header=None):
    """Stamp the session identified by ``session_header`` with ``[note:id=N]``.

    The tag is written to the SPECIFIC session line rather than merely the first
    ``[note:new]`` in the document, so every meeting is stamped exactly once and
    is never re-imported on the next sync. If that header already carries a
    ``[note:new]`` marker it is replaced; an untagged header gets the tag
    appended; and a header already carrying ``[note:id=...]`` is left untouched.
    When ``session_header`` is missing or cannot be located, the legacy
    behaviour (stamp the first ``[note:new]`` in the document) is used.
    """
    new_tag = f'[note:id={new_id}]'
    svc = _docs_service(creds)

    doc = svc.documents().get(documentId=doc_id).execute()
    content = doc.get('body', {}).get('content', [])
    full_text, index_map = _build_doc_index_map(content)

    edit = _locate_session_tag_edit(full_text, session_header)
    if edit is None:
        first_new = full_text.find('[note:new]')
        if first_new == -1:
            return
        edit = ('replace', first_new)

    mode, text_pos = edit
    if mode == 'noop':
        return

    if text_pos < len(index_map):
        doc_index = index_map[text_pos]
    elif index_map:
        doc_index = index_map[-1] + 1
    else:
        return

    requests = []
    if mode == 'replace':
        requests.append({'deleteContentRange': {'range': {
            'startIndex': doc_index,
            'endIndex': doc_index + len('[note:new]'),
        }}})
        requests.append({'insertText': {
            'location': {'index': doc_index},
            'text': new_tag,
        }})
    else:  # append
        requests.append({'insertText': {
            'location': {'index': doc_index},
            'text': ' ' + new_tag,
        }})
    svc.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()


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
