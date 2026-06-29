"""Optional IMAP-based incoming email polling.

Polls a mailbox (e.g. admin@clinic.lior-clinic.org) for replies to
reminder/notification emails and inserts them into the site's messages
table so the admin sees them in the patient messaging UI.

Requires IMAP_* env vars to be set; silently skipped if absent.
"""

import email
import imaplib
import re
from datetime import datetime


_REMINDER_SUBJECT_RE = re.compile(
    r'(Appointment Reminder|Appointment Cancelled|Appointment Rescheduled|New Appointment)',
    re.IGNORECASE,
)


def _get_imap_settings():
    import os
    host = (os.environ.get('IMAP_HOST') or '').strip()
    username = (os.environ.get('IMAP_USERNAME') or '').strip()
    password = os.environ.get('IMAP_PASSWORD', '')
    if not (host and username and password):
        return None
    port = int(os.environ.get('IMAP_PORT', '993') or 993)
    use_ssl = str(os.environ.get('IMAP_USE_SSL', '1')).strip().lower() in {'1', 'true', 'yes', 'on'}
    folder = (os.environ.get('IMAP_FOLDER') or 'INBOX').strip()
    return {
        'host': host,
        'port': port,
        'username': username,
        'password': password,
        'use_ssl': use_ssl,
        'folder': folder,
    }


def poll_incoming_email(app):
    """Check IMAP inbox for replies to automated emails and insert as messages."""
    settings = _get_imap_settings()
    if not settings:
        return 0

    try:
        if settings['use_ssl']:
            conn = imaplib.IMAP4_SSL(settings['host'], settings['port'])
        else:
            conn = imaplib.IMAP4(settings['host'], settings['port'])
            conn.starttls()
        conn.login(settings['username'], settings['password'])
        conn.select(settings['folder'], readonly=True)

        status, message_ids = conn.search(None, 'UNSEEN')
        if status != 'OK' or not message_ids[0]:
            conn.logout()
            return 0

        processed = 0
        with app.app_context():
            from clinic_app.models import get_db
            db = get_db()

            for mid in message_ids[0].split():
                try:
                    status, msg_data = conn.fetch(mid, '(RFC822)')
                    if status != 'OK':
                        continue
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    subject = msg.get('Subject', '')
                    from_addr = msg.get('From', '').strip()
                    if not _REMINDER_SUBJECT_RE.search(subject) or not from_addr:
                        continue

                    body = _get_email_body(msg)
                    if not body:
                        continue

                    address_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', from_addr)
                    if not address_match:
                        continue
                    sender_email = address_match.group(0)

                    patient = db.execute(
                        "SELECT id FROM patients WHERE email = ? AND COALESCE(is_deleted, 0) = 0",
                        (sender_email,),
                    ).fetchone()
                    if not patient:
                        patient = db.execute(
                            "SELECT p.id FROM patients p "
                            "JOIN users u ON u.patient_id = p.id AND u.role = 'patient' "
                            "WHERE u.email = ? AND COALESCE(p.is_deleted, 0) = 0",
                            (sender_email,),
                        ).fetchone()
                    if not patient:
                        continue

                    user = db.execute(
                        "SELECT id FROM users WHERE patient_id = ?", (patient['id'],)
                    ).fetchone()
                    if not user:
                        continue

                    admin = db.execute(
                        "SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1"
                    ).fetchone()
                    recipient_id = admin['id'] if admin else None

                    clean_body = _clean_email_body(body, max_length=2000)
                    db.execute(
                        'INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?)',
                        (user['id'], recipient_id, clean_body),
                    )
                    db.execute(
                        'INSERT INTO incoming_email (from_email, from_name, subject, body_text, message_id) '
                        'VALUES (?, ?, ?, ?, ?)',
                        (sender_email, from_addr[:200], subject[:500], clean_body,
                         msg.get('Message-ID', '')[:500]),
                    )
                    db.commit()
                    processed += 1
                except Exception:
                    app.logger.exception('Failed to process incoming email %s', mid)

        conn.logout()
        return processed

    except Exception:
        app.logger.exception('IMAP polling failed')
        return 0


def _get_email_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        return payload.decode('utf-8', errors='replace')
                    except Exception:
                        return payload.decode('latin-1', errors='replace')
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                return payload.decode('utf-8', errors='replace')
            except Exception:
                return payload.decode('latin-1', errors='replace')
    return ''


def _clean_email_body(body, max_length=2000):
    body = body.strip()
    lines = body.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('>'):
            continue
        if 'On ' in stripped and 'wrote:' in stripped:
            break
        if stripped.startswith('--'):
            break
        if stripped.startswith('__'):
            break
        cleaned.append(stripped)
    text = '\n'.join(c for c in cleaned if c).strip()
    return text[:max_length]
