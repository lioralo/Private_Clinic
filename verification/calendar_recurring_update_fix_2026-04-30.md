# Calendar Recurring Update Fix (2026-04-30)

## Reported Issue
When editing a recurring event and choosing scope:
- "This and all upcoming" or
- "All meetings in series"

clicking Save appeared to do nothing.

## Root Cause
The recurring scope chooser (`showScopeModal`) re-rendered the same modal body, replacing edit inputs. The save callback then attempted to read values from removed DOM elements (`editMeetingDate`, `editMeetingTime`, etc.), so the request payload build failed before `fetch` could execute.

## Fix Applied
File: `templates/calendar.html`

- In `openAppointmentEditor -> submitAppointmentEdit()`:
  - Snapshot edit form values before opening scope dialog.
  - Build request payload from snapshot values rather than querying current DOM.
  - Add input existence guard with explicit save-failed modal.
  - Add `.catch(...)` on scope flow to avoid silent failures.

## Validation
Executed:

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest -v test_export_data test_import_clinic_data test_google_calendar
```

Result: all tests passed.

## Merge Notes
- Transient `clinic.db` test diff removed.
- Intentional change for this fix: `templates/calendar.html` (+ docs/changelog updates).
