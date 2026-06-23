from playwright.sync_api import sync_playwright, expect
from datetime import datetime, timedelta
import pyotp
import sqlite3
import time
import os


BASE_URL = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
ADMIN_USERNAME = os.environ.get("VERIFY_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("VERIFY_ADMIN_PASSWORD", "admin")


def _assert_reached_admin_page(page, expected_segment):
    current = page.url
    if "/login" in current:
        raise RuntimeError(f"Unexpected redirect to login while opening {expected_segment}: {current}")
    if expected_segment not in current:
        raise RuntimeError(f"Unexpected destination for {expected_segment}: {current}")

def handle_login(page):
    """Navigate to login page and authenticate as admin, handling 2FA if needed."""
    print("Navigating to login...")
    page.goto(f"{BASE_URL}/login")

    page.fill("#username", ADMIN_USERNAME)
    page.fill("#password", ADMIN_PASSWORD)
    page.click("button[type='submit']")

    if "Setup Two-Factor Authentication" in page.content():
        print("2FA setup page detected")
        secret = page.locator(".font-monospace").inner_text().strip()
        page.click("text=Return to Login")

        page.fill("#username", ADMIN_USERNAME)
        page.fill("#password", ADMIN_PASSWORD)
        page.click("button[type='submit']")

        page.fill("#otp", pyotp.TOTP(secret).now())
        page.click("button[type='submit']")

    elif page.locator("#otp").is_visible():
        print("OTP field visible")
        conn = sqlite3.connect('clinic.db')
        res = conn.execute(
            "SELECT totp_secret FROM users WHERE username=?", (ADMIN_USERNAME,)
        ).fetchone()
        conn.close()

        if res and res[0]:
            page.fill("#otp", pyotp.TOTP(res[0]).now())
            page.fill("#username", ADMIN_USERNAME)
            page.fill("#password", ADMIN_PASSWORD)
            page.click("button[type='submit']")
        else:
            raise RuntimeError("OTP required but no secret found in DB")

    if "/admin/profile" not in page.url:
        expect(page.locator("h2").first).to_contain_text("Ongoing Patients", timeout=5000)

    print("Login successful")


def verify_and_screenshot(page, url, label, output_path):
    """Navigate to a URL, verify admin access, and take a screenshot."""
    print(f"Verifying {label}...")
    page.goto(f"{BASE_URL}{url}")
    _assert_reached_admin_page(page, url)
    page.screenshot(path=output_path)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            handle_login(page)
            page.screenshot(path="verification/1_admin_dashboard.png")

            screenshots = [
                ("/admin/revenue", "Revenue Dashboard", "verification/2_revenue_dashboard.png"),
                ("/admin/slots", "Scheduling", "verification/3_manage_slots.png"),
                ("/admin/resources", "Resources", "verification/4_manage_resources.png"),
            ]

            for url, label, path in screenshots:
                verify_and_screenshot(page, url, label, path)

            print("Verification complete")
        finally:
            browser.close()


if __name__ == "__main__":
    run()
