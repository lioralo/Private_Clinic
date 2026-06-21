import json
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, current_app, render_template
from flask_login import login_required, current_user

from clinic_app.utils import (
    parse_date_safe, parse_time_safe, combine_dt, custom_weekday,
    daterange, overlaps, _week_start_for_date, _check_public_rate_limit,
)
from clinic_app.models import get_db

calendar_bp = Blueprint('calendar', __name__)


def _login_json_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)
    return wrapper


def _parse_recurrence_days(appt):
    raw = (appt['recurrence_days'] if 'recurrence_days' in appt.keys() else '').strip()
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
    base_date = parse_date_safe(appt['appointment_date'] if 'appointment_date' in appt.keys() else '')
    if not base_date:
        return [0]
    return [custom_weekday(base_date)]


def _recurring_occurrences_for_week(appt, week_start, week_end):
    base_date = parse_date_safe(appt['appointment_date'])
    if not base_date:
        return []
    interval = int(appt['recurrence_interval'] or 1) if 'recurrence_interval' in appt.keys() else 1
    if interval <= 0:
        interval = 1
    recurrence_end = parse_date_safe(appt['recurrence_end_date'] if 'recurrence_end_date' in appt.keys() else '')
    recurrence_count = int(appt['recurrence_count'] or 0) if 'recurrence_count' in appt.keys() else 0
    days = _parse_recurrence_days(appt)
    excluded_raw = appt['excluded_dates'] if 'excluded_dates' in appt.keys() else ''
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


def _process_calendar_follow_ups(db, today):
    follow_up_alerts = []
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
    return follow_up_alerts


def _process_calendar_appointments(appointment_rows, user, week_start, week_end, events, occupied, emitted_appointment_keys):
    for appt in appointment_rows:
        is_recurring = int(appt['is_recurring'] or 0) == 1
        occ_dates = _recurring_occurrences_for_week(appt, week_start, week_end) if is_recurring else [parse_date_safe(appt['appointment_date'])]
        occ_dates = [d for d in occ_dates if d is not None]
        for occ_date in occ_dates:
            start_dt = combine_dt(occ_date, appt['appointment_time'])
            duration = int(appt['duration_minutes'] or 60)
            end_dt = start_dt + timedelta(minutes=duration)
            if user.role == 'patient' and appt['patient_id'] != user.patient_id:
                occupied.append((start_dt, end_dt))
                continue
            title = appt['patient_name']
            is_own = (user.role == 'patient' and appt['patient_id'] == user.patient_id)
            can_delete = user.role == 'admin' or is_own
            appointment_key = (appt['patient_id'], start_dt.isoformat(), end_dt.isoformat())
            if appointment_key in emitted_appointment_keys:
                continue
            emitted_appointment_keys.add(appointment_key)
            event_color = '#2563eb' if appt['patient_status'] == 'ongoing' else '#f59e0b'
            if appt['patient_status'] == 'archived':
                event_color = '#6b7280'
            platform = appt['meeting_platform'] if 'meeting_platform' in appt.keys() else ''
            meeting_title = appt['meeting_title'] if 'meeting_title' in appt.keys() else ''
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
                    'can_edit': can_delete,
                }
            })
            occupied.append((start_dt, end_dt))


def _process_calendar_group_sessions(group_sessions, user, events, occupied):
    for group_session in group_sessions:
        session_date = parse_date_safe(group_session['session_date'])
        if not session_date:
            continue
        session_start = combine_dt(session_date, group_session['session_time'])
        session_duration = int(group_session['duration_minutes'] or 60)
        session_end = session_start + timedelta(minutes=session_duration)
        if user.role != 'admin':
            occupied.append((session_start, session_end))
            continue
        from flask import url_for
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
                'title': group_session['title'] if 'title' in group_session.keys() else '',
                'facilitator': group_session['facilitator'] if 'facilitator' in group_session.keys() else '',
                'meeting_type': group_session['meeting_type'] if 'meeting_type' in group_session.keys() else None,
                'meeting_link': group_session['meeting_link'] if 'meeting_link' in group_session.keys() else None,
                'detail_url': detail_url,
                'can_delete': user.role == 'admin',
                'can_edit': user.role == 'admin',
            }
        })
        occupied.append((session_start, session_end))


