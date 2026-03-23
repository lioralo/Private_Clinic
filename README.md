# Private Psychotherapy Clinic Management System

A web application to manage patients, treatment notes, files, and receipts for a private psychotherapy clinic.

## Features
- List patients by status (Ongoing, Candidate, Archived).
- Add new patients.
- View patient details.
- Add treatment notes.
- Upload files (documents, images).
- Add receipts.
- Manage therapy groups from a dedicated overview page.
- Schedule one-time or recurring group sessions.
- Record group session summaries and per-member attendance notes.
- Open group sessions directly from the weekly calendar.
- Secure file storage and downloads.
- CSRF protection.
- Organize patient dropdown by type and name for quick selection.
- Edit appointment date and time directly in the booking panel.
- Schedule meetings as online, in-person, or phone consultations.
- Add meeting remarks to appointments.
- Mark meetings as recurring with weekly scheduling (configurable per patient status).
- Support custom booking types via "Other" option.
- Track recurring appointment series with proper deletion handling.

## Group Management
- The Groups overview page supports creating groups, editing core group metadata, and archiving or permanently deleting groups.
- Each group has a dedicated workspace for:
   - group info,
   - session scheduling,
   - member management,
   - membership history,
   - session record documentation.
- Removing a patient from a group supports three outcomes:
   - remove from the group only,
   - move the patient to archived records,
   - permanently delete the patient and related data.
- Recurring group sessions can end either by number of meetings or by a specific date.
- Clicking a group session in the calendar opens the matching group-session record directly.

## Recent Verification
- Latest full regression run: `python test_app.py`
- Latest reviewed result: `50` tests passed.
- Targeted review also confirmed:
   - group archive and full-delete flows,
   - member archive and patient-data delete flows,
   - direct calendar linking to group session records.

## Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Initialize the database and run the app:
   ```bash
   python app.py
   ```
3. Open http://127.0.0.1:5000 in your browser.

## Testing
Run the tests with:
```bash
python test_app.py
```

## Deploy Live
- Use [LIVE_DEPLOYMENT.md](LIVE_DEPLOYMENT.md) for a production deployment with Docker, Gunicorn, HTTPS, and persistent storage.
- For AWS EC2 in Israel (`il-central-1`), the guide now includes an exact launch checklist and a one-command Ubuntu Docker setup helper.
- Production deploys can be started with `bash scripts/deploy_prod.sh` after `.env.prod` is configured.

## Hebrew Dictionary
- The app supports an editable Hebrew dictionary file at `translations/he.json`.
- You can update or correct translations there without changing Python code.
- Keys are the original English text and values are Hebrew translations.
- Missing keys gracefully fall back to the built-in translation map and then to the original English text.

## Public Self-Booking Link
- Admins can generate a public self-booking link from the Calendar booking tab.
- The public page shows only currently available slots.
- Public booking validation rules:
   - Name is required.
   - Date of birth is optional.
   - At least one contact method is required: phone or email.
- When a public booking is submitted:
   - A new patient is created with `waiting` status.
   - A one-time appointment is created for the selected slot.
   - An admin notification is created for follow-up.
