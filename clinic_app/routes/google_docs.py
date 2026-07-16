import os
import re
import json
from functools import wraps

from flask import (
    Blueprint, flash, jsonify, redirect, request, session, current_app,
)
from flask_login import current_user, login_required

from clinic_app.models import get_db


google_docs_bp = Blueprint('google_docs', __name__)


def _login_json_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _google_docs_dependency_error():
    from app import gdocs, gcal
    issues = []
    if not gdocs or not bool(getattr(gdocs, 'GDOCS_LIBS_AVAILABLE', True)):
        detail = getattr(gdocs, 'GDOCS_LIBS_ERROR', None) if gdocs else None
        issues.append(detail or 'google_docs module not available')
    if not gcal or not bool(getattr(gcal, 'GOOGLE_LIBS_AVAILABLE', True)):
        detail = getattr(gcal, 'GOOGLE_LIBS_ERROR', None) if gcal else None
        issues.append(detail or 'Google libraries not installed')
    if not issues:
        return None
    
    # Improved error message for better user guidance
    error_message = 'Google integration dependencies are unavailable: '
    error_message += '; '.join(str(item) for item in issues)
    error_message += '. To fix this, please run the following command in your terminal: pip install -r requirements.txt'
    return error_message


def _extract_google_doc_id(raw_value):
    raw_text = (raw_value or '').strip()
    if not raw_text:
        return None
    match = re.search(r'/document/d/([a-zA-Z0-9_-]+)', raw_text)
    return match.group(1) if match else raw_text


def _extract_google_sheet_id(raw_value):
    raw_text = (raw_value or '').strip()
    if not raw_text:
        return None
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', raw_text)
    return match.group(1) if match else raw_text


