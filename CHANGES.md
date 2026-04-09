# Changes Documentation

---

## Test API Treatment Method Options Get

**Date:** April 09, 2026

**Objective:** Add a unit test for the `/api/treatment_method_options` GET endpoint.

**Release Summary:**
- Wrote a new test `test_api_treatment_method_options_get` in `test_app.py`.
- Tested the endpoint for correct unauthenticated redirects, patient 403 authorization failures, and successful 200 JSON payload responses for admins.
- Addressed test errors related to schema mismatch and role validation mismatch.
---

## Session 33

**Date:** April 4, 2026

**Objective:** CRM patient list redesign — treatment method tagging, table/cards view toggle, drag-to-reorder, cleaner badges, and treatment method filter.

**Release Summary:**

1. **Treatment Method Tag**
- Added `treatment_method TEXT` column to `patients` table via DB migration.
- Added `sort_order INTEGER` column to `patients` table for manual drag order.
- Added `treatment_method_options` table, seeded with: Psychodynamic, CBT, EFT, Management, 15 sessions, 3 sessions.
- Treatment method select field added to `add_patient` and `edit_patient` forms.

2. **CRM Filter Enhancement**
- `fetch_patients_by_status` now accepts a `treatment_method` filter parameter.
- Added `manual_order` sort option (by `sort_order` column, fallback to `created_at DESC`).
- Filter panel auto-expands when any active filter is set.
- Clear-filters button (×) added alongside Apply button.
- Patient count shown in the section header.

3. **CRM Table View**
- New `<table>` layout with columns: Name, Status, Type, Method, Next Appt, action button.
- Color-coded status dot (green/amber/grey) instead of text badge.
- Drag handle column visible only when `sort=manual_order` is active.
- Row click navigates to patient detail.

4. **CRM Cards View**
- Responsive CSS grid of compact patient cards (`crm-cards-grid`).
- Shows: name, self-booking icon (only when enabled), status dot, type badge, treatment method badge, next appointment, unread message count.

5. **View Toggle (Table ↔ Cards)**
- Toggle buttons in the toolbar switch between table and cards views.
- Preference persisted in `localStorage` across page loads.

6. **Drag-to-Reorder**
- SortableJS loaded from CDN only when `sort=manual_order` is active.
- Dragging rows (table) or cards saves order via `POST /api/patients/reorder`.
- Drag handle cursor on table rows; free-drag on cards.

7. **Badge & Display Cleanup**
- Removed patient `#id` number from all CRM rows.
- Removed "Self-booking OFF" badge; self-booking shown only as a small calendar ✓ icon when enabled.
- Add Patient shortcut button added to CRM header.

8. **New API Endpoints**
- `POST /api/patients/reorder` — saves drag-and-drop sort order.
- `GET /api/treatment_method_options` — lists current treatment method options.
- `POST /api/treatment_method_options` — adds a new option.
- `DELETE /api/treatment_method_options/<id>` — removes an option.

9. **CSS Additions** (`static/style.css`)
- `.crm-filter-grid`, `.crm-view-btn`, `.crm-status-dot`, `.crm-type-badge`, `.crm-method-badge`
- `.crm-table-wrap`, `.crm-table`, `.crm-table-row`, `.crm-drag-handle`
- `.crm-cards-grid`, `.crm-patient-card`, `.crm-card-header`, `.crm-card-name`, `.crm-card-appt`

10. **Test Coverage**
- All 64 existing tests pass with no regressions.
- New features verified via targeted integration checks (migration, filter, sort, all API endpoints, CRM page render).

---

## Session 32

**Date:** April 2, 2026

**Objective:** Finalize calendar recurrence correctness, improve treatment-log editing ergonomics, enforce Hebrew textbox alignment, disable non-login autofill, move inactivity timeout to 5 minutes, and strengthen patient background summaries from prior notes.

**Release Summary:**

1. **Calendar Recurrence Reliability (Edit/Delete)**
- Removed duplicate recurrence scope selection from the recurring edit modal.
- Kept a single clear scope-choice dialog at action time for recurring edit and recurring delete.
- Hardened `scope=upcoming` update logic so split recurring rows in the same series are consistently truncated/deleted from the selected occurrence onward.
- Implemented `scope=all` update behavior over the full recurrence group (not only one anchor row), including conflict checks and consistent time/day updates.

2. **Regression Coverage Expanded**
- Added test ensuring recurring `scope=all` update correctly updates all split rows in the recurrence group.
- Existing recurring one/upcoming/delete tests continue passing.

3. **Treatment Log Editing UX**
- Expanded treatment-log current meeting content input to full width in the add-note form.
- Increased textarea height for both add-note and edit-note content fields for easier long-form writing.

4. **Hebrew Textbox Alignment Across Site**
- Added global RTL form-control/textbox alignment rules for `input`, `textarea`, and `select` elements (excluding non-textual control types).
- Ensures right-aligned editing experience throughout Hebrew UI pages.

5. **Autofill Policy (Login-Only Exception)**
- Added global frontend guard that disables browser autocomplete/autocorrect/autocapitalize/spellcheck on non-login pages.
- Login endpoint is explicitly excluded so credential/OTP helper behavior remains available there.

6. **Inactivity Timeout Policy Updated**
- Changed default inactivity timeout to **5 minutes** (config + enforcement fallback).
- Updated inactivity-related tests to match the new 5-minute policy.

7. **Patient Background Suggestion Quality**
- Improved `build_patient_background_from_notes` output into a clearer structured clinical summary style.
- Added extraction of key summary points from recent/important note segments.
- Summary now emphasizes timeline, recurring patterns, current focus, and concise clinical takeaway based on historical entries.
- Added regression test validating structured summary sections are produced from note history.

**Validation & Debugging:**

1. Ran full automated test suite:
- `python test_app.py`
- Result: **59 tests passed**.

2. Verified no recurrence regressions in recurring edit/delete flows through existing and newly added tests.

**Files Modified:**
- `app.py`
- `templates/calendar.html`
- `templates/patient_detail.html`
- `templates/layout.html`
- `static/style.css`
- `test_app.py`
- `CHANGES.md`

---

## Session 30

**Date:** March 22, 2026

**Objective:** Fix recurring deletion behavior, finish profile localization, redesign groups manager flow, simplify calendar block handling, and normalize meeting data.

**Release Summary:**

1. **Recurring Delete Reliability Fixed**
- Added `appointments.recurrence_group_id` with migration/index support.
- Added grouping helpers to attach legacy recurring rows to stable logical series.
- Updated recurring create/split/update paths to preserve group identity.
- Fixed delete scope behavior so:
  - `all` removes the whole logical recurring series,
  - `upcoming` truncates and/or removes the correct related recurring rows.

2. **Regression Coverage Added**
- Extended tests for recurring series deletion edge-cases:
  - split recurring anchors without preexisting group ids,
  - upcoming-scope truncation across related anchors.
- Full suite verification passed: `python test_app.py`.

3. **Profile Hebrew Localization Completed**
- Added missing Hebrew keys for admin profile authenticator/password UI.
- Added missing Hebrew keys for patient home/profile portal text.

4. **Groups Manager UX Updated**
- Moved group-management controls from side-column layout into a top banner flow.
- Increased group description editing space.
- Session record section now presents status as a titled box above meeting content.
- Reordered member attendance row so `Notified` is adjacent to patient name.
- Missed-reason entry now uses a short prompt flow and appears only for missed status.
- Past/upcoming/next sections now appear as same-line tabs that replace each other.

5. **Calendar Simplification (Special -> Blocked)**
- Normalized backend block handling to treat `special` as `blocked`.
- Removed special-category controls from primary calendar UI.
- Updated block editor and save labels to blocked-only language.
- Simplified Zoom visual treatment to camera-icon presentation without separate color badge.

6. **Live Data Normalization Per Request**
- Created safety backup before cleanup:
  - `clinic.db.pre_user_cleanup_20260322_192614.bak`
- Applied cleanup in `clinic.db`:
  - converted special blocks to blocked,
  - removed all patient appointments,
  - left vacancy structures intact.
- Post-cleanup counts:
  - appointments: `0`
  - blocked_slots_special: `0`
  - blocked_slots_blocked: `111`
  - slots_override: `2`
  - vacancy_recurring: `6`

## Session 29

**Date:** March 21, 2026

**Objective:** Harden admin security, create a fresh full-data encrypted backup, and improve desktop/mobile usability.

**Release Summary:**

1. **Full Data Backup Confirmed**
- Created a fresh encrypted backup bundle: `secure_backups/clinic_20260321_100600.db.enc`.
- Backup bundle flow includes DB + local artifacts (`static/uploads`, `patients_logs`, and `app_log.txt`) for migration-safe restore.

2. **Admin Credentials + Security Upgrades**
- Default admin bootstrap/migration now targets username `lioraloni` with initial password `12345`.
- Added admin Google Authenticator flow using TOTP:
  - setup start,
  - QR/manual secret display,
  - verification,
  - optional disable.
