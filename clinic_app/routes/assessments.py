import json
from datetime import datetime, date
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from clinic_app.models import get_db

assessments_bp = Blueprint('assessments', __name__, url_prefix='/assessments')


def _get_assessment_types(db, only_active=True):
    query = 'SELECT * FROM assessment_types'
    if only_active:
        query += ' WHERE is_active = 1'
    return db.execute(query + ' ORDER BY name ASC').fetchall()


def _score_assessment(assessment_type, raw_scores):
    try:
        method = assessment_type.get('scoring_method', 'sum')
        interpretations = json.loads(assessment_type.get('interpretation_json', '[]'))
    except (json.JSONDecodeError, TypeError):
        return None, None, None

    scores = []
    for s in raw_scores:
        try:
            scores.append(int(s))
        except (TypeError, ValueError):
            scores.append(0)

    if method == 'sum':
        total = sum(scores)
    elif method == 'average':
        total = sum(scores) / max(len(scores), 1)
    else:
        total = sum(scores)

    severity_level = None
    interpretation = None
    for item in interpretations:
        r = item.get('range', [0, 999])
        if len(r) == 2 and r[0] <= total <= r[1]:
            severity_level = item.get('severity')
            interpretation = item.get('label')
            break

    return total, severity_level, interpretation


@assessments_bp.route('/patient/<int:patient_id>')
@login_required
def view_patient_assessments(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    patient = db.execute('SELECT id, name FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0',
                         (patient_id,)).fetchone()
    if not patient:
        flash('Patient not found.')
        return redirect(url_for('patients'))

    rows = db.execute('''
        SELECT a.*, at.name AS assessment_name, at.display_name AS assessment_display_name
        FROM assessments a
        JOIN assessment_types at ON at.id = a.assessment_type_id
        WHERE a.patient_id = ?
        ORDER BY a.taken_at DESC, a.id DESC
    ''', (patient_id,)).fetchall()

    assessments = []
    chart_data = {}
    for r in rows:
        d = dict(r)
        d['assessment_type_name'] = d['assessment_name']
        d['administered_date'] = d['taken_at']
        d['severity'] = d['severity_level']
        d['response_data'] = d.pop('raw_scores_json', '[]')
        try:
            d['answers'] = json.loads(d.get('answers_json', '{}') or '{}')
        except (json.JSONDecodeError, TypeError):
            d['answers'] = {}
        atype_name = d['assessment_name']
        assessments.append(d)
        if atype_name not in chart_data:
            chart_data[atype_name] = []
        if d['total_score'] is not None:
            chart_data[atype_name].append({
                'date': d['taken_at'],
                'score': d['total_score'],
                'severity': d['severity_level'] or '',
            })

    assessment_types = [dict(at) for at in _get_assessment_types(db)]

    return render_template('assessment_results.html',
                           patient=patient,
                           assessments=assessments,
                           chart_data=chart_data,
                           assessment_types=assessment_types)


@assessments_bp.route('/patient/<int:patient_id>/take', methods=['GET', 'POST'])
@login_required
def take_assessment(patient_id):
    if current_user.role != 'admin':
        return 'Unauthorized', 403
    db = get_db()
    patient = db.execute('SELECT id, name FROM patients WHERE id = ? AND COALESCE(is_deleted, 0) = 0',
                         (patient_id,)).fetchone()
    if not patient:
        flash('Patient not found.')
        return redirect(url_for('patients'))

    if request.method == 'POST':
        assessment_type_id = request.form.get('assessment_type_id')
        if not assessment_type_id:
            flash('Assessment type is required.')
            return redirect(url_for('assessments.take_assessment', patient_id=patient_id))

        atype = db.execute('SELECT * FROM assessment_types WHERE id = ?', (assessment_type_id,)).fetchone()
        if not atype:
            flash('Assessment type not found.')
            return redirect(url_for('assessments.take_assessment', patient_id=patient_id))

        # Load questions for this type
        questions = db.execute(
            'SELECT * FROM assessment_questions WHERE assessment_type_id = ? ORDER BY question_order',
            (assessment_type_id,)
        ).fetchall()

        notes = (request.form.get('notes') or '').strip()

        if questions:
            # Dynamic form: collect answers from question keys
            answers = {}
            raw_scores = []
            for q in questions:
                key = q['question_key']
                qtype = q['question_type']
                val = request.form.get(key, '')
                if isinstance(val, list):
                    val = ','.join(v for v in val if v)
                elif val is None:
                    val = ''
                # If "other" was selected and there's a free-text field, use that
                other_val = request.form.get(f'{key}_other', '')
                if other_val and other_val.strip():
                    if val:
                        val = f'{val}: {other_val.strip()}'
                    else:
                        val = other_val.strip()
                answers[key] = val
                # For scored types, try numeric extraction
                if qtype in ('radio', 'select'):
                    raw_scores.append(val)
                elif qtype == 'text':
                    raw_scores.append('0')
                else:
                    raw_scores.append('0')

            total, severity, label = _score_assessment(dict(atype), raw_scores)
            answers_json = json.dumps(answers, ensure_ascii=False)

            db.execute('''
                INSERT INTO assessments
                    (patient_id, assessment_type_id, admin_user_id, raw_scores_json,
                     total_score, severity_level, interpretation, notes, answers_json, taken_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, DATE('now'))
            ''', (patient_id, assessment_type_id, current_user.id,
                  json.dumps(raw_scores), total, severity, label,
                  notes or None, answers_json))
            db.commit()

            if atype['name'] == 'clinical_intake':
                flash(f'{atype["display_name"]} saved successfully.')
            else:
                flash(f'{atype["display_name"]} completed. Score: {total} ({label or "N/A"})')
        else:
            # Legacy: PHQ-9/GAD-7 without questions table entries
            num_questions = int(atype['num_questions'])
            raw_scores = []
            for i in range(num_questions):
                raw_scores.append(request.form.get(f'q_{i}', '0'))

            total, severity, label = _score_assessment(dict(atype), raw_scores)

            db.execute('''
                INSERT INTO assessments
                    (patient_id, assessment_type_id, admin_user_id, raw_scores_json,
                     total_score, severity_level, interpretation, notes, taken_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, DATE('now'))
            ''', (patient_id, assessment_type_id, current_user.id,
                  json.dumps(raw_scores), total, severity, label,
                  notes or None))
            db.commit()
            flash(f'{atype["display_name"]} completed. Score: {total} ({label or "N/A"})')

        return redirect(url_for('assessments.view_patient_assessments', patient_id=patient_id))

    assessment_types = [dict(at) for at in _get_assessment_types(db)]
    selected_type_id = request.args.get('type_id', '')

    from clinic_app.utils import ASSESSMENT_QUESTIONS, ASSESSMENT_OPTIONS
    return render_template('assessment_take.html',
                           patient=patient,
                           assessment_types=assessment_types,
                           selected_type_id=selected_type_id,
                           ASSESSMENT_QUESTIONS=ASSESSMENT_QUESTIONS,
                           ASSESSMENT_OPTIONS=ASSESSMENT_OPTIONS)


@assessments_bp.route('/api/patient/<int:patient_id>/progress')
@login_required
def assessment_progress_api(patient_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    assessment_name = request.args.get('type', 'PHQ-9')
    rows = db.execute('''
        SELECT a.taken_at, a.total_score, a.severity_level, a.interpretation
        FROM assessments a
        JOIN assessment_types at ON at.id = a.assessment_type_id
        WHERE a.patient_id = ? AND at.name = ?
        ORDER BY a.taken_at ASC
    ''', (patient_id, assessment_name)).fetchall()
    return jsonify({
        'assessment_type': assessment_name,
        'data': [{
            'date': r['taken_at'],
            'score': float(r['total_score']) if r['total_score'] is not None else None,
            'severity': r['severity_level'],
            'label': r['interpretation'],
        } for r in rows]
    })


@assessments_bp.route('/<int:assessment_id>/delete', methods=['POST'])
@login_required
def delete_assessment(assessment_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    assessment = db.execute('SELECT id, patient_id FROM assessments WHERE id = ?', (assessment_id,)).fetchone()
    if not assessment:
        return jsonify({'error': 'Not found'}), 404
    db.execute('DELETE FROM assessments WHERE id = ?', (assessment_id,))
    db.commit()
    flash('Assessment deleted.')
    return redirect(url_for('assessments.view_patient_assessments', patient_id=assessment['patient_id']))


@assessments_bp.route('/api/questions/<int:type_id>')
@login_required
def api_get_questions(type_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    questions = db.execute(
        'SELECT * FROM assessment_questions WHERE assessment_type_id = ? ORDER BY question_order',
        (type_id,)
    ).fetchall()
    return jsonify([dict(q) for q in questions])


def register_assessment_routes(app):
    app.register_blueprint(assessments_bp)