def _extract_google_activation_url(error_text):
    text = str(error_text or '')
    if not text:
        return None
    for pattern in [
        r'https://console\.developers\.google\.com/apis/api/sheets\.googleapis\.com/overview\?project=\d+',
        r'https://console\.cloud\.google\.com/apis/library/sheets\.googleapis\.com\?project=[^\s"\']+'
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _friendly_google_sheets_error(error_text):
    text = str(error_text or '')
    if not text:
        return None
    activation_url = _extract_google_activation_url(text)
    if 'SERVICE_DISABLED' in text or 'Google Sheets API has not been used in project' in text:
        project_match = re.search(r'project\s+(\d+)', text)
        project_hint = f" (project {project_match.group(1)})" if project_match else ''
        return (
            'Google Sheets API is disabled for the connected Google Cloud project'
            f'{project_hint}. Enable Google Sheets API and retry.',
            activation_url,
        )
    if 'insufficient authentication scopes' in text.lower() or 'missing Sheets permission' in text:
        return (
            'Google token is missing Sheets permission. Reconnect Google in Admin Profile and approve Sheets access.',
            activation_url,
        )
    return text, activation_url


def _google_sheets_dependency_error():
    from app import gcal
    if not gcal or not bool(getattr(gcal, 'GOOGLE_LIBS_AVAILABLE', False)):
        return 'Google Sheets integration is unavailable: Google libraries are not installed.'
    if not hasattr(gcal, 'build'):
        return 'Google Sheets integration is unavailable: google-api-python-client build helper is missing.'
    return None


def _get_google_sheets_credentials(db):
    dependency_error = _google_sheets_dependency_error()
    if dependency_error:
        return None, dependency_error
    from app import gcal
    creds = gcal.load_credentials(db)
    if not creds:
        return None, 'Google not connected — connect via Admin Profile first'
    try:
        creds = gcal._refresh_and_save(db, creds)
    except Exception as exc:
        return None, str(exc)
    has_scopes = getattr(creds, 'has_scopes', None)
    required_scopes = ['https://www.googleapis.com/auth/spreadsheets']
    if callable(has_scopes) and not creds.has_scopes(required_scopes):
        return None, 'Google token is missing Sheets permission. Reconnect Google integration from Admin Profile.'
    return creds, None


def _list_questionnaire_tabs(db):
    from app import get_site_settings
    from app import gcal
    settings = get_site_settings(db)
    source_url = (settings.get('questionnaires_source_sheet_url') or '').strip()
    source_sheet_id = _extract_google_sheet_id(source_url)
    if not source_sheet_id:
        return [], 'Please set the questionnaires Google Sheets file link in Admin Profile first.'
    creds, cred_err = _get_google_sheets_credentials(db)
    if cred_err:
        return [], cred_err
    try:
        sheets_service = gcal.build('sheets', 'v4', credentials=creds, cache_discovery=False)
        spreadsheet = sheets_service.spreadsheets().get(
            spreadsheetId=source_sheet_id,
            fields='sheets(properties(sheetId,title,hidden))'
        ).execute()
    except Exception as exc:
        friendly_error, _activation_url = _friendly_google_sheets_error(exc)
        return [], friendly_error
    tabs = []
    for item in spreadsheet.get('sheets', []):
        props = item.get('properties') or {}
        title = (props.get('title') or '').strip()
        if not title or props.get('hidden'):
            continue
        tabs.append({'sheet_id': props.get('sheetId'), 'title': title})
    return tabs, None


def _list_spreadsheet_tab_titles(db, spreadsheet_id):
    parsed_sheet_id = _extract_google_sheet_id(spreadsheet_id)
    if not parsed_sheet_id:
        return [], 'Missing spreadsheet id.'
    creds, cred_err = _get_google_sheets_credentials(db)
    if cred_err:
        return [], cred_err
    from app import gcal
    try:
        sheets_service = gcal.build('sheets', 'v4', credentials=creds, cache_discovery=False)
        spreadsheet = sheets_service.spreadsheets().get(
            spreadsheetId=parsed_sheet_id,
            fields='sheets(properties(title,hidden))'
        ).execute()
    except Exception as exc:
        friendly_error, _activation_url = _friendly_google_sheets_error(exc)
        return [], friendly_error
    titles = []
    for item in spreadsheet.get('sheets', []):
        props = item.get('properties') or {}
        title = (props.get('title') or '').strip()
        if not title or props.get('hidden'):
            continue
        titles.append(title)
    return titles, None


def _create_diagnosee_questionnaires_sheet(db, diagnosee_name, selected_titles):
    tabs, tabs_err = _list_questionnaire_tabs(db)
    if tabs_err:
        return None, tabs_err
    selected_clean = [str(item).strip() for item in (selected_titles or []) if str(item).strip()]
    if not selected_clean:
        return None, 'No questionnaires selected.'
    title_to_sheet = {str(item['title']).strip(): item for item in tabs}
    missing = [name for name in selected_clean if name not in title_to_sheet]
    if missing:
        return None, 'Selected questionnaires were not found in source sheet: ' + ', '.join(missing)
    from app import get_site_settings
    from app import gcal
    settings = get_site_settings(db)
    source_sheet_id = _extract_google_sheet_id(settings.get('questionnaires_source_sheet_url'))
    creds, cred_err = _get_google_sheets_credentials(db)
    if cred_err:
        return None, cred_err
    try:
        sheets_service = gcal.build('sheets', 'v4', credentials=creds, cache_discovery=False)
        spreadsheet_title = f'{diagnosee_name} questionnaires'
        created = sheets_service.spreadsheets().create(
            body={'properties': {'title': spreadsheet_title}},
            fields='spreadsheetId,spreadsheetUrl,sheets(properties(sheetId,title))'
        ).execute()
        destination_id = created.get('spreadsheetId')
        destination_url = created.get('spreadsheetUrl') or f'https://docs.google.com/spreadsheets/d/{destination_id}/edit'
        copied_any = False
        for tab_name in selected_clean:
            source_sheet_tab = title_to_sheet.get(tab_name)
            source_tab_id = source_sheet_tab.get('sheet_id') if source_sheet_tab else None
            if source_tab_id is None:
                continue
            copied_result = sheets_service.spreadsheets().sheets().copyTo(
                spreadsheetId=source_sheet_id,
                sheetId=source_tab_id,
                body={'destinationSpreadsheetId': destination_id}
            ).execute()
            copied_props = copied_result.get('properties') or {}
            copied_sheet_id = copied_props.get('sheetId')
            copied_title = (copied_props.get('title') or '').strip()
            if copied_sheet_id is not None and copied_title != tab_name:
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=destination_id,
                    body={
                        'requests': [{
                            'updateSheetProperties': {
                                'properties': {'sheetId': copied_sheet_id, 'title': tab_name},
                                'fields': 'title',
                            }
                        }]
                    }
                ).execute()
            copied_any = True
        if copied_any:
            destination_meta = sheets_service.spreadsheets().get(
                spreadsheetId=destination_id,
                fields='sheets(properties(sheetId,title))'
            ).execute()
            for sheet_item in destination_meta.get('sheets', []):
                props = sheet_item.get('properties') or {}
                if (props.get('title') or '').strip() == 'Sheet1':
                    sheets_service.spreadsheets().batchUpdate(
                        spreadsheetId=destination_id,
                        body={'requests': [{'deleteSheet': {'sheetId': props.get('sheetId')}}]}
                    ).execute()
                    break
        return {
            'spreadsheet_id': destination_id,
            'spreadsheet_url': destination_url,
            'selected_titles': selected_clean,
        }, None
    except Exception as exc:
        return None, str(exc)


