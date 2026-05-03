from playwright.sync_api import sync_playwright
import os


BASE_URL = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
ADMIN_USERNAME = os.environ.get("VERIFY_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("VERIFY_ADMIN_PASSWORD", "admin")
PATIENT_USERNAME = os.environ.get("VERIFY_PATIENT_USERNAME", "verifypat")
PATIENT_PASSWORD = os.environ.get("VERIFY_PATIENT_PASSWORD", "password")

def verify_features():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        try:
            # Login as Admin
            print("Logging in as Admin...")
            page.goto(f"{BASE_URL}/login")
            page.fill("input[name='username']", ADMIN_USERNAME)
            page.fill("input[name='password']", ADMIN_PASSWORD)

            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")

            # Current app can redirect admin users to /patients OR /admin/profile.
            if not ("/patients" in page.url or "/admin/profile" in page.url):
                raise RuntimeError(f"Unexpected post-login destination: {page.url}")

            print("Logged in. Verifying Agenda...")
            page.goto(f"{BASE_URL}/agenda")
            page.screenshot(path="verification_agenda.png")

            print("Verifying core admin pages...")
            page.goto(f"{BASE_URL}/patients")
            page.wait_for_load_state("networkidle")
            page.screenshot(path="verification_patient_dashboard.png")

            page.goto(f"{BASE_URL}/add_patient")
            page.wait_for_load_state("networkidle")
            page.screenshot(path="verification_patient_detail.png")

            page.goto(f"{BASE_URL}/messages")
            page.wait_for_load_state("networkidle")
            page.screenshot(path="verification_admin_chat.png")

            # Logout
            print("Logging out...")
            page.goto(f"{BASE_URL}/logout")
            print("Done.")

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

if __name__ == "__main__":
    verify_features()
