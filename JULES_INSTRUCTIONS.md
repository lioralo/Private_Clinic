# Jules Instructions: Private Clinic CRM Refactoring & Features

## Status: Completed Features
The following features have been successfully implemented and are live in the `app.py` and templates:

### 1. Recurring Weekday Calendar System
- **Database:** Uses `slots_recurring` table with `weekday` (0-6) and `time` columns.
- **Logic:** `/api/slots` generates instances for the current and next 3 weeks dynamically.
- **Admin:** Can manage these slots at `/admin/slots` (Add/Delete/Block).
- **Patient:** Sees available instances in a `FullCalendar` view on their dashboard and can book them with one click.

### 2. Tabbed Patient Details View
- Refactored `patient_detail.html` into a professional Bootstrap 5 Tabbed interface:
    - **Information:** Core contact info, portal access, and therapy progress charts.
    - **User Background:** A dedicated space for long-form medical and personal history.
    - **Treatment Info:** Clinical formulation, active goals, session notes, and medical files.
    - **History:** Chronological log of appointments and financial receipts.

### 3. Appointment Reminders
- Admin dashboard (`index.html`) now features an **Upcoming Reminders** sidebar.
- Logic identifies all scheduled appointments within the next 24 hours.

### 4. Technical Refinements
- **JSON Serialization:** All SQLite `Row` objects passed to `tojson` in templates are now explicitly converted to dictionaries in the backend to prevent `TypeError`.
- **Gunicorn Deployment:** The app is configured to run via `gunicorn` for better process management and stability.

## Maintenance & Running
- **Start Command:** `python3 -m gunicorn --bind 0.0.0.0:5000 app:app`
- **Database Initialization:** `python3 -c "from app import init_db; init_db()"` handles automatic column migrations for `background`, `treatment_info`, and `secret_token`.
