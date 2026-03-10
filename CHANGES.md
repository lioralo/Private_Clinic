# Changes Documentation

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
