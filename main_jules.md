# Instructions for Jules (Private Clinic CRM)

## Project Overview
This is a Psychotherapy Clinic CRM built with Flask, SQLite, and FullCalendar. It supports patient management, billing, scheduling, and localization.

## Latest Features Added
1.  **Advanced Recurrence**:
    *   Appointments can now repeat until a `recurrence_end_date` or for a specific `recurrence_count`.
    *   The logic is handled in `app.route('/patient/<int:patient_id>/convert')` for setting the rules and `app.route('/api/slots')` for rendering them.
2.  **Patient History JSON Import/Export**:
    *   `export_patient_history`: Exports all data for a patient.
    *   `import_patient_history`: Imports data and **automatically sorts** it chronologically.
    *   It handles the mapping between appointments and notes during import.

## Change Log
- **Date/Time**: Sunday, 8 March 2026, 20:45
- **Update**:
    - **UI/UX**: Synced routes and validated `patient_detail.html` forms.
    - **Calendar UI**: Modified `api_slots` to display the patient's name for Admins, and "My Appointment" or "Occupied" for Patients, regardless of self-scheduling permissions.
    - **Recurrence**: Updated `api_slots` to properly project recurring appointments up to 12 weeks ahead by resolving a bug in the DB query logic.
    - **Meeting Links**: Validated that `add_appointment` correctly extracts and persists `meeting_link`.
    - **Verification**: Verified JSON import logic handles sorting and ID mapping correctly.
- **Date/Time**: Tuesday, 10 March 2026, 10:00
- **Update**:
    - **Conflict Resolution**: Added logic to `api/slots` to prevent generating recurring appointments if the day/time overlaps with a "blocked" status in `slots_override`.
    - **UI Timeline**: Updated `patient_detail.html` to display the "Meeting Number" next to the clinical notes to make progress tracking easier.
    - **Audit Logging**: Ensured that when an appointment is deleted, an entry is created in the `audit_logs` table via the `delete_appointment` route.
    - **Email Reminders**: Created a stub function `send_appointment_reminders()` in `app.py` intended for external Email/SMS API integrations.
    - **Time Inputs**: Replaced `<input type="time">` in `patient_detail.html` with `<select>` dropdowns (30-minute increments, 08:00 - 21:00).
- **Date/Time**: Sunday, 8 March 2026, 13:55
- **Update**:
    - Enhanced calendar booking to show specific client names (Admin view) or "My Appointment" (Patient view).
    - Added "Unknown Patient" fallback for missing patient data.
    - Integrated meeting links directly into calendar event properties and patient dashboard.
    - Added "Add Recurring..." functionality to the appointment add dropdown.
    - Synchronized recurring projection logic across Admin and Patient views.
- **Date/Time**: Sunday, 8 March 2026, 13:25
- **Update**:
    - Integrated Advanced Calendar with Notification system.
    - Implemented Recurrent Meeting limits (by Date or Count).
    - Added Chronological JSON Import/Export for patient history with automatic sorting.
    - Fixed Jinja2 translation errors and missing admin routes.
    - Resolved merge conflicts in documentation and stabilized the code.

## Verification Checklist for Jules
Jules MUST verify the following after the latest update:
1.  **Admin View**: Go to a patient detail page, add an appointment, and verify it appears in the `/admin/slots` calendar with the patient's name.
2.  **Patient View**: Log in as a patient, go to the dashboard, and verify that your own appointment says "My Appointment" while others say "Occupied".
3.  **Recurrence**: Add a recurring appointment and verify it projects correctly into future weeks (up to 12 weeks) on both Admin and Patient calendars.
4.  **Meeting Links**: Verify that the "Join Meeting" link appears in the patient's appointment list if a URL was provided.
5.  **JSON Import**: Export a patient's history, then import it back (perhaps to a new patient) and verify that all appointments and notes are correctly sorted and linked.

## Future Tasks for Jules
- **Documentation Maintenance**: For every future update, Jules MUST add a new entry to the "Change Log" section above, including the date, time, and a concise summary of the changes made.
- **Conflict Resolution**: Ensure that recurring meetings do not overlap with existing `slots_override` marked as `blocked`.
- **UI Improvements**: Add a visual indicator in the patient history timeline to show the "Meeting Number" clearly.
- **Reminder Logic**: Enhance the `send_appointment_reminders` function to support email or SMS via external APIs.
- **Audit Logs**: Expand audit logging to capture deletion of records.

## Technical Details
- **Database**: `clinic.db` (SQLite).
- **Styling**: Vanilla CSS with some Bootstrap 5.
- **Key Files**: `app.py`, `schema.sql`, `templates/`.