def _copy_questionnaire_tabs_to_spreadsheet(db, destination_sheet_id, selected_titles):
    tabs, tabs_err = _list_questionnaire_tabs(db)
    if tabs_err:
        return None, tabs_err
    parsed_destination_id = _extract_google_sheet_id(destination_sheet_id)
    if not parsed_destination_id:
        return None, 'Missing destination questionnaires file id.'
    selected_clean = [str(item).strip() for item in (selected_titles or []) if str(item).strip()]
    if not selected_clean:
        return None, 'No questionnaires selected.'
    title_to_sheet = {str(item['title']).strip(): item for item in tabs}
    missing = [name for name in selected_clean if name not in title_to_sheet]
    from app import get_site_settings
    from app import gcal
    settings = get_site_settings(db)
    source_sheet_id = _extract_google_sheet_id(settings.get('questionnaires_source_sheet_url'))
    creds, cred_err = _get_google_sheets_credentials(db)
    if cred_err:
        return None, cred_err
    try:
        sheets_service = gcal.build('sheets', 'v4', credentials=creds, cache_discovery=False)
        destination_meta = sheets_service.spreadsheets().get(
            spreadsheetId=parsed_destination_id,
            fields='sheets(properties(title,hidden))'
        ).execute()
        existing_titles = {
            (sheet.get('properties') or {}).get('title', '').strip()
            for sheet in destination_meta.get('sheets', [])
            if (sheet.get('properties') or {}).get('title') and not (sheet.get('properties') or {}).get('hidden')
        }
        copied = []
        skipped_existing = []
        for tab_name in selected_clean:
            if tab_name in existing_titles:
                skipped_existing.append(tab_name)
                continue
            source_sheet_tab = title_to_sheet.get(tab_name)
            source_tab_id = source_sheet_tab.get('sheet_id') if source_sheet_tab else None
            if source_tab_id is None:
                continue
            copied_result = sheets_service.spreadsheets().sheets().copyTo(
                spreadsheetId=source_sheet_id,
                sheetId=source_tab_id,
                body={'destinationSpreadsheetId': parsed_destination_id}
            ).execute()
            copied_props = copied_result.get('properties') or {}
            copied_sheet_id = copied_props.get('sheetId')
            copied_title = (copied_props.get('title') or '').strip()
            if copied_sheet_id is not None and copied_title != tab_name:
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=parsed_destination_id,
                    body={
                        'requests': [{
                            'updateSheetProperties': {
                                'properties': {'sheetId': copied_sheet_id, 'title': tab_name},
                                'fields': 'title',
                            }
                        }]
                    }
                ).execute()
            copied.append(tab_name)
        return {
            'copied_titles': copied,
            'skipped_existing_titles': skipped_existing,
            'missing_titles': missing,
        }, None
    except Exception as exc:
        return None, str(exc)