- Login now supports 2-step verification for admin accounts with authenticator enabled.
- Added admin password-change endpoint requiring current password + valid authenticator code.
- Added `users` security fields in schema/migrations: `totp_secret`, `totp_enabled`, `force_password_change`.

3. **UI Improvements (Desktop + Mobile)**
- Expanded effective site width for desktop via shared app container sizing in layout.
- Improved mobile readability for patient records/file names.
- Added mobile read-mode behavior on patient detail screens that limits editing actions while preserving reading/navigation.

4. **Tests Updated And Verified**
- Updated app tests for new default admin credentials.
- Added security tests for TOTP second-step login.
- Test results:
  - `python test_security.py` passed (`5` tests)
  - `python test_app.py` passed (`50` tests)

## Session 28

## Session 31

**Date:** March 23, 2026

**Objective:** Implement 11 calendar and CRM improvements for enhanced booking and patient management functionality.

**Release Summary:**

1. **Patient Dropdown Organization**
  - Updated patient_options query to sort by patient_type then name.
  - Implemented Jinja2 optgroup grouping in calendar.html for organized dropdown display.
  - Patients grouped by status types (ongoing, candidate, archived) then clinic types.
  - Improves UX for selecting from large patient lists.

2. **Editable Booking Date and Time**
  - Added visible date input field (bookingDateInput) to booking panel.
  - Added visible time input field (bookingTimeInput) to booking panel.
  - Implemented JavaScript event listeners to sync visible fields with hidden form fields.
  - Updated setSelectedSlot() to synchronize both visible and hidden fields bidirectionally.
  - Allows admins to directly edit or adjust selected booking time without calendar re-selection.

3. **Recurring Event Deletion Fix**
  - Fixed api_calendar_appointment_delete route "upcoming" scope logic.
  - Updated to use recurring_occurrences_between() for proper series validation.
  - Now correctly truncates series to cutoff date vs deleting entire group.
  - Handles three scopes correctly: one (exclude), upcoming (truncate), all (delete).

4. **Meeting Type Options Update**
  - Changed meeting type options from [zoom, google-meet, in-person] to [online, in-person, phone].
  - Added conditional meeting link field visibility (only visible for "online" type).
  - Updated JavaScript to show/hide meeting link container based on selected type.

5. **Meeting Title → Meeting Remarks**
  - Renamed "Meeting Title" field to "Meeting Remarks" in calendar.html form.
  - Changed field name from meeting_title to meeting_remarks.
  - Set blank default placeholder (no pre-filled text).
  - Implemented backward compatibility fallback in api_calendar_book route.
  - Database still uses meeting_title column for existing data compatibility.

6. **Recurring Meeting Checkbox**
  - Added recurring checkbox (id: recurringCheckbox) to booking form.
  - Added conditional date picker (recurringDateWrap) that shows when recurring is enabled.
  - Implemented status-based defaults: ongoing=checked (auto-recurring), candidate/waiting=unchecked.
  - JavaScript event listener toggles date picker visibility on checkbox change.
  - Patient change handler updates checkbox state based on patient status.

7. **Backend Support for New Form Fields**
  - Updated api_calendar_book route to extract meeting_remarks from form.
  - Updated api_calendar_book to extract is_recurring checkbox value.
  - Updated api_calendar_book to extract recurrence_end_date from form input.
  - Implemented logic: form values override auto-detection based on patient status.
  - Default recurrence_end_date = anchor + 365 days if recurring enabled.

8. **CRM Filter Enhancement - Clinic Type**
  - Updated crm_dashboard route to accept clinic_type parameter.
  - Added validation for clinic_type: {all, private, residency, group}.
  - Stores clinic_type in session['crm_filters'] for persistence.
  - Updated template to pass clinic_type instead of patient_type.
  - Fixed all 4 summary strip URLs to use clinic_type parameter.
  - Allows filtering patients by clinic classification separately from status.

9. **"Other" Booking Type Option**
  - Added "other" option to bookingTypeSelect dropdown.
  - Added conditional input field (otherBookingTypeInput) for custom booking type entry.
  - JavaScript toggles input field visibility when "other" is selected.
  - Form submission validates custom booking type is not empty before submitting.
  - Custom type value submitted with form when booking_type="other".

10. **Group Page Dropdown UI Refactor**
   - Changed .group-side-accordion CSS from grid layout to flex column layout.
   - Updated to display: flex; flex-direction: column for full-width stacking.
   - Removed rounded corners (rounded-4 → rounded-0) for seamless accordion appearance.
   - Removed bottom margins (mb-3) for proper spacing in stacked layout.
   - Result: only one accordion section can expand at a time, spans full width.

11. **Dummy Patient Cleanup**
   - Soft-deleted dummy patients using is_deleted flag:
    - John (patient_id=18)
    - Dov Lev (patient_id=25)
    - Dirk Gently (patient_id=26)
   - Used soft-delete (is_deleted=1) to preserve referential integrity.
   - Existing queries filter out deleted patients via COALESCE(is_deleted, 0) = 0.

**Testing & Verification:**
- Python syntax validation: PASSED
- Flask app imports: PASSED
- Database schema verification: All required columns present
- Patient sorting query execution: PASSED (correct type+name ordering)
- Code review: All 11 features present and correctly implemented

**Files Modified:**
- app.py: Patient sorting query, api_calendar_book route, api_calendar_appointment_delete fix, crm_dashboard filter
- templates/calendar.html: Patient dropdown grouping, date/time inputs, meeting remarks, recurring checkbox, "other" type, meeting type options
- templates/crm.html: Clinic type filter dropdown and URL parameter updates
- templates/groups.html: Accordion CSS layout refactoring
- clinic.db: Soft-deletion of dummy patients

**Git Commit:**
- Hash: a6fd736
- Message: "Implement 11 calendar and CRM improvements"
- Status: Successfully pushed to origin/main

---
**Date:** March 17, 2026

**Objective:** Complete the latest patient-portal workflow pass for intake scheduling, patient-side meeting requests, and translation cleanup.

**Release Summary:**

1. **Intake And Diagnosee Booking Rules Updated**
- Kept `initial-intake` and `diagnosee` appointments non-recurring by default.
- Removed the forced deletion of existing scheduled meetings so additional one-time meetings can be booked when clinically needed.

2. **Patient Request Workflow Added**
- Added patient-side cancellation requests from the portal, including a required explanation.
- Added patient-side requests for another meeting / self-booking access from available slots.
- Both request types now create system-style chat messages for admin review and patient acknowledgment, and include audit log entries.

3. **Portal Translation And UX Cleanup**
- Localized the patient home page strings added in recent releases.
- Added the new request actions to the patient portal without breaking existing messaging, receipts, or shared-document sections.

**Validation:**

1. **Automated Tests**
- `python test_app.py` passed (`50` tests).
- `python test_security.py` passed (`3` tests).

2. **Targeted Smoke Check**
- Verified patient cancellation and booking-access requests return `200`, create chat messages, and write `patient-cancel-request` / `patient-booking-request` audit actions.

## Session 27

**Date:** March 16, 2026

**Objective:** Finalize the latest group-management release with a focused regression review and a concise release summary.

**Release Summary:**

1. **Group Lifecycle Controls Expanded**
- Added archive-vs-delete handling for groups.
- Added remove-vs-archive-vs-delete handling when removing a member from a group.

2. **Group Session Workspace Reworked**
- Reorganized the group detail page into collapsible management sections.
- Kept session records visible in presentation mode until the user explicitly presses edit.
- Expanded writing space for session summaries and member comments.
- Limited the default session list to the nearest upcoming and previous records, with show-all controls.

3. **Scheduling and Navigation Improved**
- Added recurring-series end selection by count or end date.
- Redirected newly created group sessions to the newest session record.
- Added direct calendar click-through from group sessions to the matching group-session record.

**Regression Review:**

1. **Automated Validation**
- Full suite: `python test_app.py` passed (`50` tests).
- Targeted group regression checks passed for:
  - group archive vs full delete,
  - member archive flow,
  - member full-delete flow,
  - calendar snapshot `detail_url` linking.

2. **Review Outcome**
- No regressions were found in the reviewed group-management and calendar handoff flows.
- The push on `main` reflects the reviewed state.

## Session 26

**Date:** March 16, 2026

**Objective:** Split group management into overview vs per-group sessions pages, and add collapsed-by-title behavior in booking panel sections.

**Changes Made:**

1. **Groups Overview vs Group Sessions Split**
- Added a dedicated overview template `groups_overview.html` for:
  - creating groups,
  - editing basic group metadata,
  - opening a specific group sessions workspace.
- Kept `/groups` focused on group list + metadata management.

2. **Single-Group Sessions Workspace**
- Reworked `groups.html` into a pure detail view for one group (`/groups/<id>`), including:
  - group info editing,
  - member management,
  - membership history date editing,
  - session scheduling and recurring setup,
  - session attendance/status/summary recording.

3. **Collapsible Session Regions**
- Converted group sessions display to accordion behavior so each session opens/collapses by clicking its title row.

