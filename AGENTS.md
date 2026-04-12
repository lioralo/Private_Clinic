# Instructions

## Running Tests
To run the tests, execute:
`python -m unittest discover -s tests -p 'test_*.py'`

Run root-level test modules as well:
`python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

## Running the App
To run the application:
1. `pip install -r requirements.txt`
2. `python app.py`

## CSRF Protection
CSRF protection is enabled. When running tests, ensure `WTF_CSRF_ENABLED` is set to `False` in the app config.