def _pull_gdoc_notes(db, patient):
    from app import gdocs, gcal
    from app import _normalize_session_number
    if not gdocs:
        return 0, 'google_docs module not available'
    if not gcal:
        return 0, 'Google libraries not installed'
    creds = gcal.load_credentials(db)
    if not creds:
        return 0, 'Google not connected — connect via Admin Profile first'
    try:
        creds = gcal._refresh_and_save(db, creds)
        doc_text = gdocs.read_doc_text(creds, patient['gdoc_id'])
        parsed_notes = gdocs.parse_doc_into_notes(doc_text)
    except Exception as exc:
        return 0, str(exc)
    latest_note = db.execute(
        '''SELECT patient_appearance, behavior_checklist, mood_summary, behavior_notes
           FROM notes
           WHERE patient_id = ?
           ORDER BY COALESCE(note_date, date(created_at)) DESC, created_at DESC, id DESC
           LIMIT 1''',
        (patient['id'],)
    ).fetchone()
    carried_fields = {
        'patient_appearance': (latest_note['patient_appearance'] if latest_note else None),
        'behavior_checklist': (latest_note['behavior_checklist'] if latest_note else None),
        'mood_summary': (latest_note['mood_summary'] if latest_note else None),
        'behavior_notes': (latest_note['behavior_notes'] if latest_note else None),
    }
    synced = 0
    try:
        for item in parsed_notes:
            session_number = _normalize_session_number(item.get('session_number'))
            note_date = (item.get('note_date') or '').strip() or None
            content = (item.get('content') or '').strip()
            note_tag = item.get('note_tag')
            if not content:
                continue
            if isinstance(note_tag, int):
                existing = db.execute(
                    'SELECT id FROM notes WHERE id = ? AND patient_id = ?',
                    (note_tag, patient['id'])
                ).fetchone()
                if not existing:
                    return 0, f'Google Doc references note #{note_tag}, but it was not found for this patient.'
                db.execute(
                    '''UPDATE notes
                       SET session_number = ?, note_date = ?, content = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND patient_id = ?''',
                    (session_number, note_date, content, note_tag, patient['id'])
                )
                synced += 1
                continue
            duplicate = db.execute(
                '''SELECT id FROM notes
                   WHERE patient_id = ?
                     AND COALESCE(session_number, '') = COALESCE(?, '')
                     AND COALESCE(note_date, '') = COALESCE(?, '')
                     AND content = ?
                   ORDER BY id DESC
                   LIMIT 1''',
                (patient['id'], session_number, note_date, content)
            ).fetchone()
            if duplicate:
                gdocs.stamp_note_id_in_doc(creds, patient['gdoc_id'], duplicate['id'], session_header=item.get('raw_header'))
                synced += 1
                continue
            cursor = db.execute(
                '''INSERT INTO notes (
                       patient_id, session_number, note_date, content,
                       patient_appearance, behavior_checklist, mood_summary, behavior_notes
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    patient['id'],
                    session_number,
                    note_date,
                    content,
                    carried_fields['patient_appearance'],
                    carried_fields['behavior_checklist'],
                    carried_fields['mood_summary'],
                    carried_fields['behavior_notes'],
                )
            )
            new_note_id = cursor.lastrowid
            gdocs.stamp_note_id_in_doc(creds, patient['gdoc_id'], new_note_id, session_header=item.get('raw_header'))
            synced += 1
        db.commit()
    except Exception as exc:
        db.rollback()
        return 0, str(exc)
    return synced, None


def _pull_group_gdoc_notes(db, group):
    from app import gdocs, gcal
    from app import _normalize_session_number
    dependency_error = _google_docs_dependency_error()
    if dependency_error:
        return 0, dependency_error
    if not group or not group['gdoc_id']:
        return 0, 'No Google Doc linked'
    creds = gcal.load_credentials(db)
    if not creds:
        return 0, 'Google not connected — connect via Admin Profile first'
    try:
        creds = gcal._refresh_and_save(db, creds)
        doc_text = gdocs.read_doc_text(creds, group['gdoc_id']) or ''
        parser = getattr(gdocs, 'parse_doc_into_notes', None)
        parsed_notes = parser(doc_text) if callable(parser) else []
    except Exception as exc:
        return 0, str(exc)

    def _normalize_person_name(value):
        text = (value or '').strip().lower()
        text = re.sub(r'\s+', ' ', text)
        text = text.replace(',', ' ').replace('.', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _normalize_meeting_title(value):
        text = (value or '').strip().lower()
        text = re.sub(r'\s+', ' ', text)
        text = text.replace('—', '-').replace('–', '-').replace('־', '-')
        text = re.sub(r'\s*#\s*', ' # ', text)
        text = re.sub(r'\s*-\s*', ' - ', text)
        return re.sub(r'\s+', ' ', text).strip()

    def _extract_missing_reason(raw_entry, matched_name):
        entry = (raw_entry or '').strip()
        if not entry:
            return ''
        if matched_name:
            pattern = re.compile(rf'^\s*{re.escape(matched_name)}\s*[-—–:]+\s*(.*)$')
            match = pattern.match(entry)
            if match:
                return (match.group(1) or '').strip()
            if entry.startswith(matched_name):
                return entry[len(matched_name):].strip(' -—–:\t')
        return entry

    def _build_structured_summary(parsed_item):
        content_body = (parsed_item.get('content') or '').strip()
        return content_body

    def _upsert_patient_group_note(patient_id, session_id, note_date, session_time, note_content, is_missed, missed_reason, group_name, session_title, session_summary=None):
        marker = f'[Group Session #{session_id}]'
        session_date_label = note_date or ''
        session_time_label = session_time or ''
        lines = [marker, 'תיעוד מקבוצת טיפול']
        if group_name:
            lines.append(f'קבוצה: {group_name}')
        if session_title:
            lines.append(f'מפגש: {session_title}')
        if session_date_label and session_time_label:
            lines.append(f'מועד: {session_date_label} {session_time_label}')
        elif session_date_label:
            lines.append(f'מועד: {session_date_label}')
        elif session_time_label:
            lines.append(f'שעה: {session_time_label}')
        if is_missed:
            lines.append('סטטוס: חסר')
            if missed_reason:
                lines.append(f'סיבת היעדרות: {missed_reason}')
            if note_content:
                lines.append(f'הערה: {note_content}')
        else:
            lines.append('סטטוס: נוכח')
            if note_content:
                lines.append(f'הערה: {note_content}')
        if session_summary and session_summary.strip():
            lines.append('')
            lines.append('תקציר הפגישה:')
            lines.append(session_summary.strip())
        body = '\n'.join(line for line in lines if line).strip()
        existing = db.execute(
            '''SELECT id FROM notes
               WHERE patient_id = ?
                 AND COALESCE(note_date, '') = COALESCE(?, '')
                 AND content LIKE ?
               ORDER BY id DESC LIMIT 1''',
            (patient_id, note_date, f'{marker}%')
        ).fetchone()
        if existing:
            db.execute(
                '''UPDATE notes SET note_date = ?, content = ?, is_missed_meeting = ?, missed_reason = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?''',
                (note_date, body, 1 if is_missed else 0, missed_reason or None, existing['id'])
            )
        else:
            db.execute(
                '''INSERT INTO notes (patient_id, note_date, content, is_missed_meeting, missed_reason)
                   VALUES (?, ?, ?, ?, ?)''',
                (patient_id, note_date, body, 1 if is_missed else 0, missed_reason or None)
            )

    group_name = group['name'] if 'name' in group.keys() else ''

    def _apply_attendance_from_doc(session_id, participants, missing_entries, session_date=None, session_time=None, session_title=None, session_summary=None):
        if not session_id:
            return
        rows = db.execute('''
            SELECT DISTINCT p.id AS patient_id, p.name AS patient_name
            FROM group_member_history h
            JOIN patients p ON p.id = h.patient_id
            WHERE h.group_id = ?
              AND COALESCE(p.is_deleted, 0) = 0
        ''', (group['id'],)).fetchall()
        name_map = {}
        for row in rows:
            normalized = _normalize_person_name(row['patient_name'])
            if normalized and normalized not in name_map:
                name_map[normalized] = {
                    'patient_id': int(row['patient_id']),
                    'patient_name': row['patient_name'],
                }

        def find_member(raw_name):
            normalized = _normalize_person_name(raw_name)
            if normalized in name_map:
                return name_map[normalized]
            for key, value in name_map.items():
                if normalized and (key.startswith(normalized) or normalized.startswith(key)):
                    return value
            return None

        for entry in participants:
            raw_name = entry['name'] if isinstance(entry, dict) else entry
            inline_note = entry.get('note', '') if isinstance(entry, dict) else ''
            matched = find_member(raw_name)
            if not matched:
                continue
            db.execute('''
                INSERT INTO group_session_attendance (session_id, patient_id, attendance_status, absence_reason, notified_on_time, attendance_note, updated_at)
                VALUES (?, ?, 'present', NULL, 0, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id, patient_id)
                DO UPDATE SET attendance_status = 'present',
                              absence_reason = NULL,
                              attendance_note = excluded.attendance_note,
                              notified_on_time = 0,
                              updated_at = CURRENT_TIMESTAMP
            ''', (session_id, matched['patient_id'], inline_note or None))
            _upsert_patient_group_note(
                matched['patient_id'], session_id, session_date, session_time, inline_note,
                is_missed=False, missed_reason=None, group_name=group_name, session_title=session_title,
                session_summary=session_summary
            )

        for entry in missing_entries:
            raw_entry = entry['name'] if isinstance(entry, dict) else entry
            absence_note = entry.get('note', '') if isinstance(entry, dict) else ''
            matched = find_member(raw_entry)
            if not matched:
                continue
            reason = absence_note or _extract_missing_reason(raw_entry if not isinstance(entry, dict) else '', matched['patient_name'])
            db.execute('''
                INSERT INTO group_session_attendance (session_id, patient_id, attendance_status, absence_reason, notified_on_time, attendance_note, updated_at)
                VALUES (?, ?, 'missed', ?, 0, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id, patient_id)
                DO UPDATE SET attendance_status = 'missed',
                              absence_reason = excluded.absence_reason,
                              notified_on_time = 0,
                              updated_at = CURRENT_TIMESTAMP
            ''', (session_id, matched['patient_id'], reason or None))
            _upsert_patient_group_note(
                matched['patient_id'], session_id, session_date, session_time, absence_note or reason,
                is_missed=True, missed_reason=reason or None, group_name=group_name, session_title=session_title,
                session_summary=session_summary
            )

    synced = 0
    try:
        ordered_sessions = db.execute('''
            SELECT id, session_date, session_time, title, session_summary
            FROM group_sessions
            WHERE group_id = ?
            ORDER BY session_date ASC, session_time ASC, id ASC
        ''', (group['id'],)).fetchall()
        title_session_map = {}
        def _title_key_no_date(title_value):
            t = _normalize_meeting_title(title_value)
            t = re.sub(r'\s*[-:]\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$', '', t).strip()
            t = re.sub(r'\s*\|\s*\d{4}-\d{2}-\d{2}\s*$', '', t).strip()
            return t
        for session_row in ordered_sessions:
            lookup_title = _title_key_no_date(session_row['title'] if 'title' in session_row.keys() else None)
            if lookup_title and lookup_title not in title_session_map:
                title_session_map[lookup_title] = session_row

        for item in parsed_notes:
            content = (item.get('content') or '').strip()
            participants = item.get('participants') or []
            missing_entries = item.get('missing') or []
            participant_entries = item.get('participant_entries') or []
            missing_note_entries = item.get('missing_entries') or []
            meeting_title = (item.get('meeting_title') or '').strip()
            note_date = (item.get('note_date') or '').strip() or None
            session_number = _normalize_session_number(item.get('session_number'))
            session_number_index = int(session_number) if isinstance(session_number, str) and session_number.isdigit() else None
            note_tag = item.get('note_tag')
            structured_summary = _build_structured_summary(item)
            if not content and not structured_summary:
                continue

            if not note_date:
                continue

            target = None
            if isinstance(note_tag, int):
                target = db.execute(
                    'SELECT id, session_date, session_time, title, session_summary FROM group_sessions WHERE id = ? AND group_id = ?',
                    (note_tag, group['id'])
                ).fetchone()

            if target is None and meeting_title:
                target = title_session_map.get(_title_key_no_date(meeting_title))

            if target is None and note_date:
                target = db.execute('''
                    SELECT id, session_date, session_time, title, session_summary
                    FROM group_sessions
                    WHERE group_id = ? AND session_date = ?
                    ORDER BY session_time ASC, id ASC
                    LIMIT 1
                ''', (group['id'], note_date)).fetchone()

            if target is None and session_number_index and session_number_index <= len(ordered_sessions):
                target = ordered_sessions[session_number_index - 1]

            if target is not None:
                final_summary = structured_summary or content
                existing_summary = (target['session_summary'] or '').strip()
                if existing_summary != final_summary:
                    db.execute(
                        'UPDATE group_sessions SET session_summary = ? WHERE id = ?',
                        (final_summary, target['id'])
                    )
                    synced += 1
                if meeting_title:
                    db.execute(
                        'UPDATE group_sessions SET title = ? WHERE id = ?',
                        (meeting_title, target['id'])
                    )
                if note_date:
                    db.execute(
                        'UPDATE group_sessions SET session_date = ? WHERE id = ?',
                        (note_date, target['id'])
                    )
                target_date = note_date or (target['session_date'] if 'session_date' in target.keys() else None)
                target_time = target['session_time'] if 'session_time' in target.keys() else None
                _apply_attendance_from_doc(
                    int(target['id']),
                    participant_entries or participants,
                    missing_note_entries or missing_entries,
                    session_date=target_date,
                    session_time=target_time,
                    session_title=meeting_title or (target['title'] if 'title' in target.keys() else None),
                    session_summary=structured_summary,
                )
                continue

            title = meeting_title or (f"Imported Session {session_number}" if session_number else 'Imported Session')
            db.execute('''
                INSERT INTO group_sessions (
                    group_id, session_date, session_time, duration_minutes, title, status, session_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (group['id'], note_date, '00:00', 60, title, 'completed', structured_summary or content))
            created_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            _apply_attendance_from_doc(
                int(created_id),
                participant_entries or participants,
                missing_note_entries or missing_entries,
                session_date=note_date,
                session_time='00:00',
                session_title=title,
                session_summary=structured_summary or content,
            )
            synced += 1

        db.commit()
    except Exception as exc:
        db.rollback()
        return 0, str(exc)

    return synced, None


def _sync_group_gdoc_sessions(db, group, session_id=None):
    from app import gdocs, gcal
    dependency_error = _google_docs_dependency_error()
    if dependency_error:
        return 0, dependency_error
    if not group or not group['gdoc_id']:
        return 0, 'No Google Doc linked'
    creds = gcal.load_credentials(db)
    if not creds:
        return 0, 'Google not connected — connect via Admin Profile first'
    try:
        creds = gcal._refresh_and_save(db, creds)
    except Exception as exc:
        return 0, str(exc)
    params = [group['id']]
    where_sql = ''
    if session_id:
        where_sql = ' AND gs.id = ?'
        params.append(session_id)
    sessions = db.execute(f'''
        SELECT gs.*, g.name AS group_name
        FROM group_sessions gs
        JOIN groups g ON g.id = gs.group_id
        WHERE gs.group_id = ?{where_sql}
        ORDER BY gs.session_date ASC, gs.session_time ASC, gs.id ASC
    ''', params).fetchall()
    if not sessions:
        return 0, None
    existing_text = ''
    try:
        existing_text = gdocs.read_doc_text(creds, group['gdoc_id']) or ''
    except Exception:
        existing_text = ''
    blocks = []
    for index, session in enumerate(sessions, start=1):
        display_number = session['occurrence_index'] or index
        marker_variants = [
            f"GROUP SESSION #{session['id']}",
            f"[note:id={session['id']}]",
            f"SESSION #{display_number} | {session['session_date']}"
        ]
        if any(marker in existing_text for marker in marker_variants):
            continue
        attendance_rows = db.execute('''
            SELECT p.name AS patient_name,
                   COALESCE(gsa.attendance_status, 'pending') AS attendance_status,
                   COALESCE(gsa.absence_reason, '') AS absence_reason
            FROM group_session_attendance gsa
            JOIN patients p ON p.id = gsa.patient_id
            WHERE gsa.session_id = ?
            ORDER BY p.name ASC
        ''', (session['id'],)).fetchall()
        present_names = [row['patient_name'] for row in attendance_rows if row['attendance_status'] == 'present']
        missed_names = [
            row['patient_name'] + (f" — {row['absence_reason']}" if row['absence_reason'] else '')
            for row in attendance_rows if row['attendance_status'] == 'missed'
        ]
        group_label = session['group_name'] or group['name'] or f"Group {group['id']}"
        lines = [
            f"SESSION #{display_number} | {session['session_date']} [note:id={session['id']}]",
            f"Group: {group_label}",
        ]
        if session['session_time']:
            lines.append(f"Time: {session['session_time']}")
        if session['title']:
            lines.append(f"Title: {session['title']}")
        if session['facilitator']:
            lines.append(f"Facilitator: {session['facilitator']}")
        if session['meeting_type']:
            lines.append(f"Meeting Type: {session['meeting_type']}")
        if present_names:
            lines.append('Participants: ' + ', '.join(present_names))
        if missed_names:
            lines.append('Missing: ' + '; '.join(missed_names))
        if session['session_summary']:
            lines.append(session['session_summary'])
        blocks.append('\n'.join(lines).strip())
    if not blocks:
        return 0, None
    service = gdocs._docs_service(creds)
    doc = service.documents().get(documentId=group['gdoc_id']).execute()
    content = doc.get('body', {}).get('content', [])
    end_index = max(1, content[-1].get('endIndex', 1) - 1) if content else 1
    text_to_append = '\n\n' + '\n\n'.join(blocks) + '\n'
    service.documents().batchUpdate(documentId=group['gdoc_id'], body={
        'requests': [{'insertText': {'location': {'index': end_index}, 'text': text_to_append}}]
    }).execute()
    return len(blocks), None


# ---------------------------------------------------------------------------
# Patient Google Doc routes
# ---------------------------------------------------------------------------


@google_docs_bp.route('/patient/<int:patient_id>/link-gdoc', methods=['POST'])
@login_required
def link_gdoc(patient_id):
    from app import gdocs, gcal
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    dependency_error = _google_docs_dependency_error()
    if dependency_error:
        return jsonify({'error': dependency_error}), 500
    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    creds = gcal.load_credentials(db)
    if not creds:
        return jsonify({'error': 'Google not connected — connect via Admin Profile first'}), 400
    try:
        creds = gcal._refresh_and_save(db, creds)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    try:
        doc_id = gdocs.create_patient_doc(creds, patient['name'])
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    webhook_url = (request.form.get('webhook_url') or '').strip()
    channel_id, expiry = None, None
    if webhook_url:
        try:
            channel_id, expiry = gdocs.register_drive_watch(creds, doc_id, webhook_url)
        except Exception:
            pass
    db.execute(
        'UPDATE patients SET gdoc_id = ?, gdoc_watch_channel = ?, gdoc_watch_expiry = ? WHERE id = ?',
        (doc_id, channel_id, expiry, patient_id)
    )
    db.commit()
    return jsonify({
        'status':  'ok',
        'doc_id':  doc_id,
        'doc_url': f'https://docs.google.com/document/d/{doc_id}/edit',
        'message': 'Google Doc created and linked successfully.',
    })


@google_docs_bp.route('/patient/<int:patient_id>/attach-gdoc', methods=['POST'])
@login_required
def attach_gdoc(patient_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    doc_url = request.form.get('doc_url', '').strip()
    if not doc_url:
        return jsonify({'error': 'No document URL provided'}), 400
    doc_id = _extract_google_doc_id(doc_url)
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
        'message': 'Google Doc linked successfully.',
    })


