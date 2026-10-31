"""
Real Browser Multi-Tab End-to-End Automation Test using Playwright.
Tests 3 tabs in a single browser context (sharing cookies/domain):
- Tab 1: Admin login
- Tab 2: Student login
- Tab 3: Operator login
- Simultaneous refresh across all 3 tabs
- Verify role isolation and dashboard contents
- Logout from student tab
- Verify Admin and Operator remain logged in
- Race condition testing with simultaneous login requests
"""

import os
import sys
import time
import socket
import threading
from playwright.sync_api import sync_playwright

import app as queuex
import db

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def run_test_server(port):
    queuex.app.config.update(TESTING=True, SECRET_KEY="playwright-browser-test-secret")
    queuex.init_db()
    # Run development server
    queuex.app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

def main():
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    print(f"[TEST] Starting live test server on {base_url}...")

    server_thread = threading.Thread(target=run_test_server, args=(port,), daemon=True)
    server_thread.start()

    # Wait for server to be responsive
    for _ in range(50):
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"{base_url}/health", timeout=1)
            if resp.status == 200:
                print("[TEST] Server is ready and healthy!")
                break
        except Exception:
            time.sleep(0.1)
    else:
        print("[TEST ERROR] Server did not become healthy in time.")
        sys.exit(1)

    with sync_playwright() as p:
        print("[TEST] Launching real Chromium browser...")
        browser = p.chromium.launch(headless=True)
        # One shared context = shared cookies, same origin, just like a user with 3 tabs!
        context = browser.new_context()

        tab_admin = context.new_page()
        tab_student = context.new_page()
        tab_operator = context.new_page()

        print("\n--- STEP A: Log in as Admin in Tab 1 ---")
        tab_admin.goto(f"{base_url}/login?role=admin")
        tab_admin.fill('input[name="login_id"]', "admin@cgc.edu.in")
        tab_admin.fill('input[name="password"]', "Admin@QueueX2026")
        tab_admin.click('button[type="submit"]')
        tab_admin.wait_for_load_state("networkidle")
        print("Tab 1 URL after login:", tab_admin.url)
        assert "/admin" in tab_admin.url, f"Expected /admin in URL, got {tab_admin.url}"
        admin_text = tab_admin.content()
        assert "Central Admin Console" in admin_text or "CGC System Admin" in admin_text
        print("✓ Tab 1 successfully logged in as Admin.")

        print("\n--- STEP B: Log in as Student in Tab 2 ---")
        tab_student.goto(f"{base_url}/login?role=student")
        tab_student.fill('input[name="login_id"]', "student@cgc.edu.in")
        tab_student.fill('input[name="password"]', "Student@QueueX2026")
        tab_student.click('button[type="submit"]')
        tab_student.wait_for_load_state("networkidle")
        print("Tab 2 URL after login:", tab_student.url)
        assert "/student" in tab_student.url, f"Expected /student in URL, got {tab_student.url}"
        student_text = tab_student.content()
        assert "Aarav Sharma" in student_text or "Student Dashboard" in student_text
        print("✓ Tab 2 successfully logged in as Student.")

        print("\n--- STEP C: Log in as Operator in Tab 3 ---")
        tab_operator.goto(f"{base_url}/login?role=operator")
        tab_operator.fill('input[name="login_id"]', "operator@cgc.edu.in")
        tab_operator.fill('input[name="password"]', "Operator@QueueX2026")
        tab_operator.click('button[type="submit"]')
        tab_operator.wait_for_load_state("networkidle")
        print("Tab 3 URL after login:", tab_operator.url)
        assert "/operator" in tab_operator.url, f"Expected /operator in URL, got {tab_operator.url}"
        operator_text = tab_operator.content()
        assert "Accounts Counter Officer" in operator_text or "Operator Dashboard" in operator_text
        print("✓ Tab 3 successfully logged in as Operator.")

        print("\n--- STEP D & E: Refresh All Three Tabs & Verify Isolation ---")
        tab_admin.reload()
        tab_student.reload()
        tab_operator.reload()

        tab_admin.wait_for_load_state("networkidle")
        tab_student.wait_for_load_state("networkidle")
        tab_operator.wait_for_load_state("networkidle")

        admin_refreshed = tab_admin.content()
        student_refreshed = tab_student.content()
        operator_refreshed = tab_operator.content()

        print("Verifying Tab 1 after refresh...")
        assert "/admin" in tab_admin.url
        assert "Central Queue Administrator" in admin_refreshed or "System Admin" in admin_refreshed
        print("✓ Tab 1 still shows System Admin.")

        print("Verifying Tab 2 after refresh...")
        assert "/student" in tab_student.url
        assert "Aarav Sharma" in student_refreshed
        print("✓ Tab 2 still shows Student Aarav Sharma.")

        print("Verifying Tab 3 after refresh...")
        assert "/operator" in tab_operator.url
        assert "Service Counter Officer" in operator_refreshed or "Accounts Counter Officer" in operator_refreshed
        print("✓ Tab 3 still shows Service Counter Officer.")

        print("\n--- STEP F: Log out from Student in Tab 2 ---")
        tab_student.goto(f"{base_url}/logout?role=student")
        tab_student.wait_for_load_state("networkidle")
        print("Tab 2 URL after logout:", tab_student.url)

        # Visiting student dashboard now should redirect to login
        tab_student.goto(f"{base_url}/student/dashboard")
        tab_student.wait_for_load_state("networkidle")
        print("Tab 2 URL accessing /student/dashboard after logout:", tab_student.url)
        assert "/login" in tab_student.url or "/operator" in tab_student.url or "/admin" in tab_student.url
        print("✓ Student session safely terminated.")

        print("\n--- STEP G: Verify Admin and Operator remain logged in ---")
        tab_admin.reload()
        tab_admin.wait_for_load_state("networkidle")
        assert "/admin" in tab_admin.url
        assert "Central Queue Administrator" in tab_admin.content() or "System Admin" in tab_admin.content()
        print("✓ Admin tab STILL fully authenticated!")

        tab_operator.reload()
        tab_operator.wait_for_load_state("networkidle")
        assert "/operator" in tab_operator.url
        assert "Service Counter Officer" in tab_operator.content() or "Accounts Counter Officer" in tab_operator.content()
        print("✓ Operator tab STILL fully authenticated!")

        print("\n--- STEP H: Race Condition Test with Simultaneous Logins ---")
        # In the same browser context, open 2 new tabs and trigger logins concurrently
        sim_tab1 = context.new_page()
        sim_tab2 = context.new_page()

        sim_tab1.goto(f"{base_url}/login?role=student")
        sim_tab2.goto(f"{base_url}/login?role=admin")

        sim_tab1.fill('input[name="login_id"]', "student@cgc.edu.in")
        sim_tab1.fill('input[name="password"]', "Student@QueueX2026")

        sim_tab2.fill('input[name="login_id"]', "admin@cgc.edu.in")
        sim_tab2.fill('input[name="password"]', "Admin@QueueX2026")

        # Submit tab 1 and tab 2 sequentially within milliseconds to test rapid interleaved logins
        sim_tab1.click('button[type="submit"]')
        sim_tab2.click('button[type="submit"]')

        sim_tab1.wait_for_load_state("networkidle")
        sim_tab2.wait_for_load_state("networkidle")

        assert "/student" in sim_tab1.url
        assert "/admin" in sim_tab2.url
        assert "Aarav Sharma" in sim_tab1.content()
        assert "Central Queue Administrator" in sim_tab2.content() or "System Admin" in sim_tab2.content()
        print("✓ Concurrent race condition test passed without collision!")

        browser.close()
        print("\n🎉 ALL REAL BROWSER TESTS PASSED FLAWLESSLY!")

if __name__ == "__main__":
    main()