4. **Booking Panel Collapsible Sections**
- Implemented title-triggered collapses in the Booking tab of `calendar.html`.
- Booking section card bodies now start hidden and expand/collapse by clicking the section title.

5. **Routing/Redirect Consistency for New Flow**
- Continued redirect hardening so group actions route back to per-group detail context where appropriate.

6. **Tests Updated and Verified**
- Updated group suggestion test to validate the new detail-page location for member suggestions.
- Verification:
  - `python test_app.py` passed (`46` tests),
  - `python test_security.py` passed (`3` tests).

## Session 25

**Date:** March 16, 2026

**Objective:** Refine group tab and group management so groups behave as ongoing treatment units with richer attendance controls and patient-card integration.

**Changes Made:**

1. **Group Membership Suggestions Restricted to Group Patients**
- Group member picker now suggests only patients where `patient_type='group'`.
- Backend now enforces this rule on add-member requests.

2. **Editable Group Join/Leave Dates**
- Added date editing for membership periods (`joined_date`, `left_date`) directly from:
  - group management history panel,
  - patient private card.
- Added synchronization logic so current active membership state remains consistent.

3. **Attendance: Missed + Notified Binary Flag**
- Added `notified_on_time` boolean on group attendance records.
- Group session recording now supports:
  - arrived/missed status,
  - missed reason,
  - notified-correctly checkbox,
  - per-patient attendance note.

4. **Patient Private Card Integration for Group Meetings**
- Added a dedicated **Group Participation** card in patient profile with:
  - private arrived counter,
  - attendance timeline per group meeting,
  - group-wide session summary visibility,
  - inline edit capability for attendance + summary from patient card.

5. **Missed Group Note De-duplication**
- Improved missed-group auto-note behavior to upsert by session marker instead of creating duplicates on repeated edits.

6. **Tests Added/Updated**
- Added/updated regression tests for:
  - group-only suggestion/enforcement,
  - membership date editing,
  - notified flag persistence,
  - patient-card attendance and summary editing.

## Session 24

**Date:** March 16, 2026

**Objective:** Expand group lifecycle management with historical membership tracking, recurring group meetings, attendance + missed-reason documentation, and individual missed-meeting documentation in treatment logs.

**Changes Made:**

1. **Group Membership History + Durations**
- Added persistent `group_member_history` tracking for join/leave cycles.
- Updated member add/remove logic to preserve historical periods while keeping current active membership.
- Added member-history UI in `groups` page showing joined date, left/active state, and days in group.

2. **Recurring Group Session Scheduling + Future-Series Updates**
- Added recurrence support when creating group sessions:
  - one-time,
  - weekly recurring,
  - interval in weeks,
  - count and/or end-date caps.
- Added `group_session_series` metadata and linked sessions via `series_id`.
- Enhanced group session update API to support:
  - single-session update,
  - apply-to-future updates for recurring series.

3. **Group Session Outcomes + Attendance Tracking**
- Added session outcome recording (`session_summary`, session status).
- Added attendance table `group_session_attendance` with per-member:
  - attendance status (pending/present/missed),
  - missed reason,
  - attendance note.
- Added session recording form in `groups` UI to capture what happened and who arrived/missed.

4. **Missed Meeting Documentation in Individual Treatment**
- Added treatment-log support for missed sessions with:
  - `is_missed_meeting`,
  - `missed_reason`.
- Updated create/edit note flows and patient detail UI to capture and display missed-session reasons.
- Group missed attendance now auto-creates an individual missed-meeting note for that patient.

5. **Schema + Migration Hardening**
- Updated `schema.sql` and `init_db()` migrations for new fields/tables/indexes:
  - `group_member_history`,
  - `group_session_series`,
  - `group_session_attendance`,
  - `group_sessions.series_id/occurrence_index/session_summary`,
  - `notes.is_missed_meeting/missed_reason`,
  - `appointments.missed_reason`.

6. **Automated Regression Coverage**
- Added tests for:
  - member history join/leave/rejoin periods,
  - recurring group session creation and future-series update,
  - attendance capture + missed reason + auto-created individual note,
  - individual missed-treatment note reason persistence.

## Session 23

**Date:** March 15, 2026

**Objective:** Fix intake tab placement so Summary and Intake sections render in the correct tabs for patient profiles.

**Root Cause:**
- The JavaScript tab relocation helper moves the element with id `intakeEvaluationFormBlock` into the Intake tab host.
- That id was incorrectly attached to the **Background** card, causing Background to appear under Intake.

**Changes Made:**

1. **Template ID Correction**
- In `templates/patient_detail.html`:
  - Removed `id="intakeEvaluationFormBlock"` from the Background card in Summary.
  - Assigned `id="intakeEvaluationFormBlock"` to the Intake Evaluation Form card (the one with DOCX export).

2. **Behavior After Fix**
- Summary tab keeps the Background section.
- Intake tab receives the Intake Evaluation Form block, including DOCX export button.

**Verification Performed:**
- Full app tests (`python test_app.py`).
- Security tests (`python test_security.py`).

**Result:**
- Tab content placement corrected with no functional regressions observed in automated tests.

## Session 22

**Date:** March 15, 2026

**Objective:** Apply deeper database performance hardening with zero feature changes.

**Changes Made:**

1. **Database Indexing Hardening**
- Added a conservative, idempotent index set in `init_db()` (`app.py`) for high-frequency query patterns.
- Added matching index declarations in `schema.sql` so new database setups are optimized immediately.

2. **Index Coverage Added**
- Patients filters: status/type with soft-delete flag.
- Users by `patient_id` lookup.
- Appointments by patient/date/time and status/date lookup patterns.
- Notes, receipts, files by `patient_id` + `created_at` sort/filter paths.
- Messages by recipient/read/timestamp and sender-recipient conversations.
- Calendar availability/blocks tables by date/time/status.
- Group membership/session lookup paths.
- Notifications unread sorting and goals by patient/status.

**Verification Performed:**
- Syntax compilation for app module.
- Full application tests (`python test_app.py`).
- Security tests (`python test_security.py`).

**Result:**
- No functional behavior changes introduced.
- Automated tests remained green after index hardening.

## Session 21

**Date:** March 15, 2026

**Objective:** Remove redundant script, improve runtime efficiency in CRM counts, and strengthen operational diagnostics while preserving behavior.

**Changes Made:**

1. **Removed Redundant Script**
- Deleted unused frontend script file `static/script.js`.
- Verified no template references were using this file.

2. **Import Cleanup in App Module**
- Removed duplicate top-level `jsonify` import from `app.py`.
- Removed redundant function-local imports of `json` and `Response` in export/import routes, using existing module-level imports instead.

3. **CRM Dashboard Query Optimization**
- Replaced four separate patient `COUNT(*)` queries with a single aggregated SQL query in `/crm` route.
- Preserved count semantics for:
  - all active patients,
  - ongoing,
  - candidate/waiting,
  - archived.

4. **Backup Robustness and Debug Visibility**
- Updated routine backup guard to log backup failures via Flask logger while continuing request processing.
- Behavior remains non-blocking for end users if backup execution fails.

**Verification Performed:**
- Syntax compilation check for `app.py`.
- Full app tests via `python test_app.py`.
- Security tests via `python test_security.py`.

**Result:**
- No behavioral regressions observed in automated verification.

## Session 20

**Date:** March 15, 2026

**Objective:** Continue localization pass 3 by reducing untranslated UI text in high-impact pages.

**Changes Made:**

1. **Admin Profile Localization**
- Converted static labels/buttons/messages in `templates/admin_profile.html` to translation helper calls.

2. **Legacy Open Booking Page Localization**
- Localized static text in `templates/open_booking.html`.
- Refactored JavaScript message localization to use `data-*` attributes, avoiding template syntax in JS and fixing diagnostics.

3. **Hebrew Dictionary Expansion**
- Added new keys in `translations/he.json` for admin profile and legacy open-booking text.

4. **Translation Audit Improvement**
- Regenerated `translation_audit.txt` and reduced remaining unmatched entries from `201` to `181`.

**Test Results:**
- `python test_app.py` passed (`36` tests).

## Session 19

**Date:** March 15, 2026

**Objective:** Add public available-slot self-booking by shareable link/email, enforce booking field requirements, and notify admin as pending patient.

**Changes Made:**

1. **Public Self-Booking Link Generation**
  - Added admin endpoint to create secure public booking links.
  - Added calendar admin UI controls to:
    - generate link,
    - copy link,
    - open prefilled email compose (`mailto`) for sharing.

2. **Public Available-Slots Booking Page**
  - Added new page: `templates/open_booking_calendar.html`.
  - Displays only available slots and allows public self-booking.

3. **Public Booking Validation Rules**
  - Enforced on backend:
    - name is required,
    - date of birth optional,
    - phone or email (at least one) required,
    - selected slot must still be available.

4. **Pending Patient + Notification Flow**
  - On successful public booking:
    - creates a new patient with `waiting` status,
    - creates one-time appointment,
    - updates one-time vacancy status when relevant,
    - inserts admin notification for follow-up.

