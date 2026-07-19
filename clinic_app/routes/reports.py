import json
from datetime import datetime, date, timedelta
from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from clinic_app.models import get_db

reports_bp = Blueprint('reports', __name__, url_prefix='/admin')


def _to_dicts(rows):
    if rows is None:
        return None
    if hasattr(rows, 'fetchall'):
        rows = rows.fetchall()
    if isinstance(rows, list):
        return [dict(r) for r in rows]
    return dict(rows) if rows else {}


@reports_bp.route('/reports')
@login_required
def financial_reports():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    today = date.today()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    # Monthly revenue
    monthly_revenue = db.execute('''
        SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count
        FROM receipts
        WHERE status = 'paid' AND created_at >= ? AND created_at < ?
    ''', (month_start.isoformat(), next_month.isoformat())).fetchone()

    # Outstanding balance
    outstanding = db.execute('''
        SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count
        FROM receipts
        WHERE status != 'paid' AND status != 'cancelled'
    ''').fetchone()

    # Revenue by payment method
    by_payment = db.execute('''
        SELECT COALESCE(payment_method, 'unknown') AS method, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total
        FROM receipts WHERE status = 'paid' AND created_at >= ? AND created_at < ?
        GROUP BY payment_method ORDER BY total DESC
    ''', (month_start.isoformat(), next_month.isoformat())).fetchall()

    # Revenue by service type
    by_service = db.execute('''
        SELECT COALESCE(st.name, ri.description, 'Other') AS name, COUNT(*) AS count, COALESCE(SUM(ri.line_total), 0) AS total
        FROM receipt_items ri
        JOIN receipts r ON r.id = ri.receipt_id
        LEFT JOIN service_types st ON st.id = ri.service_type_id
        WHERE r.status = 'paid' AND r.created_at >= ? AND r.created_at < ?
        GROUP BY st.name, ri.description ORDER BY total DESC
    ''', (month_start.isoformat(), next_month.isoformat())).fetchall()

    # Top patients by spending this month
    top_patients = db.execute('''
        SELECT p.name, COUNT(*) AS receipt_count, COALESCE(SUM(r.amount), 0) AS total
        FROM receipts r
        JOIN patients p ON p.id = r.patient_id
        WHERE r.status = 'paid' AND r.created_at >= ? AND r.created_at < ?
        GROUP BY p.id ORDER BY total DESC LIMIT 10
    ''', (month_start.isoformat(), next_month.isoformat())).fetchall()

    # Monthly revenue history (last 12 months)
    revenue_history = db.execute('''
        SELECT strftime('%Y-%m', created_at) AS month, COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count
        FROM receipts WHERE status = 'paid'
        GROUP BY month ORDER BY month DESC LIMIT 12
    ''').fetchall()

    return render_template('reports_financial.html',
        month_start=month_start,
        monthly_revenue=dict(monthly_revenue),
        outstanding=dict(outstanding),
        by_payment=_to_dicts(by_payment),
        by_service=_to_dicts(by_service),
        top_patients=_to_dicts(top_patients),
        revenue_history=_to_dicts(list(reversed(revenue_history))),
    )


