"""
Frontend verification using Playwright.
Logs in as admin, screenshots key pages, then logs out.
"""

import os
import sys
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
ADMIN_USERNAME = os.environ.get("VERIFY_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("VERIFY_ADMIN_PASSWORD", "admin")


def take_screenshot(page, url, label, output_name):
    print(f"  {label}...")
    page.goto(f"{BASE_URL}{url}")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=output_name)


def verify_features():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        try:
            print("Logging in as Admin...")
            page.goto(f"{BASE_URL}/login")
            page.fill("input[name='username']", ADMIN_USERNAME)
            page.fill("input[name='password']", ADMIN_PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")

            valid_destinations = ["/patients", "/admin/profile"]
            if not any(dest in page.url for dest in valid_destinations):
                raise RuntimeError(f"Unexpected post-login destination: {page.url}")
            print("Login successful")

            pages_to_verify = [
                ("/agenda", "Agenda", "verification_agenda.png"),
                ("/patients", "Patient Dashboard", "verification_patient_dashboard.png"),
                ("/add_patient", "Add Patient", "verification_patient_detail.png"),
                ("/messages", "Messages", "verification_admin_chat.png"),
            ]

            for url, label, filename in pages_to_verify:
                take_screenshot(page, url, label, filename)

            print("Logging out...")
            page.goto(f"{BASE_URL}/logout")
            print("Done.")

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()


def main():
    verify_features()


if __name__ == "__main__":
    main()
