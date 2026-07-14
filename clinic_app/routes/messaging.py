import os
import tempfile
from datetime import datetime

from flask import (
    Blueprint, current_app, flash, jsonify, redirect,
    render_template, request, Response, url_for,
)
from flask_login import current_user, login_required

from clinic_app.models import get_db
from clinic_app.utils import redirect_to_patient_tab


messaging_bp = Blueprint('messaging', __name__)


from clinic_app.config import LEGACY_WAITING_STATUSES


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
        if status_filter in LEGACY_WAITING_STATUSES:
            filters.append("p.status IN ('candidate', 'waiting', 'waiting for scheduling')")
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


def _get_patient_messages_api(db):
    messages = db.execute('''
        SELECT m.*, u.username as sender_name
        FROM messages m
        LEFT JOIN users u ON m.sender_id = u.id
        WHERE m.sender_id = ? OR m.recipient_id = ?
        ORDER BY m.timestamp ASC
    ''', (current_user.id, current_user.id)).fetchall()

    return jsonify([dict(m) for m in messages])


@messaging_bp.route('/api/messages', methods=['GET'])
@login_required
def api_get_messages():
    db = get_db()
    if current_user.role == 'admin':
        return _get_admin_messages(db)
    else:
        return _get_patient_messages_api(db)


@messaging_bp.route('/api/messages/send', methods=['POST'])
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
            try:
                for recipient in recipients:
                    db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                               (current_user.id, recipient['id'], content))
                db.commit()
            except Exception:
                db.rollback()
                return jsonify({'status': 'error', 'message': 'Database error while sending messages.'}), 500
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


