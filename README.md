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