def _process_calendar_blocks(blocks, user, events, occupied, weekend_specials):
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
        occupied.append((start_dt, end_dt))
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
                'can_delete': user.role == 'admin',
            }
        })
        day_code = custom_weekday(block_date)
        if day_code == 5:
            weekend_specials['friday'].append({
                'id': block['id'],
                'title': visible_title,
                'time': block['blocked_time'],
                'duration': duration,
                'type': block_type,
            })
        if day_code == 6:
            weekend_specials['saturday'].append({
                'id': block['id'],
                'title': visible_title,
                'time': block['blocked_time'],
                'duration': duration,
                'type': block_type,
            })


def _process_calendar_vacancies(db, week_start, week_end, user, events, occupied):
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
            'duration_minutes': row['duration_minutes'],
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
                'duration_minutes': row['duration_minutes'],
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
        duration = int(row['duration_minutes'] or 60) if 'duration_minutes' in row.keys() else 60
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
                'duration_minutes': duration,
            })
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
                        'can_delete': True,
                    }
                })
    return available_slots


def _process_calendar_external_events(db, week_start, week_end, user):
    external_events = []
    from app import gcal
    if gcal and hasattr(gcal, 'GOOGLE_LIBS_AVAILABLE') and gcal.GOOGLE_LIBS_AVAILABLE and user.role == 'admin':
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
                if evt.get('google_event_id') and evt['google_event_id'] not in our_event_ids:
                    external_events.append(evt)
        except Exception:
            pass
    return external_events


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
    follow_up_alerts = _process_calendar_follow_ups(db, today)
    _process_calendar_appointments(appointment_rows, user, week_start, week_end, events, occupied, emitted_appointment_keys)
    _process_calendar_group_sessions(group_sessions, user, events, occupied)
    _process_calendar_blocks(blocks, user, events, occupied, weekend_specials)
    available_slots = _process_calendar_vacancies(db, week_start, week_end, user, events, occupied)
    external_events = _process_calendar_external_events(db, week_start, week_end, user)
    return {
        'week_start': week_start.isoformat(),
        'week_end': week_end.isoformat(),
        'events': events,
        'external_events': external_events,
        'weekend_specials': weekend_specials,
        'available_slots': available_slots,
        'follow_up_alerts': follow_up_alerts,
    }


def _nearest_calendar_anchor_date(db, user):
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
    if user.role == 'admin':
        for table, date_col in [
            ('group_sessions', 'session_date'),
            ('blocked_slots', 'blocked_date'),
        ]:
            for direction, cmp in [('ASC', '>='), ('DESC', '<')]:
                row = db.execute(
                    f'SELECT {date_col} AS day FROM {table} WHERE {date_col} {cmp} ? ORDER BY {date_col} {direction} LIMIT 1',
                    (today.isoformat(),)
                ).fetchone()
                if row and parse_date_safe(row['day']):
                    return parse_date_safe(row['day'])
    return today


def collect_public_available_slots(db, weeks_ahead=10):
    today = datetime.now().date()
    week_start = today - timedelta(days=custom_weekday(today))
    from app import User
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
                'label': f"{slot_date.isoformat()} {slot_time.strftime('%H:%M')} - {end_dt.strftime('%H:%M')} ({duration} min)",
            })
    slots.sort(key=lambda s: (s['date'], s['time']))
    return slots