5. **Data Model Additions**
  - Added `public_booking_links` table migration in `init_db`.

6. **Localization Support**
  - Added translation wrappers and Hebrew dictionary entries for new public-link feature text.

7. **Tests Added**
  - Added regression tests for:
    - missing phone/email rejection,
    - successful public booking creating waiting patient, appointment, and notification.

**Test Results:**
- `python test_app.py` passed (`36` tests).

## Session 18

**Date:** March 15, 2026

**Objective:** Run a second Hebrew localization sweep focused on the calendar page and reduce remaining English UI strings.

**Changes Made:**

1. **Calendar Template Localization Sweep**
  - Localized additional static labels/buttons/placeholders in `templates/calendar.html`.
  - Added translation wrappers for booking management section labels and headers.

2. **Dynamic Calendar UI Localization (JavaScript)**
  - Added a centralized `I18N` dictionary object in calendar script.
  - Replaced key dynamic modal/toast/editor strings with translatable values.
  - Fixed string interpolation and ensured runtime messages respect active language.

3. **Hebrew Dictionary Expansion**
  - Added a broad set of calendar-specific keys to `translations/he.json`.

4. **Translation Audit Refresh**
  - Regenerated `translation_audit.txt` after the sweep.
  - Remaining unmatched English entries reduced from 241 to 201.

**Test Results:**
- `python test_app.py` passed (`34` tests).

## Session 17

**Date:** March 15, 2026

**Objective:** Address intake tab layout issues, quick-book recurrence control, and make Hebrew translation editing easier through a dictionary file.

**Changes Made:**

1. **Initial Intake Add-Patient Cleanup**
  - Removed the two free-text intake fields from the Add Patient page.
  - Intake setup now starts cleanly from the dedicated intake evaluation workflow.

2. **Quick Book Recurrence Switch (Patient Quick Actions)**
  - Added recurrence mode selector to quick-book form:
    - Auto (by patient type)
    - One-time meeting
    - Recurring weekly meeting
  - Backend now respects this selector and validates constraints.
  - Recurring mode is rejected for initial-intake patients with a clear validation message.

3. **Intake Tab Layout Fix**
  - Restored summary information cards to Summary tab.
  - Moved the actual Intake Evaluation form card to the Intake tab using the correct DOM block.

4. **Hebrew Translation Dictionary File**
  - Added editable dictionary file: `translations/he.json`.
  - Added override loader in `app.py` so dictionary edits apply without code changes.
  - Localized additional hardcoded form/button text in add-patient and quick-actions sections.

5. **Documentation**
  - Updated README with Hebrew dictionary usage notes.

**Test Results:**
- `python test_app.py` passed (`34` tests).

## Session 16

**Date:** March 12, 2026

**Objective:** Enhance UI/UX with three focused improvements: vacant slot visibility in calendar, dedicated intake form tab space, and quick booking action.

**Changes Made:**

