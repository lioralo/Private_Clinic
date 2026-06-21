# Instructions

## Running Tests
To run the tests, execute:
`python -m unittest discover -s tests -p 'test_*.py'`

### Environment variables required for tests
```powershell
$env:SECRET_KEY = "test-secret-key-for-testing-12345"
$env:FLASK_ENV = "development"
$env:TESTING = "1"
```

For Google OAuth tests also set:
```powershell
$env:GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
$env:GOOGLE_OAUTH_CLIENT_SECRET = "test-secret"
```

## Running the App
To run the application:
1. `pip install -r requirements.txt`
2. `python app.py`

## CSRF Protection
CSRF protection is enabled. When running tests, ensure `WTF_CSRF_ENABLED` is set to `False` in the app config.
