import json
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from clinic_app.models import get_db

patients_bp = Blueprint('patients', __name__, url_prefix='/api/patients')


@patients_bp.route('/counts')
@login_required
def patient_counts():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    counts = db.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE(is_deleted, 0) = 0 AND status = 'ongoing' THEN 1 ELSE 0 END) AS ongoing,
            SUM(CASE WHEN COALESCE(is_deleted, 0) = 0 AND status IN ('candidate', 'waiting') THEN 1 ELSE 0 END) AS waiting,
            SUM(CASE WHEN COALESCE(is_deleted, 0) = 0 AND status = 'archived' THEN 1 ELSE 0 END) AS archived
        FROM patients
    """).fetchone()
    return jsonify({
        'total': counts['total'] or 0,
        'ongoing': counts['ongoing'] or 0,
        'waiting': counts['waiting'] or 0,
        'archived': counts['archived'] or 0,
    })


@patients_bp.route('/search')
@login_required
def patient_search():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    q = (request.args.get('q') or '').strip()
    if not q or len(q) < 2:
        return jsonify([])
    db = get_db()
    rows = db.execute("""
        SELECT id, name, status, patient_type, treatment_method
        FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
          AND name LIKE ?
        ORDER BY
            CASE status
                WHEN 'ongoing' THEN 1 WHEN 'candidate' THEN 2
                WHEN 'waiting' THEN 3 WHEN 'archived' THEN 4 ELSE 5
            END,
            name COLLATE NOCASE ASC
        LIMIT 20
    """, (f'%{q}%',)).fetchall()
    return jsonify([{
        'id': r['id'], 'name': r['name'],
        'status': r['status'], 'patient_type': r['patient_type'],
        'treatment_method': r['treatment_method'],
    } for r in rows])


@patients_bp.route('/bulk-status', methods=['POST'])
@login_required
def bulk_status():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.get_json() or {}
    patient_ids = data.get('patient_ids', [])
    status = data.get('status', '')
    if not patient_ids or status not in ('ongoing', 'candidate', 'waiting', 'archived'):
        return jsonify({'error': 'Invalid request'}), 400
    db = get_db()
    placeholders = ','.join('?' for _ in patient_ids)
    db.execute(f'UPDATE patients SET status = ? WHERE id IN ({placeholders})',
               [status] + patient_ids)
    db.commit()
    return jsonify({'success': True, 'updated': len(patient_ids)})


@patients_bp.route('/bulk-delete', methods=['POST'])
@login_required
def bulk_delete():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.get_json() or {}
    patient_ids = data.get('patient_ids', [])
    if not patient_ids:
        return jsonify({'error': 'Invalid request'}), 400
    db = get_db()
    placeholders = ','.join('?' for _ in patient_ids)
    db.execute(f'UPDATE patients SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})',
               patient_ids)
    db.commit()
    return jsonify({'success': True, 'deleted': len(patient_ids)})