1. **Vacant Slots Now Visible in Calendar**
   - Modified `build_week_calendar_snapshot()` in app.py to render available slots as distinct calendar events
   - Vacant slots appear with green color (#10b981) labeled as "Vacant (duration)min"
   - Admin-only feature to maintain clean UI for patient calendars
   - Added "Vacant Slot" badge to calendar legend for clarity

2. **Intake Form Dedicated Tab**
   - The Intake Evaluation Form already had proper dedicated tab support via JavaScript DOM movement
   - Form is rendered in its own tab (#intake) with full card styling and spacing
   - Export DOCX button remains accessible within the tab
   - Sub-tabs within form (Prelim, Background, Administrative, Medical, Mental Status, Treatment Plan) remain functional

3. **Quick Action: Book Appointment**
   - Added new quick action button to patient detail page Quick Actions panel
   - Button navigates directly to /weekly_calendar for easy appointment booking
   - Styled with info color (#0d6efd) to distinguish from intake form action
   - Appears for all patient types after Edit and Export History buttons

**Technical Details:**

- **app.py (lines 1804-1816)**: Added vacant slot event rendering for admins using #10b981 color
- **calendar.html**: Added "Vacant Slot" badge to legend for event type visibility
- **patient_detail.html**: Appended Book Appointment link after intake tab control

**Test Results:**
- Application Tests: ✓ 16/16 passed
- Security Tests: ✓ 3/3 passed
- Syntax Validation: ✓ Passed

**Dependencies:**
- No new dependencies introduced
- Uses existing calendar event infrastructure
- Leverages existing route structure (weekly_calendar)

**User Impact:**
- Admins can now see all bookable slots at a glance in calendar view
- Patients have immediate access to book appointments from patient profile
- More screen real estate for intake form completion on dedicated tab

**Next Steps (Future):**
- Real-time vacancy counter on quick action button
- Batch slot availability import from external scheduling systems
- Intake form progress indicator (e.g., "4/6 sections completed")

## Session 15 — March 12, 2026 (Phase 1: Group Meetings History and Management)

### Overview
Started implementation of group meeting management by introducing dedicated group data models, admin workflows, and calendar integration.

### 1. New Group Data Model
- Added DB support for:
  - `groups` (name, type, description, active flag)
  - `group_members` (group-to-patient assignment with join/leave tracking)
  - `group_sessions` (scheduled sessions with date/time/duration/link)
- Added migration-safe creation in `init_db` and schema coverage in `schema.sql`.

### 2. Admin Group Management Routes
- Added admin routes:
  - `GET/POST /groups` to view and create groups
  - `POST /groups/<group_id>/members` to add a patient to a group
  - `POST /groups/<group_id>/members/<patient_id>/remove` to remove a member
  - `POST /groups/<group_id>/sessions` to schedule a group session
  - `POST /groups/sessions/<session_id>/delete` to delete a session

### 3. Groups Admin UI
- Added new template: `templates/groups.html`.
- Includes:
  - Group creation form
  - Per-group member management
  - Per-group session scheduling
  - Upcoming session list with deletion
- Added a `Groups` admin nav action in `layout.html`.

### 4. Calendar Integration
- Group sessions now appear in weekly calendar snapshot events with a dedicated color.
- Group sessions are also considered occupied time, preventing slot collisions.
- Updated calendar legend to include Group Session indicator.

### Verification
- `python -m py_compile app.py test_app.py` passed.
- `python test_app.py` passed (`16` tests).
- `python test_security.py` passed (`3` tests).

---

## Session 14 — March 12, 2026 (Vacancy-Gated Booking, Sticky CRM Filters, Messaging Ribbon, Intake Tab Controls)

### Overview
Implemented the requested behavior fixes for booking permissions, CRM filter persistence, admin chat ribbon visibility, and intake tab access controls.

### 1. Booking Restricted to Admin-Enabled Vacancies
- Calendar booking availability is now sourced from explicit admin vacancy records (`slots_override` with `status='available'`).
- Added admin endpoint: `/api/calendar/vacancy` to enable a date/time window as bookable.
- Added UI in calendar block management tab: **Enable Vacant Slot** (date, start time, end time).
- Booking now succeeds only when the selected slot exists in enabled vacancies and remains non-overlapping with appointments/blocks.

### 2. CRM Filters Persist Across Page Returns
- CRM filter state (`status`, `patient_type`, `q`, `sort`) is now persisted in session.
- Returning to `/crm` without query parameters restores the last active filter set.
- Status summary cards now preserve active search/type/sort filters when switching status buckets.

### 3. Messages Ribbon Includes Patients Without Message History
- Admin conversation list now uses patients as the base dataset and includes rows even with no prior messages.
- Added support for listing patients that do not yet have a portal login (displayed but non-selectable for sending).
- API filtering by search/type/status now applies server-side for conversation list retrieval.

### 4. Intake Form Placement and Enablement
- Intake tab visibility now supports either:
  - `patient_type='initial-intake'`, or
  - explicit `has_intake_tab=1`.
- Added migration/schema support for `has_intake_tab`.
- Added quick action for non-intake patients: **Enable Intake Tab**.
- Intake form state now posts with `active_tab='intake'` to remain on the intake tab after save.

### 5. Test Updates and Verification
- Updated booking tests to create explicit vacancies before booking actions.
- Verification:
  - `python test_app.py` passed (`16` tests)
  - `python test_security.py` passed (`3` tests)

---

## Session 13 — March 12, 2026 (Refinement Pass: Status Colors, Collapsed Filters, Admin Name, Strict Calendar Windows)

### Overview
Applied a focused refinement pass to align UI behavior with requested semantics, tighten scheduling availability windows, and fix admin identity rendering.

### 1. Status-Driven Card Semantics (Main + CRM)
- Removed visible status badges (`Ongoing`, `Candidate`, etc.) from card headers.
- Switched card backgrounds to **status-based color coding**:
  - ongoing = green
  - candidate/intake = yellow
  - waiting = blue
  - archived/other = gray
- `initial-intake` now behaves like a **status-level candidate visual state** (instead of a separate type badge in card header).

### 2. Type Badge Placement Simplification
- Kept only a compact type badge at the end of the ID row.
- Residency remains explicitly tagged as `Residency`.
- All non-residency patients are shown as `Private` for display consistency.

### 3. CRM Filter UX Compact Mode
- Moved CRM search/type/sort controls into a **collapsed panel**.
- Added a funnel icon toggle button to open/close filters.
- Removed `initial-intake` from type filter options to keep intake behavior status-centric.

### 4. Admin Display Name in Navbar
- Updated authenticated user model loading so `display_name` is available on `current_user`.
- Navbar now renders `display_name` with username fallback.
- Profile updates are now immediately reflected in the top-right identity button.

### 5. Calendar Availability Restricted to Explicit Windows
- Replaced broad workday slot generation with explicit allowed windows:
  - Sunday: 14:00–15:00
  - Monday: 09:00–10:00, 12:30–13:30
  - Thursday: 10:00–15:00, 19:00–20:00
  - Tuesday/Wednesday: no availability
- Availability slots continue to honor overlap checks against existing appointments and blocks.

### 6. Test Alignment and Verification
- Updated booking-related tests to select valid allowed slots dynamically under the new window rules.
- `python test_app.py` passed (`16` tests).

---

## Session 12 — March 12, 2026 (Intake Workflow, CRM Filters, Messaging, Admin Profile, Backup Security)

### Overview
Implemented a broad UX and workflow update across intake handling, CRM filtering/sorting, chat usability, top navigation cleanup, admin identity management, and encrypted backup reliability.

### 1. Intake Workflow Integration
- Added a dedicated **Intake Evaluation** main tab in patient profile for `initial-intake` patients.
- Intake form is now presented as its own top-level tab alongside Summary, Treatment Log, Billing, and Messages.
- For intake patients, default tab now opens Intake directly.
- Quick Actions replaced Treatment Log shortcut with an Intake Form shortcut for intake patients.

### 2. CRM and Main Card Experience
- Added CRM controls for:
  - free-text search (`name/email/phone`)
  - patient type filter (`private`, `residency`, `initial-intake`)
  - sorting (status priority, name A-Z/Z-A, newest/oldest)
- Updated patient cards to use full background coloring by patient type.
- Added clear patient-type tags (Private/Residency and Intake badge).
- Removed redundant View Profile buttons from card grids and kept full-card click navigation.
- Intake cards now navigate directly to the intake tab.

### 3. Top Navigation Cleanup
- Removed redundant top blue-bar links for Ongoing / Candidates & Waiting / Archived.
- Kept primary action buttons (Add Patient, Resources, Calendar).

### 4. Admin Identity and Profile Management
- Added admin profile page (`/admin/profile`) with editable fields:
  - display name
  - email
  - phone
  - id number
  - date of birth
- Navbar admin identity is now a button with a **crown icon** linking to profile settings.
- Added user schema support and migration coverage for new profile fields.

### 5. Messaging Improvements (Admin)
- Enhanced message drawer to support contacting patients even with no prior thread.
- Added recipient search and filtering in the chat drawer by:
  - patient name/user text
  - patient type
  - patient status
- Backend API now returns patient type metadata and supports query filtering.

### 6. Encrypted Backup and Data Safety
- Added encrypted backup support with `cryptography` (Fernet):
  - encrypted `.db.enc` backup artifacts
  - periodic routine backup guard
  - manual backup trigger endpoint (`/admin/backup_now`)
- Added `cryptography` to `requirements.txt`.

### Verification
- `python test_app.py` passed (`16` tests).

---

## Session 11 — March 11, 2026 (Special Booking Flow, CRM Views, Hebrew Coverage)

### Overview
Implemented the latest UX and workflow updates across calendar and CRM, including moving Special scheduling into Booking Panel, adding card/list presentation mode in CRM, and extending Hebrew translation coverage for updated UI labels.

### 1. Special Moved from Block Panel to Booking Panel
- Added `Booking Type` in Booking Panel with:
  - `Appointment` (default)
  - `Special` (purple-highlighted selection)
- When `Special` is selected:
  - `Special Pattern` field appears (`One-time` / `Weekly Recurring`)
  - `Repeat Until` field appears for weekly recurring mode
  - `Special Title` field appears
- Kept block creation tab for **blocked intervals only**.

### 2. Special Availability Behavior
- `api_calendar_book` now supports `booking_type=special`.
- Special slots are saved to `blocked_slots` with `block_type='special'`.
- Recurring special slots are expanded weekly until the selected end date.
- Overlap checks prevent inserting special blocks over existing appointments/blocks.
- Patients still do **not** see blocked/special events, and those slots are excluded from available slots.

### 3. Calendar Bug Fixes and UI Polish
- Fixed stale `bookingDuration` reference in `dateClick` callback (now defaults to 60-minute selection when clicking a slot cell).
- Added admin-only display for blocked/special filter chips.
- Added broader `t(...)` wrappers in calendar headers, labels, legends, and button text for Hebrew mode consistency.

### 4. CRM Main Page Updates
- Removed top action buttons for:
  - Weekly Calendar
  - Add Patient
- Added view mode toggle in CRM patient section:
  - `Cards`
  - `List`
- Implemented responsive list-mode styling so mobile layout remains intact.
- Added translation wrappers for CRM title/summary and view-mode controls.

### 5. Hebrew Translation Coverage
- Extended `HEBREW_TRANSLATIONS` with new strings used by:
  - Calendar new controls (`Booking Type`, `Special Pattern`, `Repeat Until`, etc.)
  - CRM list/card mode labels and headers

### Verification
- `python3 test_app.py` passed (`14` tests)
- `python3 test_security.py` passed (`3` tests)

---

## Session 10 — March 11, 2026 (Booking UX, Calendar Fixes, Patient Type, Meeting Links)

### Overview
Wide-scope improvement pass covering 6 requested features + bug fixes across the calendar, patient management, and booking flows.

### 1. Calendar Layout Fix on Tab Switch
- **Problem:** The FullCalendar grid rendered incorrectly (collapsed columns, overlapping text) when switching away from the Schedule tab and returning.
- **Fix:** Added `shown.bs.tab` listener on `#schedule-tab` that calls `calendar.updateSize()` to force FullCalendar to recalculate its dimensions after the tab becomes visible again.

### 2. Start/End Time Instead of Duration
- **Booking Panel (`#booking-pane`):** Replaced the "Duration (minutes)" dropdown with an "End Time" time input. Duration is now computed automatically as `end_time - start_time` in both the UI and backend.
- **Add Block / Special (`#blocks-pane`):** Replaced the "Duration (minutes)" number input with a "Start Time" + "End Time" pair (15-minute stepping).
- **Backend (`api_calendar_book`, `api_calendar_block`):** Both endpoints now accept `end_time` instead of `duration_minutes`. Duration is computed server-side from `start - end` with a 60-minute safe default.
- **`setSelectedSlot()` updated** to display `date HH:MM → HH:MM` instead of `(N min)`.

### 3. Patient Calendar: Blocked Slots Hidden from Patients
- **Problem:** Blocked slots (and special occasions) were visible to patients as "Unavailable" entries in the calendar.
- **Fix (`build_week_calendar_snapshot`):** Blocked/special entries are still added to the `occupied` set (so available slots remain accurate), but the calendar `events` list only includes them when the viewer is an admin. Patients never see blocked time entries.
- **Legend updated:** Blocked/Special badges in the Schedule tab legend are now wrapped in `{% if current_user.role == 'admin' %}`.

### 4. Patient Type Field (Private / Residency)
- **DB migration:** `ALTER TABLE patients ADD COLUMN patient_type TEXT DEFAULT 'private'`
- **Add Patient form (`add_patient.html`):** Added radio buttons for "Private" vs "Residency" below the phone field.
- **Edit Patient form (`edit_patient.html`):** Same radio buttons, pre-selects current value.
- **Patient Detail (`patient_detail.html`):** Shows a colour-coded badge (purple for Residency, muted for Private) next to the status badge.
- **CRM Dashboard (`crm.html`):** Residency patients show a small "Residency" badge next to their ID.
- **`add_patient` / `edit_patient` routes in `app.py`:** Accept and persist `patient_type` with validation against `('private', 'residency')`.

### 5. Google Meet / Zoom Meeting Link Integration
- **New meeting type options:** Added `zoom` and `google-meet` to the Meeting Type dropdown in the Booking Panel (previously only `in-person` and `online`).
- **Helper buttons:** Two buttons added next to the Meeting Link URL field:
  - **Meet** button: opens `https://meet.google.com/new` in a new tab with `noopener,noreferrer` (no API key required — admin copies the generated link manually).
  - **Zoom** button: opens `https://zoom.us/start/videomeeting` in a new tab.
  - Clicking either button also auto-selects the corresponding meeting type in the dropdown.
- **`meeting_platform` column:** Added to the `appointments` table to store the platform independently of `meeting_type`. Both are sent from the frontend and persisted.

### 6. Zoom / Google Meet Icon in Calendar Events
- **`eventContent` callback** added to the FullCalendar configuration.
- Meetings with `meeting_platform = 'zoom'` or `meeting_type = 'zoom'` show a filled camera icon (`bi-camera-video-fill`).
- Meetings with `meeting_platform = 'google-meet'` or `meeting_type = 'google-meet'` show an outline camera icon (`bi-camera-video`).
- Legend updated with a "Zoom" camera-video badge for player reference.

### Bug Fixes
- `api_calendar_block` was accepting a free-form `duration_minutes` integer input that could be negative or zero — replaced by computed end−start with a 60-minute fallback.
- Calendar `booking_date` local variable was also used for form parsing, causing potential shadowing with `appointment_date` in the INSERT — renamed/traced to confirm no conflict.
- `appt.keys()` check for `meeting_platform` column ensures graceful fallback on legacy DB rows that predate the migration.

### Tests
- All 14 `test_app.py` tests pass.
- All 3 `test_security.py` tests pass.

---

## Session 9 - March 11, 2026 (Stability, Debugging, and Verification)

### Overview
Completed a full debug and verification pass on current calendar and test updates, then aligned security tests and dependency declarations with the current app behavior.

### Fixes Applied
- Added deduping guard for weekly calendar event emission to avoid duplicate recurring render collisions.
- Improved weekly calendar UI workflow (tabs, modal confirmations, grouped available slots, ongoing list, current-week auto-roll behavior).
- Added `.venv/` to `.gitignore` to avoid accidental environment commits.
- Added missing dependency `pyotp` to `requirements.txt`.
- Rewrote `test_security.py` from outdated OTP/`secret_token` assumptions to current login security behavior.

### Verification
- `WTF_CSRF_ENABLED=False python3 test_app.py` passed (`14` tests).
- `python3 test_security.py` passed (`3` tests).
- `python3 test_db.py` completed successfully (schema verification output).

---

## Session 8 — March 10, 2026 (Calendar UX Polish)

### Overview
Added a usability polish pass on top of the weekly snapshot calendar to improve planning speed and clarity.

### UX Enhancements
- Added visual legend for event meaning (ongoing, candidate/waiting, archived, blocked, special).
- Added interactive filter chips to toggle visible event groups in the calendar view.
- Added drag-to-book support:
  - selecting a time range now sets date, time, and duration in booking panel.
  - duration selector added to booking panel.
- Added half-hour slot granularity for availability generation (08:00-20:00, Sun-Thu).

### Backend Adjustments
- Calendar event metadata now includes `patient_status` for precise frontend filtering.
- Time parsing now accepts `HH:MM` and `HH:MM:SS`.
- Booking normalizes appointment time values before insert.

### Files Updated
- `templates/calendar.html`
- `app.py`
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`14` tests).

---

## Session 7 — March 10, 2026 (Workweek Snapshot Calendar + Self-Booking)

### Overview
Implemented a new weekly scheduling system focused on operational snapshot planning (not meeting journaling), with workweek visibility, weekend special handling, blocked intervals, private admin-only labels, and controlled patient self-booking.

### Features Implemented

#### 1. Treatment-log template now specifies checklist options
- Updated `static/treatment_log_template.json` to include `behavior_checklist_allowed_values` in the template entries.
- This gives explicit allowed values when editing/importing previous sessions.

#### 2. Removed extra Clinic CRM text button in ribbon
- Removed the additional `Clinic CRM` nav text link.
- Main brand/title remains the single entry point to CRM.

#### 3. New weekly calendar system
- Added route: `/calendar` and new template: `templates/calendar.html`.
- Added API: `/api/calendar/snapshot` returning a week snapshot payload.
- Main calendar view configuration:
  - Sunday-Thursday only
  - 08:00-20:00
  - Weekly time-grid snapshot

#### 4. Weekend special occasions side columns
- Calendar page now renders dedicated Friday and Saturday side panels.
- Weekend items are sourced from schedule overrides and support time + duration.

#### 5. Recurring vs one-time behavior
- Recurring appointments are expanded into weekly occurrences using recurrence rules.
- One-time intake/diagnostic meetings remain one-time and do not replicate.
- Added follow-up indicators for candidate/waiting patients with past one-time meetings and no future booking.

#### 6. Blocked intervals and private admin-only labels
- Extended `blocked_slots` model with:
  - `duration_minutes`
  - `title`
  - `is_private`
  - `block_type` (`blocked` or `special`)
  - `created_by`
- Patients see private entries as `Unavailable` while admins see full titles (e.g., supervision/seminar/group).

#### 7. Self-booking and deletion for users (controlled by admin)
- Added API `POST /api/calendar/book`:
  - Admin can book for any selected patient.
  - Patient can self-book only when `can_self_schedule = 1`.
- Added API `POST /api/calendar/appointment/<id>/delete`:
  - Admin can delete any appointment.
  - Patient can delete own appointments when self-management is enabled.

#### 8. Admin override management
- Added API `POST /api/calendar/block` for adding blocked/special intervals.
- Added API `POST /api/calendar/block/<id>/delete` for removing overrides.

### Additional UX wiring
- Added calendar nav access for both admin and patient in `templates/layout.html`.
- Added quick links from `templates/crm.html` and `templates/patient_home.html`.

### Files Updated
- `app.py`
- `schema.sql`
- `templates/calendar.html` (new)
- `templates/layout.html`
- `templates/crm.html`
- `templates/patient_home.html`
- `static/treatment_log_template.json`
- `test_app.py`
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`14` tests).

---

## Session 6 — March 10, 2026 (CRM Navigation + Meeting History UX + Multi-Patient Messaging)

### Overview
Implemented requested admin UX updates across the main ribbon, treatment log structure, and messaging workflows. Added a dedicated CRM management dashboard and upgraded treatment log history into a nested, collapsible meeting view.

### Features Implemented

#### 1. Previous meetings now shown as titled, collapsible entries
- In the patient Treatment Log tab, each historical entry now renders as:
  - `Meeting #<number> - <date>`
- Clicking the meeting title expands meeting content.
- Inside each expanded meeting, a nested `Behavior & Appearance` toggle reveals:
  - appearance
  - mood summary
  - behavior notes
  - behavior checklist tags

#### 2. Treatment log split into two sections
- Treatment Log tab now has two clear sections:
  - `Last Meeting Record` (latest session snapshot)
  - `Treatment Log` (import + new entry form + full history)

#### 3. Public Resources removed from admin ribbon
- Main ribbon now hides `Public Resources` for admin users.
- Public resources link remains available for non-admin users.

#### 4. All-patients moved under Clinic CRM management tool
- Added new admin route: `/crm`.
- Added dedicated template: `templates/crm.html`.
- Admin homepage now redirects to CRM dashboard.
- `/patients` remains as a compatibility route and now redirects to `/crm` with status.
- CRM dashboard includes:
  - patient list by selected status
  - management cards (All/Ongoing/Candidates+Waiting/Archived)
  - management actions (`Add Patient`, `Manage Resources`)
  - **Download button for treatment log template** (`static/treatment_log_template.json`)

#### 5. Main ribbon messages upgraded to navigate by patient conversation
- Admin offcanvas messages now includes a patient conversation selector.
- Admin can navigate between patient conversations instead of seeing a single mixed stream.
- Backend `/api/messages` now returns admin conversation list + active thread.
- Backend `/api/messages/send` now requires `recipient_id` for admin messages.
- Existing patient message behavior remains unchanged.

### Backend/Code Changes
- Added helper `fetch_patients_by_status` in `app.py`.
- Added route `crm_dashboard` in `app.py`.
- Updated `index` route admin redirect to `crm_dashboard`.
- Added `latest_note` context in `patient_detail` route for last-meeting section.
- Enhanced `api_get_messages` and `api_send_message` for per-patient admin messaging.

### Files Updated
- `app.py`
- `templates/layout.html`
- `templates/patient_detail.html`
- `templates/crm.html` (new)
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`12` tests).
- `python test_security.py` failed due missing local dependency: `pyotp` (`ModuleNotFoundError`).