@google_docs_bp.route('/patient/<int:patient_id>/detach-gdoc', methods=['POST'])
@login_required
def detach_gdoc(patient_id):
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
    return jsonify({'status': 'ok', 'message': 'Google Doc disconnected successfully.'})


@google_docs_bp.route('/patient/<int:patient_id>/open-gdoc')
@login_required
def open_gdoc(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    patient = db.execute('SELECT gdoc_id FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient or not patient['gdoc_id']:
        flash('No Google Doc linked for this patient.')
        return redirect(url_for('patients.patient_detail', patient_id=patient_id))
    return redirect(f'https://docs.google.com/document/d/{patient["gdoc_id"]}/edit')


@google_docs_bp.route('/patient/<int:patient_id>/sync-from-gdoc', methods=['POST'])
@login_required
def sync_from_gdoc(patient_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    dependency_error = _google_docs_dependency_error()
    if dependency_error:
        return jsonify({'error': dependency_error}), 500
    db = get_db()
    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if not patient or not patient['gdoc_id']:
        return jsonify({'error': 'No Google Doc linked'}), 400
    count, err = _pull_gdoc_notes(db, patient)
    if err:
        return jsonify({'error': err}), 500
    return jsonify({'status': 'ok', 'synced': count, 'message': f'Synced {count} note(s) from Google Doc.'})


# ---------------------------------------------------------------------------
# Group Google Doc routes
# ---------------------------------------------------------------------------


@google_docs_bp.route('/groups/<int:group_id>/link-gdoc', methods=['POST'])
@login_required
def link_group_gdoc(group_id):
    from app import gdocs, gcal
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    dependency_error = _google_docs_dependency_error()
    if dependency_error:
        return jsonify({'error': dependency_error}), 500
    db = get_db()
    group = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    creds = gcal.load_credentials(db)
    if not creds:
        return jsonify({'error': 'Google not connected — connect via Admin Profile first'}), 400
    try:
        creds = gcal._refresh_and_save(db, creds)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    try:
        create_group_doc = getattr(gdocs, 'create_group_doc', None)
        group_name = (group['name'] or '').strip() or f'Group {group_id}'
        if callable(create_group_doc):
            doc_id = create_group_doc(creds, group_name)
        else:
            doc_id = gdocs.create_patient_doc(creds, f"Group — {group_name}")
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    webhook_url = (request.form.get('webhook_url') or '').strip()
    channel_id, expiry = None, None
    if webhook_url:
        try:
            channel_id, expiry = gdocs.register_drive_watch(creds, doc_id, webhook_url)
        except Exception:
            pass
    db.execute(
        'UPDATE groups SET gdoc_id = ?, gdoc_watch_channel = ?, gdoc_watch_expiry = ? WHERE id = ?',
        (doc_id, channel_id, expiry, group_id)
    )
    db.commit()
    return jsonify({
        'status': 'ok',
        'doc_id': doc_id,
        'doc_url': f'https://docs.google.com/document/d/{doc_id}/edit',
        'message': 'Google Doc created and linked successfully.'
    })


@google_docs_bp.route('/groups/<int:group_id>/attach-gdoc', methods=['POST'])
@login_required
def attach_group_gdoc(group_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    doc_id = _extract_google_doc_id(request.form.get('doc_url', ''))
    if not doc_id:
        return jsonify({'error': 'Invalid document URL or ID'}), 400
    db = get_db()
    group = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    db.execute('UPDATE groups SET gdoc_id = ? WHERE id = ?', (doc_id, group_id))
    db.commit()
    return jsonify({
        'status': 'ok',
        'doc_id': doc_id,
        'doc_url': f'https://docs.google.com/document/d/{doc_id}/edit',
        'message': 'Google Doc linked successfully.'
    })


@google_docs_bp.route('/groups/<int:group_id>/detach-gdoc', methods=['POST'])
@login_required
def detach_group_gdoc(group_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    group = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    db.execute(
        'UPDATE groups SET gdoc_id = NULL, gdoc_watch_channel = NULL, gdoc_watch_expiry = NULL WHERE id = ?',
        (group_id,)
    )
    db.commit()
    return jsonify({'status': 'ok', 'message': 'Google Doc disconnected successfully.'})


@google_docs_bp.route('/groups/<int:group_id>/open-gdoc')
@login_required
def open_group_gdoc(group_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    group = db.execute('SELECT gdoc_id FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group or not group['gdoc_id']:
        flash('No Google Doc linked for this group.')
        return redirect(url_for('groups.group_detail', group_id=group_id))
    return redirect(f"https://docs.google.com/document/d/{group['gdoc_id']}/edit")


@google_docs_bp.route('/groups/<int:group_id>/sync-gdoc', methods=['POST'])
@login_required
def sync_group_gdoc(group_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    group = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    session_id_raw = (request.form.get('session_id') or '').strip()
    session_id = int(session_id_raw) if session_id_raw.isdigit() else None
    sync_mode = (request.form.get('mode') or 'both').strip().lower()
    if sync_mode not in ('both', 'pull', 'push'):
        return jsonify({'error': 'Invalid sync mode'}), 400
    pulled = 0
    pushed = 0
    if sync_mode in ('both', 'pull'):
        pulled, pull_err = _pull_group_gdoc_notes(db, group)
        if pull_err:
            return jsonify({'error': pull_err}), 400
    if sync_mode in ('both', 'push'):
        pushed, push_err = _sync_group_gdoc_sessions(db, group, session_id=session_id)
        if push_err:
            return jsonify({'error': push_err}), 400
    total_synced = int(pulled or 0) + int(pushed or 0)
    if sync_mode == 'pull':
        message = f'Replaced site meeting content from Google Docs for {int(pulled or 0)} meeting(s).'
    elif sync_mode == 'push':
        message = f'Appended {int(pushed or 0)} meeting record(s) to the end of Google Docs.'
    else:
        message = f'Synced {total_synced} group meeting record(s). Pulled {int(pulled or 0)} from Google Docs and pushed {int(pushed or 0)} back.'
    return jsonify({
        'status': 'ok',
        'synced': total_synced,
        'pulled': int(pulled or 0),
        'pushed': int(pushed or 0),
        'doc_url': f"https://docs.google.com/document/d/{group['gdoc_id']}/edit",
        'mode': sync_mode,
        'message': message
    })


@google_docs_bp.route('/groups/<int:group_id>/pull-gdoc', methods=['POST'])
@login_required
def pull_group_gdoc(group_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    group = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    pulled, pull_err = _pull_group_gdoc_notes(db, group)
    if pull_err:
        return jsonify({'error': pull_err}), 400
    return jsonify({
        'status': 'ok',
        'pulled': int(pulled or 0),
        'synced': int(pulled or 0),
        'doc_url': f"https://docs.google.com/document/d/{group['gdoc_id']}/edit",
        'message': f'Replaced site meeting content from Google Docs for {int(pulled or 0)} meeting(s).'
    })


@google_docs_bp.route('/groups/<int:group_id>/push-gdoc', methods=['POST'])
@login_required
def push_group_gdoc(group_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    group = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    session_id_raw = (request.form.get('session_id') or '').strip()
    session_id = int(session_id_raw) if session_id_raw.isdigit() else None
    pushed, push_err = _sync_group_gdoc_sessions(db, group, session_id=session_id)
    if push_err:
        return jsonify({'error': push_err}), 400
    return jsonify({
        'status': 'ok',
        'pushed': int(pushed or 0),
        'synced': int(pushed or 0),
        'doc_url': f"https://docs.google.com/document/d/{group['gdoc_id']}/edit",
        'message': f'Appended {int(pushed or 0)} meeting record(s) to the end of Google Docs.'
    })


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


@google_docs_bp.route('/api/gdoc/webhook', methods=['POST'])
def gdoc_webhook():
    from app import gdocs, gcal
    from app import csrf
    from app import _validate_gdoc_webhook_request
    if not _validate_gdoc_webhook_request():
        return '', 403
    channel_id = (request.headers.get('X-Goog-Channel-ID') or '').strip()
    db = get_db()
    patient = None
    group = None
    try:
        patient = db.execute(
            'SELECT * FROM patients WHERE gdoc_watch_channel = ?', (channel_id,)
        ).fetchone()
        if not patient:
            group = db.execute(
                'SELECT * FROM groups WHERE gdoc_watch_channel = ?', (channel_id,)
            ).fetchone()
    except Exception:
        pass
    if not patient and not group:
        return '', 404
    if patient and patient['gdoc_id'] and gdocs:
        try:
            _pull_gdoc_notes(db, patient)
        except Exception:
            pass
    return '', 200
