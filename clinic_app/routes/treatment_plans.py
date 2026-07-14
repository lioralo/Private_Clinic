import json
from datetime import datetime, date
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from clinic_app.models import get_db
from clinic_app.utils import parse_date_safe

treatment_plans_bp = Blueprint('treatment_plans', __name__, url_prefix='/treatment-plans')


def _get_plan_with_goals(db, plan_id):
    plan = db.execute('SELECT * FROM treatment_plans WHERE id = ?', (plan_id,)).fetchone()
    if not plan:
        return None, []
    goals = db.execute('SELECT * FROM treatment_plan_goals WHERE plan_id = ? ORDER BY goal_number ASC',
                       (plan_id,)).fetchall()
    return dict(plan), [dict(g) for g in goals]


def _patient_has_active_plan(db, patient_id):
    plan = db.execute(
        "SELECT id FROM treatment_plans WHERE patient_id = ? AND status = 'active' LIMIT 1",
        (patient_id,)).fetchone()
    return plan['id'] if plan else None


@treatment_plans_bp.route('/patient/<int:patient_id>')
@login_required
def view_patient_plans(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    patient = db.execute('SELECT id, name FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0',
                         (patient_id,)).fetchone()
    if not patient:
        flash('Patient not found.')
        return redirect(url_for('patients'))
    plans = db.execute('SELECT * FROM treatment_plans WHERE patient_id = ? ORDER BY created_date DESC',
                       (patient_id,)).fetchall()
    return render_template('treatment_plan_view.html', patient=patient, plans=[dict(p) for p in plans])


@treatment_plans_bp.route('/patient/<int:patient_id>/create', methods=['GET', 'POST'])
@login_required
def create_plan(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    patient = db.execute('SELECT id, name FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0',
                         (patient_id,)).fetchone()
    if not patient:
        flash('Patient not found.')
        return redirect(url_for('patients'))

    if request.method == 'POST':
        diagnosis_code = (request.form.get('diagnosis_code') or '').strip()
        diagnosis_description = (request.form.get('diagnosis_description') or '').strip()
        problem_statement = (request.form.get('problem_statement') or '').strip()
        strengths = (request.form.get('strengths') or '').strip()
        next_review_date = (request.form.get('next_review_date') or '').strip() or None
        notes = (request.form.get('notes') or '').strip()

        db.execute('''
            INSERT INTO treatment_plans
                (patient_id, diagnosis_code, diagnosis_description, problem_statement,
                 strengths, next_review_date, notes, status, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', DATE('now'))
        ''', (patient_id, diagnosis_code, diagnosis_description, problem_statement,
              strengths, next_review_date, notes))

        plan_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

        goal_descriptions = request.form.getlist('goal_description[]')
        objectives_list = request.form.getlist('objectives[]')
        interventions_list = request.form.getlist('interventions[]')
        target_dates = request.form.getlist('target_date[]')

        for i in range(len(goal_descriptions)):
            desc = (goal_descriptions[i] or '').strip()
            if not desc:
                continue
            obj = (objectives_list[i] if i < len(objectives_list) else '')
            inter = (interventions_list[i] if i < len(interventions_list) else '')
            td = (target_dates[i] if i < len(target_dates) else '') or None
            db.execute('''
                INSERT INTO treatment_plan_goals
                    (plan_id, goal_number, goal_description, objectives, interventions, target_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (plan_id, i + 1, desc, obj, inter, td))

        db.commit()
        flash('Treatment plan created with SMART goals.')
        return redirect(url_for('treatment_plans.view_patient_plans', patient_id=patient_id))

    return render_template('treatment_plan_form.html', patient=patient, plan=None, goals=[])


@treatment_plans_bp.route('/<int:plan_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_plan(plan_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    plan, goals = _get_plan_with_goals(db, plan_id)
    if not plan:
        flash('Treatment plan not found.')
        return redirect(url_for('patients'))
    patient = db.execute('SELECT id, name FROM patients WHERE id = ?', (plan['patient_id'],)).fetchone()

    if request.method == 'POST':
        diagnosis_code = (request.form.get('diagnosis_code') or '').strip()
        diagnosis_description = (request.form.get('diagnosis_description') or '').strip()
        problem_statement = (request.form.get('problem_statement') or '').strip()
        strengths = (request.form.get('strengths') or '').strip()
        status = (request.form.get('status') or 'active').strip()
        next_review_date = (request.form.get('next_review_date') or '').strip() or None
        notes = (request.form.get('notes') or '').strip()

        db.execute('''
            UPDATE treatment_plans SET
                diagnosis_code=?, diagnosis_description=?, problem_statement=?,
                strengths=?, status=?, next_review_date=?, notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        ''', (diagnosis_code, diagnosis_description, problem_statement,
              strengths, status, next_review_date, notes, plan_id))

        try:
            db.execute('DELETE FROM treatment_plan_goals WHERE plan_id = ?', (plan_id,))

            goal_descriptions = request.form.getlist('goal_description[]')
            objectives_list = request.form.getlist('objectives[]')
            interventions_list = request.form.getlist('interventions[]')
            target_dates = request.form.getlist('target_date[]')
            goal_statuses = request.form.getlist('goal_status[]')
            progress_pcts = request.form.getlist('progress_percentage[]')

            for i in range(len(goal_descriptions)):
                desc = (goal_descriptions[i] or '').strip()
                if not desc:
                    continue
                obj = (objectives_list[i] if i < len(objectives_list) else '')
                inter = (interventions_list[i] if i < len(interventions_list) else '')
                td = (target_dates[i] if i < len(target_dates) else '') or None
                gs = (goal_statuses[i] if i < len(goal_statuses) else 'active')
                pp = int(progress_pcts[i]) if i < len(progress_pcts) and progress_pcts[i].isdigit() else 0
                db.execute('''
                    INSERT INTO treatment_plan_goals
                        (plan_id, goal_number, goal_description, objectives, interventions,
                         target_date, status, progress_percentage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (plan_id, i + 1, desc, obj, inter, td, gs, pp))

            db.commit()
            flash('Treatment plan updated.', 'success')
        except Exception:
            db.rollback()
            flash('Error updating treatment plan. Please try again.', 'error')
        return redirect(url_for('treatment_plans.view_patient_plans', patient_id=plan['patient_id']))

    return render_template('treatment_plan_form.html', patient=patient, plan=plan, goals=goals)


@treatment_plans_bp.route('/<int:plan_id>/view')
@login_required
def view_plan(plan_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    plan, goals = _get_plan_with_goals(db, plan_id)
    if not plan:
        flash('Treatment plan not found.')
        return redirect(url_for('patients'))
    patient = db.execute('SELECT id, name FROM patients WHERE id = ?', (plan['patient_id'],)).fetchone()
    return render_template('treatment_plan_view.html', patient=patient, plans=[plan], focus_plan=plan, goals=goals)


@treatment_plans_bp.route('/<int:plan_id>/delete', methods=['POST'])
@login_required
def delete_plan(plan_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    plan = db.execute('SELECT id, patient_id FROM treatment_plans WHERE id = ?', (plan_id,)).fetchone()
    if not plan:
        return jsonify({'error': 'Not found'}), 404
    db.execute('DELETE FROM treatment_plan_goals WHERE plan_id = ?', (plan_id,))
    db.execute('DELETE FROM treatment_plans WHERE id = ?', (plan_id,))
    db.commit()
    flash('Treatment plan deleted.')
    return redirect(url_for('treatment_plans.view_patient_plans', patient_id=plan['patient_id']))


@treatment_plans_bp.route('/api/goal/<int:goal_id>/update-progress', methods=['POST'])
@login_required
def update_goal_progress(goal_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    goal = db.execute('SELECT id, plan_id FROM treatment_plan_goals WHERE id = ?', (goal_id,)).fetchone()
    if not goal:
        return jsonify({'error': 'Goal not found'}), 404
    body = request.get_json(force=True) or {}
    new_pct = body.get('progress_percentage')
    new_status = body.get('status')
    if new_pct is not None:
        try:
            new_pct = max(0, min(100, int(new_pct)))
            db.execute('UPDATE treatment_plan_goals SET progress_percentage=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                       (new_pct, goal_id))
        except (TypeError, ValueError):
            pass
    if new_status and new_status in ('active', 'in_progress', 'achieved', 'discontinued', 'revised'):
        db.execute('UPDATE treatment_plan_goals SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                   (new_status, goal_id))
    db.commit()
    return jsonify({'status': 'ok'})


def register_treatment_plan_routes(app):
    app.register_blueprint(treatment_plans_bp)
