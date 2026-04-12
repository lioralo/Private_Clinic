"""
Patient Engagement Dashboard - Create via new route
Adds features to make the clinic system more engaging and interactive
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
    
    # Get patient info
    patient = db.execute(
        'SELECT * FROM patients WHERE id = ?', 
        (current_user.patient_id,)
    ).fetchone()
    
    if not patient:
        return redirect(url_for('patient_home'))
    
    # Get upcoming appointments
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
    
    # Get notes/progress
    recent_notes = db.execute('''
        SELECT * FROM notes
        WHERE patient_id = ?
        ORDER BY created_at DESC
        LIMIT 3
    ''', (current_user.patient_id,)).fetchall()
    
    # Get therapy goals
    goals = db.execute('''
        SELECT * FROM goals
        WHERE patient_id = ?
        AND status = 'active'
        ORDER BY created_at DESC
    ''', (current_user.patient_id,)).fetchall()
    
    # Calculate engagement metrics
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
    
    # Get zoom meetings count
    zoom_meetings = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND meeting_type IN ('zoom', 'google-meet')
    ''', (current_user.patient_id,)).fetchone()['count']
    
    engagement_data = {
        'total_appointments': total_appointments,
        'upcoming_appointments': len(upcoming_appointments),
        'days_since_last': days_since_last_session,
        'zoom_meetings': zoom_meetings,
        'active_goals': len(goals),
        'recent_notes': len(recent_notes)
    }
    
    return render_template('patient_dashboard.html',
        patient=patient,
        upcoming_appointments=upcoming_appointments,
        recent_notes=recent_notes,
        goals=goals,
        engagement=engagement_data
    )

@app.route('/api/appointments/upcoming')
@login_required
def api_upcoming_appointments():
    """API endpoint for upcoming appointments with meeting info"""
    db = get_db()
    
    today = datetime.now().date()
    appointments = db.execute('''
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
    for appt in appointments:
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
            'patient_name': appt['patient_name']
        })
    
    return jsonify(result)

@app.route('/api/engagement/stats')
@login_required
def api_engagement_stats():
    """Get engagement statistics for the patient"""
    db = get_db()
    
    total_appts = db.execute(
        'SELECT COUNT(*) as count FROM appointments WHERE patient_id = ?',
        (current_user.patient_id,)
    ).fetchone()['count']
    
    completed_appts = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND COALESCE(status, 'scheduled') = 'completed'
    ''', (current_user.patient_id,)).fetchone()['count']
    
    this_month_appts = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND strftime('%Y-%m', appointment_date) = strftime('%Y-%m', 'now')
    ''', (current_user.patient_id,)).fetchone()['count']
    
    online_appts = db.execute('''
        SELECT COUNT(*) as count FROM appointments
        WHERE patient_id = ?
        AND meeting_type IN ('zoom', 'google-meet')
    ''', (current_user.patient_id,)).fetchone()['count']
    
    return jsonify({
        'total_appointments': total_appts,
        'completed_appointments': completed_appts,
        'appointments_this_month': this_month_appts,
        'online_appointments': online_appts,
        'completion_rate': round((completed_appts / max(total_appts, 1)) * 100) if total_appts > 0 else 0
    })
