# Private Psychotherapy Clinic Management System

A web application to manage patients, treatment notes, files, and receipts for a private psychotherapy clinic.

## Features
- List patients by status (Ongoing, Candidate, Archived).
- Add new patients.
- View patient details.
- Add treatment notes.
- Upload files (documents, images).
- Add receipts.
- Secure file storage and downloads.
- CSRF protection.

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