---

## Session 5 — March 9, 2026 (Appearance/Behavior Questionnaire + JSON Template)

### Overview
Added structured appearance and behavior capture to the treatment log with auto-fill from the previous session. Also provided JSON template/example files and validated import against the live workflow.

### Features Implemented

#### 1. Appearance/Behavior questionnaire in Treatment Log
- Added a structured section to treatment log create/edit forms:
  - **Tick-box checklist** (`behavior_flags`)
  - **Short answer**: appearance overview (`patient_appearance`)
  - **Short answer**: mood summary (`mood_summary`)
  - **Short answer**: behavior notes (`behavior_notes`)

#### 2. Auto-fill from previous session
- On patient detail load, the latest note is read.
- Questionnaire values are pre-filled automatically into the next treatment log entry form.
- This supports continuity from one session to the next.

#### 3. Storage + migration support
- Added note-level fields via migrations and base schema updates:
  - `behavior_checklist`
  - `mood_summary`
  - `behavior_notes`
- Existing note fields (`note_date`, `patient_appearance`, `updated_at`) continue to be used.

#### 4. JSON template and example files
- Added reusable template at:
  - `static/treatment_log_template.json`
- Added concrete sample at:
  - `static/treatment_log_example.json`

#### 5. JSON import enhancements
- Import now accepts and maps questionnaire fields from JSON records:
  - `behavior_checklist` (array or string)
  - `mood_summary`
  - `behavior_notes`
  - `patient_appearance`
