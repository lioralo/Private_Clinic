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
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font('Arial', '', r'C:\Windows\Fonts\arial.ttf', uni=True)
    pdf.add_font('Arial', 'B', r'C:\Windows\Fonts\arialbd.ttf', uni=True)
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, 'PRIVATE CLINIC SERVICE RECEIPT', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 6, f'Receipt #: {receipt["receipt_number"] or receipt["id"]}', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 6, f'Patient:   {patient_name}', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 6, f'Date:      {receipt["created_at"] or ""}', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 6, f'Status:    {receipt["status"] or "paid"}', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)
    col_w = [70, 15, 30, 30]
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(230, 230, 230)
    headers = ['Item', 'Qty', 'Price', 'Total']
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, align='C', fill=True)
    pdf.ln()
    pdf.set_font('Arial', '', 9)
    for it in items:
        name = (it['service_name'] or it['description'] or f'Item #{it["id"]}')[:40]
        pdf.cell(col_w[0], 6, name, border=1)
        pdf.cell(col_w[1], 6, str(it['quantity']), border=1, align='C')
        pdf.cell(col_w[2], 6, f'${it["unit_price"]:.2f}', border=1, align='R')
        pdf.cell(col_w[3], 6, f'${it["line_total"]:.2f}', border=1, align='R')
        pdf.ln()
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(col_w[0] + col_w[1] + col_w[2], 7, 'TOTAL', border=1, align='R')
    pdf.cell(col_w[3], 7, f'${receipt["amount"]:.2f}', border=1, align='R')
    pdf.ln(10)
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 6, 'Thank you for choosing our clinic.', new_x='LMARGIN', new_y='NEXT', align='C')

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

    count = db.execute('SELECT COUNT(*) as c FROM receipts').fetchone()['c']
    receipt_number = f'RCPT-{count + 1:06d}'

    try:
        cur = db.execute(
            'INSERT INTO receipts (patient_id, amount, description, receipt_number, status) VALUES (?, ?, ?, ?, ?)',
            (patient_id, total, f'{len(items)} item(s)', receipt_number, 'paid')
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

        client_name = doc.get('clientName', 'Unknown')
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

        amount = float(doc.get('total', 0) or 0)
        description = doc.get('description', '') or f'Morning doc #{doc.get("number", doc_id[:8])}'
        receipt_number = doc.get('number', doc_id[:8])

        cur = db.execute(
            '''INSERT INTO receipts (patient_id, amount, description, receipt_number, status,
                morning_doc_id, morning_sync_status, morning_synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (patient_id, amount, description, receipt_number, 'paid',
             doc_id, 'synced', datetime.now().isoformat())
        )
        receipt_id = cur.lastrowid

        income_items = doc.get('incomeItems', []) or doc.get('items', []) or []
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
        result = client.create_document(
            client_name=patient['name'],
            items=income_items,
            client_email=patient.get('email') or None,
            client_phone=patient.get('phone') or None,
            notes=receipt['description'] or '',
            doc_type=305,
        )
        morning_id = result.get('id', '')
        db.execute(
            '''UPDATE receipts SET morning_doc_id = ?, morning_sync_status = 'synced',
               morning_synced_at = ? WHERE id = ?''',
            (morning_id, datetime.now().isoformat(), receipt_id)
        )
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

            client_name = doc.get('clientName', 'Unknown')
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

            amount = float(doc.get('total', 0) or 0)
            description = doc.get('description', '') or f'Morning #{doc.get("number", doc_id[:8])}'
            receipt_number = doc.get('number', doc_id[:8])

            cur = db.execute(
                '''INSERT INTO receipts (patient_id, amount, description, receipt_number, status,
                    morning_doc_id, morning_sync_status, morning_synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (patient_id, amount, description, receipt_number, 'paid',
                 doc_id, 'synced', datetime.now().isoformat())
            )
            receipt_id = cur.lastrowid

            income_items = doc.get('incomeItems', []) or doc.get('items', []) or []
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
