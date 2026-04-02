1. **Schema Modifications (`schema.sql` & `app.py`)**:
   - Add `slots` table to `schema.sql`: `id`, `weekday` (0-6), `time` (TIME), `is_blocked` (BOOLEAN DEFAULT 0).
   - Add columns to `patients`: `background TEXT`, `treatment_info TEXT`.
   - Update `app.py`'s `init_db()` to handle adding these new columns dynamically via ALTER TABLE, and create `slots` table.
   - Wait, `init_db` runs `schema.sql`. For new deployments it's fine. For existing DB, we need an alter table in `init_db()`.

2. **Tabbed Patient View (`patient_detail.html`)**:
   - Refactor UI to use Bootstrap Tabs: Information, User Background, Treatment Info, History.
   - Information Tab: Same content + Portal Access section.
   - User Background Tab: Large textarea for `background`. Add form to submit to `/patient/<id>/update_info`.
   - Treatment Info Tab: Goals (part of treatment info text?), Current Clinical Notes, Medical Files. Add form to update `treatment_info`.
   - History Tab: Past Appointments, Financial Receipts.
   - Add `/patient/<int:patient_id>/update_info` route in `app.py`.

3. **Recurring Weekday Calendar System (`app.py`, `manage_slots.html`, `dashboard.html`)**:
   - Create `/manage_slots` route for Admin to view/add slots to the `slots` table and mark them as blocked.
   - Create `/api/slots` route to output JSON for FullCalendar.
     - Generate recurring occurrences for current and future weeks.
     - Logic: for next N weeks, generate occurrences of that weekday and time.
     - Filter: Admin sees all (Open, Booked, Blocked). Patient sees Open + personally booked.
     - Booked check: check `appointments` table for date/time.
   - Create `manage_slots.html` to manage the underlying `slots`.
   - Update `dashboard.html` to handle new recurring slot data if needed. (Maybe just an appointment booking calendar interface?) The prompt says "Update manage_slots.html and dashboard.html to handle the new recurring slot data structure". We will create a `manage_slots.html` and update `dashboard.html` to display the calendar using FullCalendar.

4. **Appointment Management & Reminders**:
   - Deletion logic: `app.py` `/appointment/<int:appointment_id>/delete` already just deletes from `appointments`. This leaves the slot open again automatically since the slot generation checks appointments.
   - Reminder System: `send_appointment_reminders()` in `app.py`? Check if `app.py` has this. No. "Populate the send_appointment_reminders function in app.py. Logic: For now, implement a dashboard notification or a log-based "reminder" that identifies appointments occurring within the next 24 hours. UI: Display a "Upcoming Reminders" section on the Admin dashboard." So I'll write `send_appointment_reminders()` and call it in `/patients` (Admin dashboard) to pass reminders to `index.html`.

5. **Pre commit instructions**:
   - Call `pre_commit_instructions` tool to run verification and tests before submit.
