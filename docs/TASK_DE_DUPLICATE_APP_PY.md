# Task: De-duplicate `app.py`

**File:** `/home/lioraloni/Private_Clinic/app.py` (9,464 lines)

## Problem

`app.py` redefines **34 functions** that already exist in `clinic_app/routes/` files. Every bug fix must be applied in two places. For example, `_pull_group_gdoc_notes` was edited in both `google_docs.py:425` and `app.py:8298` during this session (2 copies of identical logic).

Additionally, `build_week_calendar_snapshot` is defined **twice within app.py itself** — at lines 5589 and 5928. The first definition is dead code (shadowed by the second).

## Current import chain

Functions from route files are already imported at app.py lines 273-315:

```python
# Line 282
from clinic_app.routes.calendar import (
    calendar_allowed_windows,
    build_recurrence_group_id,
    ...
)

# Line 301
from clinic_app.routes.google_docs import (
    _extract_google_doc_id,
    ...
    _pull_group_gdoc_notes,
    ...
)
```

But app.py also has LOCAL definitions of these same functions that **shadow** the imports.

## Plan

### Step 1: Remove first `build_week_calendar_snapshot` (line 5589)

Delete lines **5589-5925** (337 lines). This function is defined again at line 5928 — the second definition wins. The inner helper functions (`_process_calendar_follow_ups`, `_process_calendar_appointments`, etc.) are all redefined as standalone functions in `clinic_app/routes/calendar.py` and already imported at line 282. There are no callers that reach the first definition.

**Grep to verify no remaining callers after removal:**
```bash
grep -n "build_week_calendar_snapshot" app.py  # should show line 5928 + line 5993
```

### Step 2: Remove second `build_week_calendar_snapshot` (line 5928)

Check if line 5928's implementation matches `clinic_app/routes/calendar.py:330`'s implementation. If so, remove the local definition and let callers use the imported one.

Read `clinic_app/routes/calendar.py:330` and compare with `app.py:5928`. If identical, delete `app.py:5928-6018` and update the one caller at line 5993:
```python
# Before:
snapshot = build_week_calendar_snapshot(db, target_week, proxy_user)
# After — should work without change since imported version has same signature
```

### Step 3: Remove Google Docs duplicates (lines 7879-8588)

These are 13 functions that are EXACT copies of their counterparts in `clinic_app/routes/google_docs.py`:

| app.py line | Function |
|-------------|----------|
| 7879 | `_pull_gdoc_notes` |
| 7985 | `_extract_google_doc_id` |
| 7994 | `_google_docs_dependency_error` |
| 8007 | `_extract_google_sheet_id` |
| 8015 | `_extract_google_activation_url` |
| 8029 | `_friendly_google_sheets_error` |
| 8053 | `_google_sheets_dependency_error` |
| 8061 | `_get_google_sheets_credentials` |
| 8082 | `_list_questionnaire_tabs` |
| 8113 | `_list_spreadsheet_tab_titles` |
| 8142 | `_create_diagnosee_questionnaires_sheet` |
| 8223 | `_copy_questionnaire_tabs_to_spreadsheet` |

Each is imported at lines 301-311. Delete all local definitions.

### Step 4: Remove group sync duplicates (lines 8298-8589)

These are the `_pull_group_gdoc_notes` function and its inner helpers:

| app.py line | Function |
|-------------|----------|
| 8298 | `_pull_group_gdoc_notes` |
| 8317 | `_normalize_person_name` |
| 8324 | `_normalize_meeting_title` |
| 8332 | `_extract_missing_reason` |
| 8345 | `_build_structured_summary` |
| 8349 | `_upsert_patient_group_note` |
| 8400 | `_apply_attendance_from_doc` |
| 8421 | `find_member` |
| 8482 | `_title_key_no_date` |
| 8588 | `_sync_group_gdoc_sessions` |

All imported at lines 301-315. Delete the entire block from line 8298 through 8589+rest of function. Verify the import at line 313 actually imports `_pull_group_gdoc_notes`.

### Step 5: Remove `smtp_health_check` (line 417)

The route version is in `clinic_app/routes/admin.py:1761` and imported at line 270. Delete `app.py:417-425`.

### Step 6: Remove `groups_dashboard` (line 6267)

This is a full route handler duplicate. The blueprint version is in `clinic_app/routes/calendar.py` (registered as `calendar_bp` at line 40 of app.py). Check if any URL rules in app.py route to `groups_dashboard` — likely it's just handled by the blueprint. Remove the local definition.

### Step 7: Remove `collect_public_available_slots` (line 5984)

Imported but also locally defined. Delete local definition.

### Step 8: Remove `_nearest_calendar_anchor_date` (line 6019)

Same — imported but locally defined.

### Step 9: Verify

After each step, check:
```bash
# No syntax errors
python3 -c "import app as _"

# Functions still accessible
python3 -c "from app import build_week_calendar_snapshot, _pull_group_gdoc_notes, groups_dashboard; print('OK')"
```

## Important guidelines

- **Start with Step 1 first** — it's the safest (dead code)
- **After each step, commit separately** — makes rollback easy
- **Don't touch the import section** (lines 40, 273-315) — those are correct
- **The `wrapper` function at line 391** is an inner function inside something else — leave it alone
- **Check callers before deleting** — some functions may be called from within app.py itself (e.g., `build_week_calendar_snapshot` is called at line 5993)
- **Expected reduction**: ~2,000 lines removed from app.py

## Current session's baseline

The latest commit is `ab986e1` on `main`. All edits to `_pull_group_gdoc_notes` in this session were applied to BOTH `app.py` and `google_docs.py`. After de-duplication, `google_docs.py` becomes the sole source of truth.
