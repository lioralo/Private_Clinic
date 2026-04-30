# Intake Debug and Merge Notes (2026-04-30)

## Scope
- Intake filing/submission regression debug
- Intake section editability verification
- DOCX export verification
- Merge-readiness cleanup

## Code Areas Reviewed
- `app.py`
  - `intake_data_from_request(...)`
  - `update_patient_info(...)`
  - `export_patient_intake_docx(...)`
- `templates/patient_detail.html`
  - intake tabbed section rendering
  - client-side intake pane switch logic
- `tests/test_app.py`
  - intake save/edit/export coverage
  - partial-update preservation regression test

## New Regression Guard
- Added test: `test_intake_partial_update_preserves_existing_fields`
- Verifies that posting only a subset of `intake_*` fields updates those fields while preserving previously stored values for untouched fields.

## Validation Commands and Results
1. Targeted intake tests

```bash
python -m unittest -v \
  tests.test_app.ClinicTestCase.test_intake_form_save_edit_and_export_docx \
  tests.test_app.ClinicTestCase.test_intake_partial_update_preserves_existing_fields \
  tests.test_app.ClinicTestCase.test_legacy_plain_text_intake_can_be_loaded_edited_and_exported
```

- Result: PASS (3/3)

2. Full suite

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

- Result: PASS (162 tests)

3. Root-level regression modules

```bash
python -m unittest -v test_export_data test_import_clinic_data test_google_calendar
```

- Result: PASS (13 tests)

## Merge Readiness
- Removed transient DB binary drift from test runs (`clinic.db`).
- Remaining intentional modified files:
  - `app.py`
  - `templates/patient_detail.html`
  - `tests/test_app.py`
  - `CHANGES.md`

## Recommended Merge Commit Message
`fix(intake): preserve fields on partial updates, restore full tabbed editing, and add regression coverage`