@reports_bp.route('/analytics')
@login_required
def clinic_analytics():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    today = date.today()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    # Sessions this month
    sessions_this_month = db.execute('''
        SELECT COUNT(*) AS count FROM appointments
        WHERE status = 'completed' AND appointment_date >= ? AND appointment_date < ?
    ''', (month_start.isoformat(), next_month.isoformat())).fetchone()['count']

    sessions_last_month = db.execute('''
        SELECT COUNT(*) AS count FROM appointments
        WHERE status = 'completed' AND appointment_date >= ? AND appointment_date < ?
    ''', (last_month_start.isoformat(), month_start.isoformat())).fetchone()['count']

    # New patients this month
    new_patients = db.execute('''
        SELECT COUNT(*) AS count FROM patients
        WHERE COALESCE(is_deleted, 0) = 0 AND created_at >= ? AND created_at < ?
    ''', (month_start.isoformat(), next_month.isoformat())).fetchone()['count']

    # Active patients (had sessions this month)
    active_patients = db.execute('''
        SELECT COUNT(DISTINCT patient_id) AS count FROM appointments
        WHERE status = 'completed' AND appointment_date >= ? AND appointment_date < ?
    ''', (month_start.isoformat(), next_month.isoformat())).fetchone()['count']

    # Total patients
    total_patients = db.execute('''
        SELECT COUNT(*) AS count FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
    ''').fetchone()['count']

    # No-show rate this month
    total_appts = db.execute('''
        SELECT COUNT(*) AS count FROM appointments
        WHERE appointment_date >= ? AND appointment_date < ?
    ''', (month_start.isoformat(), next_month.isoformat())).fetchone()['count']
    no_shows = db.execute('''
        SELECT COUNT(*) AS count FROM appointments
        WHERE status = 'no_show' AND appointment_date >= ? AND appointment_date < ?
    ''', (month_start.isoformat(), next_month.isoformat())).fetchone()['count']
    no_show_rate = round((no_shows / total_appts * 100), 1) if total_appts > 0 else 0

    # Patient status distribution
    status_dist = db.execute('''
        SELECT status, COUNT(*) AS count FROM patients
        WHERE COALESCE(is_deleted, 0) = 0
        GROUP BY status ORDER BY count DESC
    ''').fetchall()

    # Sessions by month (last 12 months)
    sessions_history = db.execute('''
        SELECT strftime('%Y-%m', appointment_date) AS month, COUNT(*) AS count
        FROM appointments WHERE status IN ('completed', 'scheduled')
        GROUP BY month ORDER BY month DESC LIMIT 12
    ''').fetchall()

    # Average sessions per patient (among active patients)
    avg_sessions = db.execute('''
        SELECT ROUND(AVG(cnt), 1) AS avg FROM (
            SELECT COUNT(*) AS cnt FROM appointments WHERE status = 'completed'
            GROUP BY patient_id
        )
    ''').fetchone()['avg'] or 0

    # Assessment improvement (PHQ-9 average improvement between first and last)
    assessment_improvement = db.execute('''
        SELECT at.name, ROUND(first_score - last_score, 1) AS improvement
        FROM (
            SELECT a.assessment_type_id,
                   (SELECT a2.total_score FROM assessments a2
                    WHERE a2.patient_id = a.patient_id AND a2.assessment_type_id = a.assessment_type_id
                    ORDER BY a2.taken_at ASC LIMIT 1) AS first_score,
                   (SELECT a3.total_score FROM assessments a3
                    WHERE a3.patient_id = a.patient_id AND a3.assessment_type_id = a.assessment_type_id
                    ORDER BY a3.taken_at DESC LIMIT 1) AS last_score
            FROM assessments a GROUP BY a.patient_id, a.assessment_type_id
            HAVING COUNT(*) >= 2
        )
        JOIN assessment_types at ON at.id = assessment_type_id
        WHERE first_score IS NOT NULL AND last_score IS NOT NULL
        GROUP BY at.name
        ORDER BY improvement DESC
    ''').fetchall()

    # Meeting type distribution
    meeting_types = db.execute('''
        SELECT COALESCE(meeting_type, 'in-person') AS type, COUNT(*) AS count
        FROM appointments WHERE appointment_date >= ? AND appointment_date < ?
        GROUP BY meeting_type ORDER BY count DESC
    ''', (month_start.isoformat(), next_month.isoformat())).fetchall()

    # Monthly patient additions (last 12 months)
    patient_additions = db.execute('''
        SELECT strftime('%Y-%m', created_at) AS month, COUNT(*) AS count
        FROM patients WHERE COALESCE(is_deleted, 0) = 0
        GROUP BY month ORDER BY month DESC LIMIT 12
    ''').fetchall()

    # Clinical trends: PHQ-9 / GAD-7 monthly averages (last 12 months)
    clinical_trends = db.execute('''
        SELECT at.name AS assessment_name,
               strftime('%Y-%m', a.taken_at) AS month,
               ROUND(AVG(a.total_score), 1) AS avg_score,
               COUNT(*) AS count
        FROM assessments a
        JOIN assessment_types at ON at.id = a.assessment_type_id
        WHERE a.taken_at >= date('now', '-12 months')
        GROUP BY at.name, month
        ORDER BY at.name, month
    ''').fetchall()

    # Patient engagement: sessions per patient distribution
    session_distribution = db.execute('''
        SELECT CASE
            WHEN cnt = 1 THEN '1'
            WHEN cnt BETWEEN 2 AND 5 THEN '2-5'
            WHEN cnt BETWEEN 6 AND 12 THEN '6-12'
            WHEN cnt BETWEEN 13 AND 24 THEN '13-24'
            ELSE '25+'
        END AS bucket, COUNT(*) AS patients
        FROM (SELECT patient_id, COUNT(*) AS cnt FROM appointments WHERE status = 'completed' GROUP BY patient_id)
        GROUP BY bucket ORDER BY MIN(cnt)
    ''').fetchall()

    return render_template('reports_analytics.html',
        month_start=month_start,
        sessions_this_month=sessions_this_month,
        sessions_last_month=sessions_last_month,
        new_patients=new_patients,
        active_patients=active_patients,
        total_patients=total_patients,
        no_show_rate=no_show_rate,
        total_appts=total_appts,
        no_shows=no_shows,
        status_dist=_to_dicts(status_dist),
        sessions_history=_to_dicts(list(reversed(sessions_history))),
        avg_sessions=avg_sessions,
        assessment_improvement=_to_dicts(assessment_improvement),
        meeting_types=_to_dicts(meeting_types),
        patient_additions=_to_dicts(list(reversed(patient_additions))),
        clinical_trends=_to_dicts(clinical_trends),
        session_distribution=_to_dicts(session_distribution),
    )


def register_reports_routes(app):
    app.register_blueprint(reports_bp)
