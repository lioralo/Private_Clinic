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


billing_bp = Blueprint('billing', __name__)


@billing_bp.route('/patient/receipt/<int:receipt_id>/download')
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

    patient = db.execute('SELECT name FROM patients WHERE id = ?', (receipt['patient_id'],)).fetchone()
    patient_name = patient['name'] if patient else 'Unknown'

    items = db.execute('''
        SELECT ri.*, st.name as service_name
        FROM receipt_items ri
        LEFT JOIN service_types st ON ri.service_type_id = st.id
        WHERE ri.receipt_id = ?
        ORDER BY ri.id ASC
    ''', (receipt_id,)).fetchall()

    from fpdf import FPDF
    import os as _os

    from clinic_app.utils import get_site_settings
    settings = get_site_settings(db)
    clinic_name = settings.get('clinic_business_name', '') or 'Private Clinic'
    clinic_id = settings.get('clinic_business_id', '') or ''
    clinic_addr = settings.get('clinic_address', '') or ''
    clinic_phone = settings.get('clinic_phone', '') or ''
    clinic_email = settings.get('clinic_email', '') or ''
    vat_rate = float(receipt.get('vat_rate') or settings.get('clinic_vat_rate', 0) or 0)
    vat_amount = float(receipt.get('vat_amount') or 0)
    net_amount = float(receipt.get('net_amount') or receipt['amount'])
    payment_method = receipt.get('payment_method') or ''

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    font_path = _os.path.join(_os.path.dirname(__file__), '..', '..', 'static', 'fonts', 'DejaVuSans.ttf')
    font_path = _os.path.abspath(font_path)
    if not _os.path.exists(font_path):
        font_path = '/app/static/fonts/DejaVuSans.ttf'
    pdf.add_font('Sans', '', font_path, uni=True)
    pdf.add_font('Sans', 'B', font_path, uni=True)

    pdf.set_font('Sans', 'B', 14)
    pdf.cell(0, 8, clinic_name, new_x='LMARGIN', new_y='NEXT', align='R' if any('\u0590' <= c <= '\u05EA' for c in clinic_name) else 'L')
    pdf.set_font('Sans', '', 8)
    if clinic_id:
        pdf.cell(0, 5, f'{"ח.פ" if vat_rate > 0 else "עוסק פטור"}: {clinic_id}', new_x='LMARGIN', new_y='NEXT', align='R')
    if clinic_addr:
        pdf.cell(0, 5, clinic_addr, new_x='LMARGIN', new_y='NEXT', align='R')
    if clinic_phone or clinic_email:
        pdf.cell(0, 5, f'{clinic_phone}  |  {clinic_email}'.strip(' |'), new_x='LMARGIN', new_y='NEXT', align='R')
    pdf.ln(4)

    pdf.set_font('Sans', 'B', 18)
    title = 'קבלה / חשבונית מס' if vat_rate > 0 else 'קבלה'
    pdf.cell(0, 10, title, new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.ln(2)

    pdf.set_font('Sans', '', 9)
    pdf.cell(45, 6, 'מספר קבלה:', border=0)
    pdf.cell(0, 6, f'{receipt["receipt_number"] or receipt["id"]}', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(45, 6, f'{"לקוח" if any(c > "\u0590" for c in patient_name) else "Patient"}:', border=0)
    pdf.cell(0, 6, patient_name, new_x='LMARGIN', new_y='NEXT')
    pdf.cell(45, 6, 'תאריך:', border=0)
    pdf.cell(0, 6, f'{receipt["created_at"] or ""}', new_x='LMARGIN', new_y='NEXT')
    if payment_method:
        methods_he = {'cash': 'מזומן', 'credit': 'כרטיס אשראי', 'transfer': 'העברה בנקאית', 'bit': 'ביט', 'paypal': 'פייפאל', 'other': 'אחר'}
        pdf.cell(45, 6, 'אמצעי תשלום:', border=0)
        pdf.cell(0, 6, methods_he.get(payment_method, payment_method), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)

    col_w = [75, 15, 30, 30]
    pdf.set_font('Sans', 'B', 9)
    pdf.set_fill_color(230, 230, 230)
    headers = ['תיאור', 'כמות', 'מחיר', 'סה"כ']
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, align='C' if i > 0 else 'R', fill=True)
    pdf.ln()
    pdf.set_font('Sans', '', 9)
    for it in items:
        name = (it['service_name'] or it['description'] or f'פריט #{it["id"]}')[:45]
        pdf.cell(col_w[0], 6, name, border=1, align='R')
        pdf.cell(col_w[1], 6, str(it['quantity']), border=1, align='C')
        pdf.cell(col_w[2], 6, f'NIS {it["unit_price"]:.2f}', border=1, align='R')
        pdf.cell(col_w[3], 6, f'NIS {it["line_total"]:.2f}', border=1, align='R')
        pdf.ln()
    pdf.set_font('Sans', 'B', 10)

    if vat_rate > 0:
        label_w = col_w[0] + col_w[1] + col_w[2]
        pdf.cell(label_w, 7, 'סכום לפני מע"מ', border=1, align='R')
        pdf.cell(col_w[3], 7, f'NIS {net_amount:.2f}', border=1, align='R')
        pdf.ln()
        pdf.cell(label_w, 7, f'מע"מ ({int(vat_rate*100)}%)', border=1, align='R')
        pdf.cell(col_w[3], 7, f'NIS {vat_amount:.2f}', border=1, align='R')
        pdf.ln()

    pdf.cell(col_w[0] + col_w[1] + col_w[2], 7, 'סה"כ לתשלום', border=1, align='R')
    pdf.cell(col_w[3], 7, f'NIS {receipt["amount"]:.2f}', border=1, align='R')
    pdf.ln(8)

    pdf.set_font('Sans', '', 8)
    pdf.cell(0, 5, 'תודה שבחרתם בקליניקה שלנו.', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.cell(0, 5, 'מסמך זה הופק באמצעות מערכת מורנינג (Green Invoice)', new_x='LMARGIN', new_y='NEXT', align='C')

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    pdf.output(tmp.name)
    tmp.close()
    with open(tmp.name, 'rb') as f:
        pdf_bytes = f.read()
    os.unlink(tmp.name)
    filename = f'receipt_{receipt["receipt_number"] or receipt["id"]}.pdf'
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@billing_bp.route('/service_types/manage', methods=('GET', 'POST'))
@login_required
def manage_service_types():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        default_price = request.form.get('default_price', '').strip()
        description = request.form.get('description', '').strip()
        if name and default_price:
            db.execute('INSERT INTO service_types (name, description, default_price) VALUES (?, ?, ?)',
                       (name, description or None, float(default_price)))
            db.commit()
            flash(f'Service type "{name}" added.')
        else:
            flash('Name and price are required.')
        return redirect(url_for('.manage_service_types'))
    service_types = db.execute('SELECT * FROM service_types ORDER BY is_active DESC, name ASC').fetchall()
    return render_template('manage_service_types.html', service_types=service_types)


@billing_bp.route('/service_types/<int:service_id>/toggle', methods=('POST',))
@login_required
def toggle_service_type(service_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    db = get_db()
    st = db.execute('SELECT is_active FROM service_types WHERE id = ?', (service_id,)).fetchone()
    if st:
        new_val = 0 if st['is_active'] else 1
        db.execute('UPDATE service_types SET is_active = ? WHERE id = ?', (new_val, service_id))
        db.commit()
    return redirect(url_for('.manage_service_types'))


@billing_bp.route('/patient/<int:patient_id>/add_receipt', methods=('POST',))
@login_required
def add_receipt(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    service_type_ids = request.form.getlist('service_type_id[]')
    quantities = request.form.getlist('quantity[]')
    unit_prices = request.form.getlist('unit_price[]')
    descriptions = request.form.getlist('item_description[]')
    payment_method = (request.form.get('payment_method') or '').strip() or 'transfer'

    items = []
    total = 0.0
    for i in range(len(service_type_ids)):
        sid = service_type_ids[i].strip()
        qty = int(quantities[i] or 1)
        price = float(unit_prices[i] or 0)
        desc = (descriptions[i] or '').strip()
        if not sid or price <= 0:
            continue
        line_total = round(qty * price, 2)
        total += line_total
        items.append((sid, qty, price, line_total, desc))

    if not items:
        flash('At least one valid line item is required.')
        return redirect_to_patient_tab(patient_id, 'billing')

    total = round(total, 2)

    from clinic_app.utils import get_site_settings
    settings = get_site_settings(db)
    vat_rate = float(settings.get('clinic_vat_rate', 0) or 0)
    vat_amount = round(total * vat_rate, 2)
    net_amount = round(total - vat_amount, 2)

    count = db.execute('SELECT COUNT(*) as c FROM receipts').fetchone()['c']
    import datetime
    year = datetime.datetime.now().year
    receipt_number = f'{year}-{count + 1:05d}'

    try:
        cur = db.execute(
            '''INSERT INTO receipts (patient_id, amount, description, receipt_number, status,
                payment_method, net_amount, vat_rate, vat_amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (patient_id, total, f'{len(items)} item(s)', receipt_number, 'paid',
             payment_method, net_amount, vat_rate, vat_amount)
        )
        receipt_id = cur.lastrowid

        for sid, qty, price, line_total, desc in items:
            db.execute(
                'INSERT INTO receipt_items (receipt_id, service_type_id, quantity, unit_price, line_total, description) VALUES (?, ?, ?, ?, ?, ?)',
                (receipt_id, sid, qty, price, line_total, desc or None)
            )

        db.commit()
        flash(f'Receipt {receipt_number} created for ${total:.2f}.', 'success')
    except Exception:
        db.rollback()
        flash('Error creating receipt. Please try again.', 'error')
    return redirect_to_patient_tab(patient_id, 'billing')


def _update_appointment_status(appointment_id, status):
    db = get_db()
    appt = db.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,)).fetchone()
    if not appt:
        return None
    db.execute('UPDATE appointments SET status = ? WHERE id = ?', (status, appointment_id))
    db.execute(
        'INSERT INTO audit_logs (patient_id, action, details) VALUES (?, ?, ?)',
        (appt['patient_id'], 'appointment-status', f'Appointment {appointment_id} marked {status}')
    )
    db.commit()
    return appt


@billing_bp.route('/appointment/<int:appointment_id>/set_status', methods=['POST'])
@login_required
def set_appointment_status(appointment_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    status = (request.form.get('status') or '').strip()
    allowed_statuses = {'completed', 'no_show', 'scheduled', 'cancelled'}
    if status not in allowed_statuses:
        return "Invalid status", 400
    appt = _update_appointment_status(appointment_id, status)
    if not appt:
        return "Appointment not found", 404
    return redirect_to_patient_tab(appt['patient_id'], 'notes')


@billing_bp.route('/api/appointment/<int:appointment_id>/status', methods=['POST'])
@login_required
def api_set_appointment_status(appointment_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    status = (request.form.get('status') or '').strip()
    allowed_statuses = {'completed', 'no_show', 'scheduled', 'cancelled'}
    if status not in allowed_statuses:
        return jsonify({'error': 'Invalid status'}), 400
    appt = _update_appointment_status(appointment_id, status)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    return jsonify({
        'message': 'Appointment status updated.',
        'new_status': status,
        'patient_id': appt['patient_id']
    })


@billing_bp.route('/morning/pull', methods=['POST'])
@login_required
def pull_morning_documents():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    from clinic_app.morning_api import get_morning_client
    client = get_morning_client(db)
    if not client:
        flash('Morning API is not configured.', 'error')
        return redirect(url_for('admin.morning_settings'))

    try:
        docs, total = client.search_documents(page_size=100)
    except Exception as e:
        flash(f'Failed to pull from Morning: {str(e)[:100]}', 'error')
        return redirect(request.referrer or url_for('admin.morning_settings'))

    imported = 0
    skipped = 0
    for doc in docs:
        doc_id = doc.get('id', '')
        existing = db.execute(
            'SELECT id FROM receipts WHERE morning_doc_id = ?', (doc_id,)
        ).fetchone()
        if existing:
            skipped += 1
            continue

        client_data = doc.get('client', {}) or {}
        client_name = client_data.get('name') or doc.get('clientName', 'Unknown')
        patient = db.execute(
            "SELECT id FROM patients WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (client_name.strip(),)
        ).fetchone()
        if not patient:
            patient = db.execute(
                'INSERT INTO patients (name, status, patient_type) VALUES (?, ?, ?)',
                (client_name.strip(), 'candidate', 'private')
            )
            patient_id = patient.lastrowid
        else:
            patient_id = patient['id']

        amount = float(doc.get('amount', 0) or 0)
        description = doc.get('description', '') or f'Morning doc #{doc.get("number", doc_id[:8])}'
        receipt_number = doc.get('number', doc_id[:8])

        cur = db.execute(
            '''INSERT INTO receipts (patient_id, amount, description, receipt_number, status,
                morning_doc_id, morning_sync_status, morning_synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (patient_id, amount, description, receipt_number, 'paid',
             doc_id, 'synced', datetime.now().isoformat())
        )
        receipt_id = cur.lastrowid

        income_items = doc.get('income', []) or doc.get('incomeItems', []) or []
        for item in income_items:
            item_desc = item.get('description', '')
            item_price = float(item.get('price', 0) or 0)
            item_qty = int(item.get('quantity', 1) or 1)
            db.execute(
                '''INSERT INTO receipt_items (receipt_id, quantity, unit_price, line_total, description)
                   VALUES (?, ?, ?, ?, ?)''',
                (receipt_id, item_qty, item_price, round(item_qty * item_price, 2), item_desc)
            )
        imported += 1

    db.commit()
    flash(f'Imported {imported} receipts from Morning ({skipped} already synced).', 'success')
    return redirect(request.referrer or url_for('admin.morning_settings'))


@billing_bp.route('/patient/<int:patient_id>/morning/push', methods=['POST'])
@login_required
def push_receipt_to_morning(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    from clinic_app.morning_api import get_morning_client
    client = get_morning_client(db)
    if not client:
        flash('Morning API is not configured.', 'error')
        return redirect_to_patient_tab(patient_id, 'billing')

    receipt_id = request.form.get('receipt_id')
    if not receipt_id:
        flash('No receipt selected.', 'error')
        return redirect_to_patient_tab(patient_id, 'billing')

    receipt = db.execute('SELECT * FROM receipts WHERE id = ?', (receipt_id,)).fetchone()
    if not receipt:
        flash('Receipt not found.', 'error')
        return redirect_to_patient_tab(patient_id, 'billing')

    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()
    items = db.execute('SELECT * FROM receipt_items WHERE receipt_id = ?', (receipt_id,)).fetchall()
    income_items = []
    for item in items:
        income_items.append({
            'description': item['description'] or 'Service',
            'price': float(item['unit_price'] or 0),
            'quantity': int(item['quantity'] or 1),
        })

    try:
        result, client_id = client.create_document_with_client(
            client_name=patient['name'],
            items=income_items,
            client_email=patient['email'] or None,
            client_phone=patient['phone'] or None,
            notes=receipt['description'] or '',
            doc_type=300,
            signed=True,
        )
        morning_id = result.get('id', '')
        db.execute(
            '''UPDATE receipts SET morning_doc_id = ?, morning_sync_status = 'synced',
               morning_synced_at = ? WHERE id = ?''',
            (morning_id, datetime.now().isoformat(), receipt_id)
        )
        if client_id:
            db.execute('INSERT OR REPLACE INTO site_settings (setting_key, setting_value) VALUES (?, ?)',
                       (f'patient_{patient_id}_morning_client_id', client_id))
        db.commit()
        flash(f'Receipt pushed to Morning (doc #{result.get("number", morning_id[:8])}).', 'success')
    except Exception as e:
        flash(f'Failed to push to Morning: {str(e)[:100]}', 'error')

    return redirect_to_patient_tab(patient_id, 'billing')


@billing_bp.route('/patient/<int:patient_id>/morning/payment-request', methods=['POST'])
@login_required
def send_payment_request(patient_id):
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    from clinic_app.morning_api import get_morning_client
    client = get_morning_client(db)
    if not client:
        flash('Morning API is not configured.', 'error')
        return redirect_to_patient_tab(patient_id, 'billing')

    amount = (request.form.get('amount') or '').strip()
    description = (request.form.get('description') or '').strip()
    if not amount or not description:
        flash('Amount and description are required.', 'error')
        return redirect_to_patient_tab(patient_id, 'billing')

    patient = db.execute('SELECT * FROM patients WHERE id = ?', (patient_id,)).fetchone()

    try:
        result = client.create_payment_request(
            client_name=patient['name'],
            amount=float(amount),
            description=description,
            client_email=patient.get('email') or None,
        )
        flash(f'Payment request sent to {patient["name"]}.', 'success')
    except Exception as e:
        flash(f'Failed to send payment request: {str(e)[:100]}', 'error')

    return redirect_to_patient_tab(patient_id, 'billing')


@billing_bp.route('/admin/morning/pull-all', methods=['POST'])
@login_required
def pull_all_morning_pages():
    if current_user.role != 'admin':
        return "Unauthorized", 403

    db = get_db()
    from clinic_app.morning_api import get_morning_client
    client = get_morning_client(db)
    if not client:
        flash('Morning API is not configured.', 'error')
        return redirect(url_for('admin.morning_settings'))

    total_imported = 0
    total_skipped = 0
    page = 1
    while True:
        try:
            docs, total = client.search_documents(page=page, page_size=50)
        except Exception as e:
            flash(f'Pull failed at page {page}: {str(e)[:100]}', 'error')
            break
        if not docs:
            break

        for doc in docs:
            doc_id = doc.get('id', '')
            existing = db.execute(
                'SELECT id FROM receipts WHERE morning_doc_id = ?', (doc_id,)
            ).fetchone()
            if existing:
                total_skipped += 1
                continue

            client_data = doc.get('client', {}) or {}
            client_name = client_data.get('name') or doc.get('clientName', 'Unknown')
            patient = db.execute(
                "SELECT id FROM patients WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (client_name.strip(),)
            ).fetchone()
            if not patient:
                patient = db.execute(
                    'INSERT INTO patients (name, status, patient_type) VALUES (?, ?, ?)',
                    (client_name.strip(), 'candidate', 'private')
                )
                patient_id = patient.lastrowid
            else:
                patient_id = patient['id']

            amount = float(doc.get('amount', 0) or 0)
            description = doc.get('description', '') or f'Morning #{doc.get("number", doc_id[:8])}'
            receipt_number = doc.get('number', doc_id[:8])
            vat_amount = float(doc.get('vatAmount', 0) or 0)
            net_amount = float(doc.get('subTotal', amount - vat_amount) or amount)

            cur = db.execute(
                '''INSERT INTO receipts (patient_id, amount, description, receipt_number, status,
                    morning_doc_id, morning_sync_status, morning_synced_at,
                    net_amount, vat_amount, vat_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (patient_id, amount, description, receipt_number, 'paid',
                 doc_id, 'synced', datetime.now().isoformat(),
                 net_amount, vat_amount, float(doc.get('vatRate', 0) or 0))
            )
            receipt_id = cur.lastrowid

            income_items = doc.get('incomeItems', []) or doc.get('income', []) or []
            for item in income_items:
                item_desc = item.get('description', '')
                item_price = float(item.get('price', 0) or 0)
                item_qty = int(item.get('quantity', 1) or 1)
                db.execute(
                    '''INSERT INTO receipt_items (receipt_id, quantity, unit_price, line_total, description)
                       VALUES (?, ?, ?, ?, ?)''',
                    (receipt_id, item_qty, item_price, round(item_qty * item_price, 2), item_desc)
                )
            total_imported += 1

        if page >= (total // 50) + 1:
            break
        page += 1

    db.commit()
    flash(f'Pull complete — imported {total_imported}, skipped {total_skipped} already synced.', 'success')
    return redirect(url_for('admin.morning_settings'))


@billing_bp.route('/webhooks/morning', methods=['POST'])
def morning_webhook():
    """Receive payment notifications and document events from Morning webhooks."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'status': 'ignored'}), 200

    topic = request.headers.get('x-webhook-topic', '')
    doc_id = data.get('id') or data.get('documentId') or ''
    event = data.get('event') or data.get('type') or topic

    if not doc_id:
        return jsonify({'status': 'no_doc_id'}), 200

    db = get_db()
    receipt = db.execute(
        'SELECT id FROM receipts WHERE morning_doc_id = ?', (str(doc_id),)
    ).fetchone()

    if receipt:
        if 'payment/received' in topic or 'paid' in str(event).lower():
            db.execute(
                "UPDATE receipts SET status='paid', morning_synced_at=? WHERE id=?",
                (datetime.now().isoformat(), receipt['id'])
            )
            db.commit()

    return jsonify({'status': 'ok'}), 200

morning_webhook.is_csrf_exempt = True