- Sorting behavior remains by date and meeting number.

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`12` tests).
- End-to-end live import check performed using `static/treatment_log_example.json`; records loaded with meeting/date/order and questionnaire fields.

### Files Updated
- `app.py`
- `schema.sql`
- `templates/patient_detail.html`
- `test_app.py`
- `static/treatment_log_template.json` (new)
- `static/treatment_log_example.json` (new)
- `CHANGES.md`

---

## Session 4 — March 9, 2026 (Treatment Log Workflow + Patient Detail UX)

### Overview
Implemented a focused upgrade of the patient detail workflow with emphasis on treatment-log operations, import/edit lifecycle, and keeping users on the same tab after form actions.

### What Changed

#### 1. Summary background box behavior
- Reworked the background section in patient summary to a closed preview box by default.
- Added an explicit Edit button that opens a collapsible editor.
- Save still updates patient info, but now keeps the user on the Summary tab.

#### 2. Appointments tab hidden for now
- Removed the Appointments tab button from patient detail navigation.
- Removed quick-action shortcut to appointments.
- Backend appointment endpoints remain intact for later re-enable.

#### 3. Clinical Notes renamed and form reshaped
- Renamed the visible tab label to Treatment Log.
- Changed treatment log entry form to use three core fields:
  - Meeting number
  - Date
  - Content

#### 4. Appearance/behavior placeholder
- Added a placeholder input for patient appearance/behavior in treatment log create/edit UI.
- Placeholder is visible but disabled to prepare for future activation.

#### 5. JSON treatment-log import flow
- Strengthened `/patient/<id>/import` JSON import handling for treatment logs.
- Supports flat list records using meeting/date/content fields.
- Imports are sorted by date and meeting number before insert.
- Imported notes now populate note date and meeting number consistently.

#### 6. Treatment log is editable post-creation
- Enabled per-note edit forms directly in the treatment log list.
- Edit supports updating meeting number, date, and content.

#### 7. Track when a treatment log entry was edited
- Added/used `updated_at` note field.
- Edit action updates `updated_at = CURRENT_TIMESTAMP`.
- UI now displays edited timestamp (or “Not edited yet”).

#### 8. Billing future upload placeholder
- Added disabled placeholder input for future external receipt upload support in billing form.

#### 9. Messaging behavior preserved
- Messaging flow was kept unchanged functionally.
- Redirect now keeps user on Messages tab after sending from patient detail.

#### 10. Keep same tab/page after actions
- Added tab-preserving redirect pattern for patient detail actions.
- Added tab state sync in UI (`tab` query param + hidden `active_tab` form input).
- Actions now return to the same working tab instead of always jumping to Summary.

### Backend/Migration Notes
- Added note migrations via `init_db()` for:
  - `note_date`
  - `patient_appearance`
  - `key_topics` (compatibility)
  - `updated_at`
- Note loading order now prefers `note_date`, then session number, then creation time.

### Files Updated
- `app.py`
- `templates/patient_detail.html`
- `test_app.py`
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`10` tests).

---

## Session 3 — Feature Branch Analysis & Integration

### Overview
Analyzed all 8 remote feature branches, identified valuable code, and selectively merged/extracted improvements while discarding conflicting or low-quality changes.

### Branch Decisions
| Branch | Decision | Reason |
|--------|----------|--------|
| `feature-crm-refactoring` | ✅ Merged | Port detection, `can_self_schedule`, notifications system, goals table, DOCX improvements |
| `enhance-clinic-crm` | ✅ Extracted | Goals CRUD, edit_note, Revenue dashboard, unread message context processor |
| `feature-calendar-doc-integration` | ❌ Discarded | Conflicting `/api/slots` schema |
| `feature-clinic-crm-updates` | ❌ Discarded | Test file only, no app code |
| `jules-clinic-app` | ❌ Discarded | 125-line skeleton (incomplete rewrite) |

### New Features Added

#### From `feature-crm-refactoring` (merged)
- **`can_self_schedule` flag** on patients — controls self-scheduling UI visibility; dashboard always shows calendar, shows info alert when self-scheduling is disabled
- **Notifications system** — `notifications` table populated when patients self-schedule/reschedule; admin gets toast alerts every 10s via `/api/notifications`
- **`goals` table** in schema + migrations
- **`is_port_in_use()` startup check** — warns if port 5000 is already occupied
- **`import socket`** added to imports
- **Fixed `datetime` import conflict** — removed bare `import datetime` module (was shadowing `from datetime import datetime, timedelta`)

#### From `enhance-clinic-crm` (extracted)
- **`inject_global_vars` context processor** — injects `unread_messages` count into all templates
- **`edit_note` route** (`POST /note/<id>/edit`) — admin can edit session note content, appearance, topics
- **Goals CRUD routes** — `add_goal` (`POST /patient/<id>/add_goal`) and `toggle_goal_status` (`POST /goal/<id>/toggle_status`)
- **Revenue dashboard** (`GET /admin/revenue`) — shows total revenue, pending debt, monthly breakdown; linked in admin navbar

### Files Changed
- `app.py` — added 5 new routes, 2 context processors, fixed datetime naming conflict
- `templates/admin_revenue.html` — new revenue dashboard template
- `templates/layout.html` — Revenue nav link added; notification toast container + polling script
- `templates/edit_patient.html` — better styled `can_self_schedule` toggle
- `schema.sql` — `notifications`, `goals`, `can_self_schedule` column added
- `requirements.txt` — added `psutil`, `python-docx`

---

## Session 2 — March 9, 2026 (Recurring Calendar Overhaul)

### Overview
Addressed the core recurring-appointment visibility problem: sessions belonging to long-running therapy patients were not appearing in the calendar. Also standardised both calendars to show only workdays (Sun–Thu) at the correct hours (08:00–20:00) with clean day-name-only column headers.

---

### 1. **Fixed Recurring Appointments Not Appearing in Calendar** ✅ — `app.py`

**Problem:**  
Recurring therapy sessions were invisible on any week that wasn't the week the series originally started. The entire projection loop was nested inside:

```python
if start_date <= original_appointment_date <= end_date:
    # project recurring occurrences  ← never reached for older series
```

Because most ongoing patients have series that began weeks or months ago, their original appointment date sits outside the current view window — so zero occurrences were ever projected and the calendar appeared empty.

**Root cause (secondary):**  
Even when the original date happened to fall in range, the projection iterated only `12 // interval_weeks` cycles *from the original date*, not from the current date, so bi-weekly series starting long ago would also be missed.

**Solution:**  
Completely rewrote the `/api/slots` endpoint recurring-event section (`app.py`):

- Fetches **all** recurring appointment series (not just those whose `appointment_date` falls in the view range).
- For each series, finds the Sunday of the week containing the original appointment and steps forward in `interval_weeks` increments, collecting every matching weekday occurrence.
- Stops walking only when the week's Sunday exceeds `end_date + 7 days` (no more occurrences can be in range).
- Applies `recurrence_end_date` and `recurrence_count` limits in the correct chronological order.
- Safety cap of 1040 week iterations (~20 years).

**How it works step by step:**
```
series_week_sunday = appt_date - timedelta(days=(appt_date.weekday()+1) % 7)
week_num = 0
while week_sunday <= end_date + 7 days:
    for each fc_day in recurrence_fc_days:       # 0=Sun, 1=Mon … 4=Thu
        occ = week_sunday + timedelta(days=fc_day)
        if occ >= appt_date: collect(occ)
    week_num += 1 (advance by interval_weeks)
apply limit_count / limit_date
emit events where start_date <= occ <= end_date
```

**Files Modified:** `app.py` — `api_slots()` function

---

### 2. **Fixed Recurring Event Titles** ✅ — `app.py`

**Problem:**  
All recurring occurrences were labelled `"Occupied (Recurring)"` regardless of who the patient was. This made it impossible to identify sessions on the admin calendar.

