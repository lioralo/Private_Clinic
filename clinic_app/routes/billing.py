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
    flash(f'Receipt {receipt_number} created for ${total:.2f}.')
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
