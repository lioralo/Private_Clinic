"""
Patient Engagement Dashboard routes.

NOTE: This is a Flask blueprint route module, NOT a standalone script.
It registers routes (patient_dashboard, upcoming appointments API,
engagement stats API) when imported by the application.

To enable, import this module in app.py:
    from scripts.patient_engagement import *
"""

from flask import render_template, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import app, get_db

@app.route('/dashboard')
@login_required
def patient_dashboard():
    """Enhanced patient engagement dashboard with stats and insights"""
    db = get_db()

    if current_user.role == 'admin':
        return redirect(url_for('patients'))

    patient = db.execute(
        'SELECT * FROM patients WHERE id = ?',
        (current_user.patient_id,)
    ).fetchone()

    if not patient:
        return redirect(url_for('patient_home'))

    today = datetime.now().date()
    upcoming_appointments = db.execute('''
        SELECT * FROM appointments
        WHERE patient_id = ?
        AND appointment_date >= ?
        AND COALESCE(status, 'scheduled') = 'scheduled'
        ORDER BY appointment_date ASC, appointment_time ASC
        LIMIT 5
    ''', (current_user.patient_id, today.isoformat())).fetchall()
    
    # Get total appointment count
    total_appointments = db.execute(
        'SELECT COUNT(*) as count FROM appointments WHERE patient_id = ?',
        (current_user.patient_id,)
    ).fetchone()['count']
    
    recent_notes = db.execute('''
        SELECT * FROM notes
        WHERE patient_id = ?
        ORDER BY created_at DESC
        LIMIT 3
    ''', (current_user.patient_id,)).fetchall()

    goals = db.execute('''
        SELECT * FROM goals
        WHERE patient_id = ? AND status = 'active'
        ORDER BY created_at DESC
    ''', (current_user.patient_id,)).fetchall()

    days_since_last_session = None
    if total_appointments > 0:
        last_appointment = db.execute('''
            SELECT appointment_date FROM appointments
            WHERE patient_id = ?
            ORDER BY appointment_date DESC
            LIMIT 1
        ''', (current_user.patient_id,)).fetchone()
        if last_appointment:
            last_date = datetime.fromisoformat(last_appointment['appointment_date']).date()
            days_since_last_session = (today - last_date).days

    zoom_meetings = db.execute('''
        SELECT COUNT(*) FROM appointments
        WHERE patient_id = ? AND meeting_type IN ('zoom', 'google-meet')
    ''', (current_user.patient_id,)).fetchone()[0]

    engagement_data = {
        'total_appointments': total_appointments,
        'upcoming_appointments': len(upcoming_appointments),
        'days_since_last': days_since_last_session,
        'zoom_meetings': zoom_meetings,
        'active_goals': len(goals),
        'recent_notes': len(recent_notes),
    }

    return render_template(
        'patient_dashboard.html',
        patient=patient,
        upcoming_appointments=upcoming_appointments,
        recent_notes=recent_notes,
        goals=goals,
        engagement=engagement_data,
    )

@app.route('/api/appointments/upcoming')
@login_required
def api_upcoming_appointments():
    """Return upcoming appointments with meeting info for the current patient."""
    db = get_db()
    today = datetime.now().date()
    rows = db.execute('''
        SELECT a.*, p.name as patient_name
        FROM appointments a
        LEFT JOIN patients p ON p.id = a.patient_id
        WHERE a.patient_id = ?
          AND a.appointment_date >= ?
          AND COALESCE(a.status, 'scheduled') = 'scheduled'
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
        LIMIT 10
    ''', (current_user.patient_id, today.isoformat())).fetchall()

    result = []
    for appt in rows:
        appt_date = datetime.fromisoformat(appt['appointment_date']).date()
        days_away = (appt_date - today).days
        result.append({
            'id': appt['id'],
            'date': appt['appointment_date'],
            'time': appt['appointment_time'],
            'days_away': days_away,
            'meeting_type': appt['meeting_type'] or 'in-person',
            'meeting_link': appt['meeting_link'],
            'is_today': days_away == 0,
            'is_tomorrow': days_away == 1,
            'patient_name': appt['patient_name'],
        })

    return jsonify(result)


@app.route('/api/engagement/stats')
@login_required
def api_engagement_stats():
    """Return engagement statistics for the current patient."""
    db = get_db()

    counts = db.execute('''
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE(status, 'scheduled') = 'completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN strftime('%Y-%m', appointment_date) = strftime('%Y-%m', 'now') THEN 1 ELSE 0 END) AS this_month,
            SUM(CASE WHEN meeting_type IN ('zoom', 'google-meet') THEN 1 ELSE 0 END) AS online
        FROM appointments
        WHERE patient_id = ?
    ''', (current_user.patient_id,)).fetchone()

    total = counts['total'] or 0
    completed = counts['completed'] or 0
    completion_rate = round((completed / max(total, 1)) * 100) if total > 0 else 0

    return jsonify({
        'total_appointments': total,
        'completed_appointments': completed,
        'appointments_this_month': counts['this_month'] or 0,
        'online_appointments': counts['online'] or 0,
        'completion_rate': completion_rate,
    })