**Solution:**  
Applied the same title logic used for single appointments:
- **Admin view** → patient's name (e.g., `"Jane Cohen"`)
- **Patient view (own appointment)** → `"My Appointment"`
- **Patient view (other patient's slot)** → `"Occupied"`

**Files Modified:** `app.py` — `make_appt_event()` helper inside `api_slots()`

---

### 3. **Removed Dates from Calendar Column Headers** ✅ — Both calendars

**Problem:**  
Day column headers showed specific dates (e.g., "Mon 3/10"), which was noisy and inconsistent with the desired "weekly schedule" view that focuses on time slots rather than specific dates.

**Solution:**  
Added `dayHeaderFormat: { weekday: 'long' }` to both FullCalendar instances.  
Columns now read: **Sunday · Monday · Tuesday · Wednesday · Thursday**.

**Files Modified:** `templates/manage_slots.html`, `templates/dashboard.html`

---

### 4. **Standardised Calendar to Workdays and Correct Hours** ✅ — Both calendars

**Problem:**  
- Dashboard calendar showed Friday and Saturday (non-working days for this clinic).  
- Dashboard calendar cut off at **18:00** instead of the correct **20:00**.  
- Both calendars had mismatched configurations.

**Solution:**

| Setting | Before | After |
|---------|--------|-------|
| `hiddenDays` (dashboard) | not set (all 7 days shown) | `[5, 6]` (Fri + Sat hidden) |
| `slotMaxTime` (dashboard) | `18:00:00` | `20:00:00` |
| `firstDay` (dashboard) | not set | `0` (Sunday) |
| `headerToolbar center` | date range string | empty (no cluttered title) |

Admin (`manage_slots.html`) already had correct `hiddenDays` and hours; only the `dayHeaderFormat` and toolbar title were updated.

**Files Modified:** `templates/dashboard.html`, `templates/manage_slots.html`

---

### Files Modified — Session 2

| File | What Changed |
|------|-------------|
| `app.py` | Rewrote `api_slots()` recurring projection; fixed event titles |
| `templates/manage_slots.html` | `dayHeaderFormat`, removed center title |
| `templates/dashboard.html` | `hiddenDays`, `slotMaxTime`, `firstDay`, `dayHeaderFormat`, removed center title |
| `CHANGES.md` | This documentation |

---

### Testing Checklist — Session 2

1. **Recurring series started in the past shows on current week**  
   - Create a recurring weekly appointment starting 2+ months ago  
   - Navigate to the current week on `/admin/slots`  
   - ✅ Session must appear on the correct weekday

2. **Admin sees patient name on recurring events**  
   - Open `/admin/slots`, look at any recurring slot  
   - ✅ Title should be the patient's name, not "Occupied (Recurring)"

3. **Column headers show only weekday names**  
   - Open both `/admin/slots` and patient dashboard  
   - ✅ Columns should read "Sunday", "Monday", … — no numeric dates

4. **Dashboard shows Sun–Thu only, 08:00–20:00**  
   - Log in as a patient and open the dashboard  
   - ✅ Only five columns visible; time grid ends at 20:00

---

# Changes Documentation - March 9, 2026 (Session 1)

## Overview
Fixed multiple issues with ongoing patient crashes, color coding, calendar refresh, and unified booking interface.

## Changes Made

### 1. **Fixed Port Closing Issue in `run.py`** ✅
**Problem**: When Ctrl+C was pressed, the Flask app process wasn't properly terminating, causing the port (5000) to remain occupied.

**Solution**:
- Added `psutil` dependency for robust process management
- Implemented proper process group cleanup using `psutil.Process.children()`
- Added graceful termination with force-kill fallback
- Implemented proper signal handling with flag to prevent signal recursion
- Added auto-cleanup via `atexit` module for edge cases
- Added 0.5-second delay after process termination to ensure port release

**Files Modified**: `run.py`, `requirements.txt`

---

### 2. **Fixed Ongoing Patients Crash (Convert Modal)** ✅
**Problem**: The convert modal was missing critical fields (`duration`, `days`) causing form submission errors and crashes when converting candidates to ongoing.

**Solution**:
- Added `duration` field selector (30, 60, 90, 120 minutes)
- Added `days` checkboxes for recurrence day selection (Sun-Thu)
- Properly structure recurrence fields in modal  
- Enhanced error handling in `convert_patient()` function:
  - Input validation for dates and times
  - Type conversion with error handling
  - Database error handling with rollback
  - User-friendly error messages
  - Audit logging for patient conversion

**Files Modified**: `templates/patient_detail.html`, `app.py` (convert_patient function)

---

### 3. **Fixed Color Coding for Waiting Patients** ✅
**Problem**: Candidate and waiting patients were using the same color scheme, making it unclear which waiting patients have bookings scheduled.

**Solution**:
- Updated color logic to differentiate waiting patients:
  - `Ongoing` = Green (bg-success)
  - `Candidate` = Yellow (bg-warning)
  - `Waiting WITH recurring appointments` = Blue (bg-info) - indicates scheduled
  - `Waiting WITHOUT appointments` = Gray (bg-secondary) - indicates not yet scheduled
  - `Archived` = Gray (bg-secondary)

**Files Modified**: `templates/index.html`, `templates/patient_detail.html`

---

### 4. **Fixed Calendar Not Refreshing After Booking** ✅
**Problem**: After booking appointments from the patient detail page, the admin calendar in manage_slots didn't update automatically.

**Solution**:
- Added "Refresh" button to calendar toolbar
- Implemented auto-refresh every 30 seconds using `calendar.refetchEvents()`
- Calendar now properly reflects changes from both interfaces

**Files Modified**: `templates/manage_slots.html`

---

### 5. **Created Unified Booking Interface in Manage Slots** ✅
**Problem**: Booking existed in two disconnected places (patient detail vs. management tool) with different functionality. No way to book from scheduler tool.

**Solution**:
- Redesigned slot modal with dual modes:
  
  **Mode 1: Availability Management (Override)**
  - Manage slot availability (Open/Blocked/Occupied)
  - Set duration and status
  - Existing functionality preserved
  
  **Mode 2: Patient Booking**
  - Select patient from dropdown
  - Set appointment details (duration, cost, meeting type, link)
  - **RECURRING APPOINTMENT SUPPORT**:
    - Checkbox to enable recurring scheduling
    - Interval selection (weekly/bi-weekly)
    - Day of week selection
    - End limit options (by date or count)
  - Auto-marks slot as occupied after booking
  - Audit logging for admin actions

- Updated `manage_slots()` route:
  - Now passes all patients to template for dropdown
  
- Enhanced `admin_manage_slots()` function:
  - Detects mode and routes to appropriate handler
  - Comprehensive validation and error handling
  - Both single and recurring appointment support
  - Transaction rollback on errors
  - Automatic slot override creation/update

**Files Modified**: `templates/manage_slots.html`, `app.py`

---

### 6. **Enhanced Error Handling Throughout** ✅
- Added try-except blocks with proper error messages
- Implemented database transaction rollback on errors
- Improved validation for dates, times, and numeric fields
- User-friendly flash messages for all error conditions
- Audit logging for convert and booking operations

**Files Modified**: `app.py` (multiple functions)

---

## Testing Recommendations

### 1. **Ongoing Patient Conversion**
- Go to candidate patient
- Click "Convert to Ongoing"
- Fill all fields (should no longer crash):
  - Start date and time
  - Duration
  - Cost
  - Recurrence days (select at least Monday)
  - End limit (count or date)
- Verify patient converts successfully with audit log

### 2. **Patient Color Coding**
- View patients list (/patients)
- Verify colors:
  - Ongoing patients = Green
  - Candidate patients = Yellow
  - Waiting patients with recurring = Blue
  - Waiting patients without appointments = Gray

### 3. **Calendar Auto-Refresh**
- Open manage_slots in one window
- Book appointment from patient detail in another
- Verify calendar refreshes within 30 seconds
- Test manual "Refresh" button

### 4. **Unified Booking Interface**
- Go to Manage Slots
- Click on a time slot
- Switch between modes:
  - **Override Mode**: Manage availability
  - **Patient Booking Mode**: Book for patient
- Test booking single appointment
- Test booking with recurring option
- Verify slot is marked occupied
- Verify calendar updates

### 5. **Recurring Appointments from Scheduler**
- Book appointment from manage_slots
- Enable "Make recurring"
- Select interval (weekly/bi-weekly)
- Select days of week
- Set end limit (count or date)
- Verify recurring series appears in calendar

---

## Security Improvements
- Validated all user inputs (dates, times, numeric values)
- Protected against type errors and injection
- Proper authorization checks maintained
- Audit logging for sensitive operations

## Performance Improvements
- Calendar auto-refresh efficient (30-second intervals)
- Manual refresh button for immediate updates
- Better error isolation prevents cascading failures

## Backwards Compatibility
- All existing functionality preserved
- Can still use patient detail page for bookings
- Slot override management unchanged
- New booking interface is additive

---

## Files Modified Summary
1. `run.py` - Process management enhancements
2. `requirements.txt` - Added psutil
3. `app.py` - Multiple function improvements:
   - `manage_slots()` - Pass all_patients to template
   - `admin_manage_slots()` - Unified booking interface
   - `convert_patient()` - Complete rewrite with validation
   - `add_appointment()` - Recurring appointment support
   - `api_slots()` - Time handling improvements
   - `seed_data()` - Error handling
4. `templates/patient_detail.html` - Enhanced convert modal
5. `templates/index.html` - Improved color coding
6. `templates/manage_slots.html` - Unified booking modal + calendar refresh
7. `CHANGES.md` - Comprehensive documentation