def _api_calendar_book_special(db, current_user, anchor, booking_time, duration, special_pattern, special_repeat_until, special_title):
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
    parsed_booking_time = parse_time_safe(booking_time)
    from app import has_time_conflict
    for d in dates_to_block:
        date_iso = d.isoformat()
        start_dt = combine_dt(d, parsed_booking_time.strftime('%H:%M'))
        end_dt = start_dt + timedelta(minutes=duration)
        conflict = has_time_conflict(db, d, start_dt, end_dt)
        if conflict:
            return jsonify({'status': 'error', 'message': f'Special slot overlaps existing time on {date_iso}.'}), 409
    for d in dates_to_block:
        db.execute('''
            INSERT INTO blocked_slots
            (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
              VALUES (?, ?, ?, ?, 1, 'blocked', ?)
        ''', (d.isoformat(), parsed_booking_time.strftime('%H:%M'), duration,
              special_title or 'Special Occasion', current_user.id))
        db.execute('''
            UPDATE slots_override
            SET status = 'booked', booked_by_name = ?, booked_at = ?
            WHERE slot_date = ? AND slot_time = ? AND status = 'available'
        ''', (
            special_title or 'Special Occasion',
            datetime.now().isoformat(),
            d.isoformat(),
            parsed_booking_time.strftime('%H:%M')
        ))
    db.commit()
    return jsonify({'status': 'success'})


def _api_calendar_book_regular(db, current_user, anchor, booking_date, booking_time, parsed_booking_time, duration, patient_id, patient_status, is_recurring_explicit, recurrence_end_date_form, meeting_type, meeting_link, meeting_platform, meeting_remarks, save_to_google):
    if is_recurring_explicit in ('1', 'on', 'true'):
        is_recurring = 1
    elif is_recurring_explicit == '0':
        is_recurring = 0
    else:
        is_recurring = 1 if patient_status == 'ongoing' else 0
    recurrence_interval = 1 if is_recurring else None
    recurrence_days = str(custom_weekday(anchor)) if is_recurring else None
    start_dt = combine_dt(anchor, parsed_booking_time.strftime('%H:%M'))
    end_dt = start_dt + timedelta(minutes=duration)
    from app import has_time_conflict
    conflict_message = has_time_conflict(db, anchor, start_dt, end_dt)
    if conflict_message:
        return jsonify({'status': 'error', 'message': conflict_message}), 409
    if current_user.role != 'admin':
        week_start = anchor - timedelta(days=custom_weekday(anchor))
        from app import User
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
    recurrence_group_id = secrets.token_hex(16) if is_recurring else None
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
    response_payload = {'status': 'success'}
    if patient_id:
        new_appt = db.execute(
            'SELECT id FROM appointments WHERE patient_id = ? AND appointment_date = ? AND appointment_time = ? ORDER BY id DESC LIMIT 1',
            (patient_id, booking_date, parsed_booking_time.strftime('%H:%M')),
        ).fetchone()
        if new_appt:
            from app import _sync_appointment_with_google
            sync_message = _sync_appointment_with_google(db, int(new_appt['id']))
            if sync_message:
                response_payload['message'] = sync_message
    return jsonify(response_payload)


# ---- API Routes ----

@calendar_bp.route('/api/calendar/snapshot')
@_login_json_required
def api_calendar_snapshot():
    start_raw = request.args.get('week_start', '').strip()
    anchor = parse_date_safe(start_raw) or datetime.now().date()
    week_start = anchor - timedelta(days=custom_weekday(anchor))
    db = get_db()
    if current_user.role == 'admin':
        from app import ensure_ongoing_recurrence_from_previous_week, ensure_ongoing_patients_have_upcoming_bookings, ensure_default_recurring_vacancies
        ensure_ongoing_recurrence_from_previous_week(db, anchor)
        ensure_ongoing_patients_have_upcoming_bookings(db, anchor)
        ensure_default_recurring_vacancies(db)
    payload = build_week_calendar_snapshot(db, week_start, current_user)
    return jsonify(payload)


@calendar_bp.route('/api/calendar/block', methods=['POST'])
@_login_json_required
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
    from app import has_time_conflict
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


@calendar_bp.route('/api/calendar/block/<int:block_id>/update', methods=['POST'])
@_login_json_required
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
    from app import has_time_conflict
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


@calendar_bp.route('/api/calendar/block/<int:block_id>/delete', methods=['POST'])
@_login_json_required
def api_calendar_block_delete(block_id):
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    db = get_db()
    db.execute('DELETE FROM blocked_slots WHERE id = ?', (block_id,))
    db.commit()
    return jsonify({'status': 'success'})


