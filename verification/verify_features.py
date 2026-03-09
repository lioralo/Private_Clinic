from playwright.sync_api import sync_playwright, expect
from datetime import datetime, timedelta
import pyotp
import sqlite3
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # --- 1. Admin Login & 2FA Setup ---
        print("Navigating to login...")
        page.goto("http://127.0.0.1:5000/login")

        # Initial login attempt
        page.fill("#username", "admin")
        page.fill("#password", "admin")
        page.click("button[type='submit']")

        if "Setup Two-Factor Authentication" in page.content():
            print("Detected 2FA Setup Page.")
            secret_el = page.locator(".font-monospace")
            secret = secret_el.inner_text().strip()
            print(f"Secret: {secret}")
            page.click("text=Return to Login")
            print("Logging in again with OTP...")
            page.fill("#username", "admin")
            page.fill("#password", "admin")
            page.click("button[type='submit']")

            totp = pyotp.TOTP(secret)
            otp = totp.now()
            page.fill("#otp", otp)
            page.click("button[type='submit']")

        elif page.locator("#otp").is_visible():
            print("OTP field visible immediately.")
            conn = sqlite3.connect('clinic.db')
            cursor = conn.cursor()
            res = cursor.execute("SELECT secret_token FROM users WHERE username='admin'").fetchone()
            conn.close()

            if res and res[0]:
                secret = res[0]
                totp = pyotp.TOTP(secret)
                otp = totp.now()
                page.fill("#otp", otp)

                # Refill credentials if cleared
                page.fill("#username", "admin")
                page.fill("#password", "admin")

                page.click("button[type='submit']")
            else:
                print("Error: OTP required but no secret found in DB.")
                return

        # --- 2. Verify Dashboard ---
        print("Verifying Dashboard...")
        try:
            expect(page.locator("h2").first).to_contain_text("Ongoing Patients", timeout=5000)
            print("Login successful.")
        except AssertionError:
            print(f"Login failed. Current URL: {page.url}")
            return

        page.screenshot(path="verification/1_admin_dashboard.png")

        # --- 3. Verify Revenue Dashboard ---
        print("Verifying Revenue Dashboard...")
        page.click("a[href='/admin/revenue']")
        # Use first h2 or specific text locator to avoid strict mode error
        expect(page.locator("h2").first).to_contain_text("Revenue Dashboard")
        page.screenshot(path="verification/2_revenue_dashboard.png")

        # --- 4. Verify Scheduling ---
        print("Verifying Scheduling...")
        page.click("#navbarDropdown")
        page.click("a[href='/admin/slots']")

        expect(page.locator("h2").first).to_contain_text("Scheduling Management")

        start_t = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT10:00")
        end_t = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT11:00")

        page.fill("input[name='start_time']", start_t)
        page.fill("input[name='end_time']", end_t)
        page.click("button:has-text('Create Slot')")

        expect(page.locator("body")).to_contain_text("Slot created")
        page.screenshot(path="verification/3_manage_slots.png")

        # --- 5. Verify Resources ---
        print("Verifying Resources...")
        page.click("#navbarDropdown")
        page.click("a[href='/admin/resources']")
        expect(page.locator("h2").first).to_contain_text("Resource Library")
        page.screenshot(path="verification/4_manage_resources.png")

        print("Verification Complete.")
        browser.close()

if __name__ == "__main__":
    run()
