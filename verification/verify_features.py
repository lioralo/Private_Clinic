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

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # --- 1. Admin Login & 2FA Setup ---
        print("Navigating to login...")
        page.goto(f"{BASE_URL}/login")

        # Initial login attempt
        page.fill("#username", ADMIN_USERNAME)
        page.fill("#password", ADMIN_PASSWORD)
        page.click("button[type='submit']")

        if "Setup Two-Factor Authentication" in page.content():
            print("Detected 2FA Setup Page.")
            secret_el = page.locator(".font-monospace")
            secret = secret_el.inner_text().strip()
            print(f"Secret: {secret}")
            page.click("text=Return to Login")
            print("Logging in again with OTP...")
            page.fill("#username", ADMIN_USERNAME)
            page.fill("#password", ADMIN_PASSWORD)
            page.click("button[type='submit']")

            totp = pyotp.TOTP(secret)
            otp = totp.now()
            page.fill("#otp", otp)
            page.click("button[type='submit']")

        elif page.locator("#otp").is_visible():
            print("OTP field visible immediately.")
            conn = sqlite3.connect('clinic.db')
            cursor = conn.cursor()
            res = cursor.execute("SELECT totp_secret FROM users WHERE username=?", (ADMIN_USERNAME,)).fetchone()
            conn.close()

            if res and res[0]:
                secret = res[0]
                totp = pyotp.TOTP(secret)
                otp = totp.now()
                page.fill("#otp", otp)

                # Refill credentials if cleared
                page.fill("#username", ADMIN_USERNAME)
                page.fill("#password", ADMIN_PASSWORD)

                page.click("button[type='submit']")
            else:
                print("Error: OTP required but no secret found in DB.")
                return

        # --- 2. Verify Dashboard ---
        print("Verifying Dashboard...")
        # Current flow may place admins in /patients or /admin/profile.
        if "/admin/profile" in page.url:
            print("Login successful (admin profile flow).")
        else:
            try:
                expect(page.locator("h2").first).to_contain_text("Ongoing Patients", timeout=5000)
                print("Login successful.")
            except AssertionError:
                print(f"Login failed. Current URL: {page.url}")
                return

        page.screenshot(path="verification/1_admin_dashboard.png")

        # --- 3. Verify Revenue Dashboard ---
        print("Verifying Revenue Dashboard...")
        page.goto(f"{BASE_URL}/admin/revenue")
        _assert_reached_admin_page(page, "/admin/revenue")
        page.screenshot(path="verification/2_revenue_dashboard.png")

        # --- 4. Verify Scheduling ---
        print("Verifying Scheduling...")
        page.goto(f"{BASE_URL}/admin/slots")
        _assert_reached_admin_page(page, "/admin/slots")
        page.screenshot(path="verification/3_manage_slots.png")

        # --- 5. Verify Resources ---
        print("Verifying Resources...")
        page.goto(f"{BASE_URL}/admin/resources")
        _assert_reached_admin_page(page, "/admin/resources")
        page.screenshot(path="verification/4_manage_resources.png")

        print("Verification Complete.")
        browser.close()

if __name__ == "__main__":
    run()