@calendar_bp.route('/api/calendar/bookings')
@_login_json_required
def api_calendar_bookings():
    if current_user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    mode = (request.args.get('mode') or 'upcoming').strip().lower()
    if mode not in ('upcoming', 'history'):
        mode = 'upcoming'
    db = get_db()
    from app import build_booking_management_payload
    payload = build_booking_management_payload(db, mode=mode)
    return jsonify(payload)


@calendar_bp.route('/api/calendar/vacancy', methods=['POST'])
@_login_json_required
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
    from app import has_time_conflict
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
        return jsonify({'status': 'success', 'recurrence_pattern': 'weekly', 'recurring_id': insert_cur.lastrowid})
    db.execute('''
        DELETE FROM slots_override
        WHERE slot_date = ? AND slot_time = ? AND status = 'available'
    ''', (slot_date, start_time.strftime('%H:%M')))
    insert_cur = db.execute('''
        INSERT INTO slots_override (slot_date, slot_time, status, duration_minutes)
        VALUES (?, ?, 'available', ?)
    ''', (slot_date, start_time.strftime('%H:%M'), duration))
    db.commit()
    return jsonify({'status': 'success', 'recurrence_pattern': 'one-time', 'override_id': insert_cur.lastrowid})


@calendar_bp.route('/api/calendar/vacancies')
@_login_json_required
def api_calendar_vacancies():
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
    weekday_names = {0: 'Sunday', 1: 'Monday', 2: 'Tuesday', 3: 'Wednesday', 4: 'Thursday', 5: 'Friday', 6: 'Saturday'}
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
            'booked_by_name': row['booked_by_name'] if 'booked_by_name' in row.keys() else '',
            'booked_by_phone': row['booked_by_phone'] if 'booked_by_phone' in row.keys() else '',
            'booked_at': row['booked_at'] if 'booked_at' in row.keys() else '',
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


@calendar_bp.route('/api/calendar/vacancy/<int:override_id>/occupy', methods=['POST'])
@_login_json_required
def api_calendar_vacancy_occupy(override_id):
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
    from app import has_time_conflict
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
            str(custom_weekday(date_obj)) if is_ongoing else None,
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


@calendar_bp.route('/api/calendar/vacancy/<int:override_id>/delete', methods=['POST'])
@_login_json_required
def api_calendar_vacancy_delete(override_id):
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


@calendar_bp.route('/api/calendar/book', methods=['POST'])
@_login_json_required
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
    duration = 60
    parsed_start = parse_time_safe(booking_time)
    parsed_end = parse_time_safe(end_time_raw) if end_time_raw else None
    if parsed_start and parsed_end:
        start_minutes = parsed_start.hour * 60 + parsed_start.minute
        end_minutes = parsed_end.hour * 60 + parsed_end.minute
        computed = end_minutes - start_minutes
        if computed > 0:
            duration = computed
    from app import _validate_appointment_duration
    valid_duration, dur_error = _validate_appointment_duration(duration)
    if dur_error:
        return jsonify({'status': 'error', 'message': dur_error}), 400
    duration = valid_duration
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
    anchor = parse_date_safe(booking_date)
    if not anchor:
        return jsonify({'status': 'error', 'message': 'Invalid booking date.'}), 400
    if booking_type == 'special':
        return _api_calendar_book_special(
            db, current_user, anchor, booking_time, duration,
            special_pattern, special_repeat_until, special_title
        )
    parsed_booking_time = parse_time_safe(booking_time)
    if not parsed_booking_time:
        return jsonify({'status': 'error', 'message': 'Invalid time.'}), 400
    return _api_calendar_book_regular(
        db, current_user, anchor, booking_date, booking_time, parsed_booking_time,
        duration, patient_id, patient_status, is_recurring_explicit,
        recurrence_end_date_form, meeting_type, meeting_link,
        meeting_platform, meeting_remarks, save_to_google
    )




