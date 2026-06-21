import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import app

def check_smtp():
    print("Testing SMTP configuration...")
    host = app.config.get('MAIL_SERVER', os.environ.get('MAIL_SERVER'))
    port = int(app.config.get('MAIL_PORT', os.environ.get('MAIL_PORT', 587)))
    user = app.config.get('MAIL_USERNAME', os.environ.get('MAIL_USERNAME'))
    password = app.config.get('MAIL_PASSWORD', os.environ.get('MAIL_PASSWORD'))
    use_tls = str(app.config.get('MAIL_USE_TLS', os.environ.get('MAIL_USE_TLS', 'True'))).lower() in ['true', '1', 't', 'yes']

    if not all([host, port, user, password]):
        print("Error: Missing SMTP configuration in environment.")
        print(f"Server: {host}:{port}, User: {user}")
        sys.exit(1)

    print(f"Connecting to {host}:{port} (TLS: {use_tls})...")

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.starttls()
        
        server.login(user, password)
        print("✅ SMTP connection and login successful!")
        server.quit()
        sys.exit(0)
    except Exception as e:
        print(f"❌ SMTP check failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    check_smtp()
