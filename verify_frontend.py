from playwright.sync_api import sync_playwright

def verify_features():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        try:
            # Login as Admin
            print("Logging in as Admin...")
            page.goto("http://127.0.0.1:5000/login")
            page.fill("input[name='username']", "admin")
            page.fill("input[name='password']", "admin")

            with page.expect_navigation(url="**/patients*"):
                page.click("button[type='submit']")

            print("Logged in. Verifying Agenda...")
            page.goto("http://127.0.0.1:5000/agenda")
            page.screenshot(path="verification_agenda.png")

            # Add Verification Patient
            print("Adding Patient...")
            page.goto("http://127.0.0.1:5000/add_patient")
            page.fill("input[name='name']", "Verification Patient")
            page.select_option("select[name='status']", "ongoing")

            with page.expect_navigation(url="**/patients*"):
                page.click("button[type='submit']")

            print("Verifying Patient Detail...")
            # Click the first view profile button (assuming new patient is at top or list is short)
            # Or use reliable selector.
            # Let's try to click the first profile button.
            page.click(".card a.btn-outline-primary") # Matches View Profile buttons

            page.wait_for_selector("text=Clinical Notes")
            page.screenshot(path="verification_patient_detail.png")

            # Create User Access for Patient to test Chat
            print("Creating Patient User...")
            page.fill("input[name='username']", "verifypat")
            page.fill("input[name='password']", "password")

            # Click Grant/Update Access
            page.click("button:has-text('Access')")
            page.wait_for_timeout(1000)

            # Send Message as Admin
            print("Sending Message as Admin...")
            # We need to make sure we are targeting the right form.
            # The admin chat form is at bottom right usually.
            # Use specific placeholder
            page.fill("textarea[placeholder='Message patient...']", "Hello from Admin")
            page.click("form[action*='send_message'] button")
            page.wait_for_timeout(1000)

            page.screenshot(path="verification_admin_chat.png")

            # Logout
            print("Logging out...")
            page.goto("http://127.0.0.1:5000/logout")

            # Login as Patient
            print("Logging in as Patient...")
            page.goto("http://127.0.0.1:5000/login")
            page.fill("input[name='username']", "verifypat")
            page.fill("input[name='password']", "password")

            with page.expect_navigation(url="**/dashboard"):
                 page.click("button[type='submit']")

            # Verify Dashboard (Financial & Chat)
            print("Verifying Dashboard...")
            # Check for message content
            if page.locator("text=Hello from Admin").count() > 0:
                print("Message received!")
            else:
                print("Message NOT found!")

            page.screenshot(path="verification_patient_dashboard.png")

            # Send message as Patient
            print("Sending Message as Patient...")
            page.fill("textarea[placeholder='Type your message...']", "Hello from Patient")
            page.click("form[action*='contact_admin'] button")
            page.wait_for_timeout(1000)

            page.screenshot(path="verification_patient_chat_sent.png")
            print("Done.")

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

if __name__ == "__main__":
    verify_features()