@messaging_bp.route('/patient/<int:patient_id>/send_message', methods=['POST'])
@login_required
def send_message(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    content = (request.form.get('content') or '').strip()
    if content:
        db = get_db()
        user = db.execute('SELECT id FROM users WHERE patient_id = ?', (patient_id,)).fetchone()
        if user:
            db.execute(
                'INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                (current_user.id, user['id'], content)
            )
            db.commit()
            flash('Message sent.', 'success')
        else:
            flash('Patient does not have an active user account to receive messages.', 'error')

    return redirect_to_patient_tab(patient_id, 'messages')


@messaging_bp.route('/admin_reply_message/<int:patient_id>', methods=['POST'])
@login_required
def admin_reply_message(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    content = (request.form.get('content') or '').strip()
    if content:
        db = get_db()
        user = db.execute('SELECT id FROM users WHERE patient_id = ?', (patient_id,)).fetchone()
        if user:
            db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                       (current_user.id, user['id'], content))
            db.commit()
            flash('Message sent.', 'success')
        else:
            flash('Patient does not have an active user account to receive messages.', 'error')

    return redirect_to_patient_tab(patient_id, 'messages')


@messaging_bp.route('/contact_admin', methods=('POST',))
@login_required
def contact_admin():
    if current_user.role != 'patient':
        return "Unauthorized", 403

    db = get_db()
    from clinic_app.utils import _check_db_rate_limit, _record_db_rate_limit
    bucket_key = f"contact-admin-{current_user.id}"
    retry_after = _check_db_rate_limit(db, bucket_key, 'contact', 10, 60) # 10 messages per minute
    if retry_after:
        flash(f'Too many messages. Please wait {retry_after} seconds.', 'warning')
        return redirect(url_for('patient_home'))
    _record_db_rate_limit(db, bucket_key, 'contact')

    content = (request.form.get('content') or '').strip()
    if content:
        admin = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        recipient_id = admin['id'] if admin else None

        db.execute('INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                   (current_user.id, recipient_id, content))
        db.commit()
        flash('Message sent to your therapist.', 'success')

    return redirect(url_for('patient_home'))


@messaging_bp.route('/contact-inquiry', methods=('POST',))
def contact_inquiry():
    """Handle public contact form submissions from the About page (no login required)."""
    name = (request.form.get('inquiry_name') or '').strip()
    email = (request.form.get('inquiry_email') or '').strip() or None
    phone = (request.form.get('inquiry_phone') or '').strip() or None
    message = (request.form.get('inquiry_message') or '').strip()

    errors = []
    if not name:
        errors.append('Name is required.')
    if not message:
        errors.append('Message is required.')
    if not email and not phone:
        errors.append('Please provide at least one contact method (email or phone).')
    if email and len(email) > 254:
        errors.append('Email address is too long.')
    if phone and len(phone) > 30:
        errors.append('Phone number is too long.')

    redirect_target = (request.referrer or '') or url_for('about_page')
    if not redirect_target.startswith(request.host_url):
        redirect_target = url_for('about_page')

    if errors:
        for err in errors:
            flash(err, 'error')
        return redirect(redirect_target + ('#contact-form' if '#' not in redirect_target else ''))

    db = get_db()
    db.execute(
        'INSERT INTO contact_inquiries (name, email, phone, message) VALUES (?, ?, ?, ?)',
        (name, email, phone, message),
    )
    db.commit()
    flash('Your message has been sent. We will get back to you soon.', 'success')
    return redirect(redirect_target + ('#contact-form' if '#' not in redirect_target else ''))


contact_inquiry.is_csrf_exempt = True  # public endpoint


@messaging_bp.route('/admin/contact-inquiries')
@login_required
def admin_contact_inquiries():
    """Admin view for public contact form submissions."""
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    inquiries = db.execute(
        'SELECT * FROM contact_inquiries ORDER BY is_read ASC, created_at DESC'
    ).fetchall()
    return render_template('admin_contact_inquiries.html', inquiries=inquiries)


@messaging_bp.route('/admin/contact-inquiries/<int:inquiry_id>/read', methods=['POST'])
@login_required
def mark_contact_inquiry_read(inquiry_id):
    """Mark a contact inquiry as read."""
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    db.execute('UPDATE contact_inquiries SET is_read = 1 WHERE id = ?', (inquiry_id,))
    db.commit()
    return redirect(url_for('.admin_contact_inquiries'))


@messaging_bp.route('/admin/contact-inquiries/<int:inquiry_id>/delete', methods=['POST'])
@login_required
def delete_contact_inquiry(inquiry_id):
    """Delete a contact inquiry."""
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    db.execute('DELETE FROM contact_inquiries WHERE id = ?', (inquiry_id,))
    db.commit()
    return redirect(url_for('.admin_contact_inquiries'))


def _get_notification_patient_choices(db):
    return [dict(row) for row in db.execute('''
        SELECT p.id AS patient_id,
               p.name AS patient_name,
               COALESCE(p.patient_type, 'private') AS patient_type,
               COALESCE(p.status, 'ongoing') AS status,
               u.id AS user_id,
               CASE WHEN u.id IS NULL THEN 0 ELSE 1 END AS has_login
        FROM patients p
        LEFT JOIN users u
          ON u.patient_id = p.id
         AND u.role = 'patient'
         AND COALESCE(u.is_active, 1) = 1
        WHERE COALESCE(p.is_deleted, 0) = 0
        ORDER BY CASE COALESCE(p.patient_type, 'private')
            WHEN 'group' THEN 0
            WHEN 'private' THEN 1
            WHEN 'residency' THEN 2
            WHEN 'initial-intake' THEN 3
            ELSE 4 END,
            CASE WHEN COALESCE(p.status, '') = 'archived' THEN 1 ELSE 0 END,
            p.name ASC
    ''').fetchall()]


def _get_notification_target_users(db, audience='all', selected_patient_ids=None):
    selected_patient_ids = [int(pid) for pid in (selected_patient_ids or []) if str(pid).isdigit()]
    filters = ["u.role = 'patient'", 'COALESCE(u.is_active, 1) = 1', 'COALESCE(p.is_deleted, 0) = 0']
    params = []

    normalized_audience = (audience or 'all').strip().lower()
    if normalized_audience in {'group', 'private', 'residency'}:
        filters.append('COALESCE(p.patient_type, \'private\') = ?')
        params.append(normalized_audience)
    elif normalized_audience == 'selected':
        if not selected_patient_ids:
            return []
        placeholders = ','.join(['?'] * len(selected_patient_ids))
        filters.append(f'p.id IN ({placeholders})')
        params.extend(selected_patient_ids)

    query = f'''
        SELECT DISTINCT u.id AS user_id,
               p.id AS patient_id,
               p.name AS patient_name,
               COALESCE(p.patient_type, 'private') AS patient_type
        FROM users u
        JOIN patients p ON p.id = u.patient_id
        WHERE {' AND '.join(filters)}
        ORDER BY p.name ASC
    '''
    return [dict(row) for row in db.execute(query, params).fetchall()]


@messaging_bp.route('/api/notification_recipients')
@login_required
def notification_recipients():
    if current_user.role != 'admin':
        return jsonify([])

    db = get_db()
    return jsonify(_get_notification_patient_choices(db))


@messaging_bp.route('/admin/notifications/send', methods=['POST'])
@login_required
def send_admin_notification():
    if current_user.role != 'admin':
        return 'Unauthorized', 403

    title = (request.form.get('title') or '').strip()
    message = (request.form.get('message') or '').strip()
    audience = (request.form.get('audience') or 'all').strip().lower()
    selected_patient_ids = request.form.getlist('patient_ids')

    if not message:
        flash('Notification message is required.', 'error')
        return redirect(request.referrer or url_for('admin_dashboard'))

    if audience not in {'all', 'group', 'private', 'residency', 'selected'}:
        audience = 'all'

    db = get_db()
    recipients = _get_notification_target_users(db, audience=audience, selected_patient_ids=selected_patient_ids)
    if not recipients:
        flash('No patient portal users matched the selected notification audience.', 'warning')
        return redirect(request.referrer or url_for('admin_dashboard'))

    title_value = title or 'Clinic Update'
    for recipient in recipients:
        db.execute('''
            INSERT INTO notifications (title, message, recipient_user_id, sender_id, audience, is_read)
            VALUES (?, ?, ?, ?, ?, 0)
        ''', (title_value, message, recipient['user_id'], current_user.id, audience))

    db.commit()
    flash(f'Notification sent to {len(recipients)} patient(s).', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@messaging_bp.route('/api/notifications')
@login_required
def get_notifications():
    db = get_db()
    include_all = (request.args.get('all') or '').strip() in {'1', 'true', 'yes'}
    mark_read = (request.args.get('mark_read') or '0').strip().lower() not in {'0', 'false', 'no'}

    if current_user.role == 'admin':
        if include_all:
            notifications = db.execute('''
                SELECT id,
                       COALESCE(title, 'Clinic Update') AS title,
                       message,
                       COALESCE(audience, 'admin') AS audience,
                       recipient_user_id,
                       sender_id,
                       COALESCE(is_read, 0) AS is_read,
                       created_at
                FROM notifications
                WHERE COALESCE(audience, 'admin') = 'admin'
                   OR recipient_user_id = ?
                   OR sender_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 60
            ''', (current_user.id, current_user.id)).fetchall()
        else:
            notifications = db.execute('''
                SELECT id,
                       COALESCE(title, 'Clinic Update') AS title,
                       message,
                       COALESCE(audience, 'admin') AS audience,
                       recipient_user_id,
                       sender_id,
                       COALESCE(is_read, 0) AS is_read,
                       created_at
                FROM notifications
                WHERE COALESCE(is_read, 0) = 0
                  AND (COALESCE(audience, 'admin') = 'admin' OR recipient_user_id = ?)
                ORDER BY datetime(created_at) ASC, id ASC
            ''', (current_user.id,)).fetchall()
    else:
        if include_all:
            notifications = db.execute('''
                SELECT id,
                       COALESCE(title, 'Clinic Update') AS title,
                       message,
                       COALESCE(audience, 'patient') AS audience,
                       recipient_user_id,
                       sender_id,
                       COALESCE(is_read, 0) AS is_read,
                       created_at
                FROM notifications
                WHERE recipient_user_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 60
            ''', (current_user.id,)).fetchall()
        else:
            notifications = db.execute('''
                SELECT id,
                       COALESCE(title, 'Clinic Update') AS title,
                       message,
                       COALESCE(audience, 'patient') AS audience,
                       recipient_user_id,
                       sender_id,
                       COALESCE(is_read, 0) AS is_read,
                       created_at
                FROM notifications
                WHERE COALESCE(is_read, 0) = 0
                  AND recipient_user_id = ?
                ORDER BY datetime(created_at) ASC, id ASC
            ''', (current_user.id,)).fetchall()

    if notifications and mark_read:
        notification_ids = [n['id'] for n in notifications]
        placeholders = ','.join(['?'] * len(notification_ids))
        db.execute(f'UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})', notification_ids)
        db.commit()

    return jsonify([dict(n) for n in notifications])


@messaging_bp.route('/api/notifications/mark_read', methods=['POST'])
@login_required
def mark_notifications_read():
    db = get_db()
    mark_all = (request.form.get('all') or request.args.get('all') or '').strip().lower() in {'1', 'true', 'yes'}
    raw_ids = request.form.getlist('notification_id') or request.args.getlist('notification_id')
    notification_ids = [int(value) for value in raw_ids if str(value).isdigit()]

    if current_user.role == 'admin':
        if mark_all:
            db.execute('''
                UPDATE notifications
                SET is_read = 1
                WHERE COALESCE(is_read, 0) = 0
                  AND (COALESCE(audience, 'admin') = 'admin' OR recipient_user_id = ? OR sender_id = ?)
            ''', (current_user.id, current_user.id))
            db.commit()
            return jsonify({'status': 'success'})

        if not notification_ids:
            return jsonify({'status': 'error', 'message': 'No notification selected.'}), 400

        placeholders = ','.join(['?'] * len(notification_ids))
        db.execute(f'''
            UPDATE notifications
            SET is_read = 1
            WHERE id IN ({placeholders})
              AND (COALESCE(audience, 'admin') = 'admin' OR recipient_user_id = ? OR sender_id = ?)
        ''', [*notification_ids, current_user.id, current_user.id])
    else:
        if mark_all:
            db.execute('''
                UPDATE notifications
                SET is_read = 1
                WHERE COALESCE(is_read, 0) = 0
                  AND recipient_user_id = ?
            ''', (current_user.id,))
            db.commit()
            return jsonify({'status': 'success'})

        if not notification_ids:
            return jsonify({'status': 'error', 'message': 'No notification selected.'}), 400

        placeholders = ','.join(['?'] * len(notification_ids))
        db.execute(f'''
            UPDATE notifications
            SET is_read = 1
            WHERE id IN ({placeholders})
              AND recipient_user_id = ?
        ''', [*notification_ids, current_user.id])

    db.commit()
    return jsonify({'status': 'success'})
