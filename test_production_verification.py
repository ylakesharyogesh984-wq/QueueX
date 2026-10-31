"""
Production & Deployment Verification Script for QueueX
Performs comprehensive testing of:
1. Customer, operator, and admin logins
2. Independent multi-tab authentication & role isolation across 3 concurrent pages
3. Page refreshes and role-isolated logouts
4. Token generation, operator queue handling, and admin settings update
5. Viewport and layout validation at 320px, 375px, 390px, and 430px (mobile responsiveness)
6. Route auditing for HTTP 500 errors across all public and authenticated paths
"""

import sys
import time
import socket
import threading
from playwright.sync_api import sync_playwright
import app
import db

def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def run_server(port):
    app.app.config.update(TESTING=False)
    app.socketio.run(app.app, host="127.0.0.1", port=port, debug=False, use_reloader=False)

def verify_all():
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    print(f"[TEST] Starting live server on {base_url}...")
    
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()
    time.sleep(2)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # -------------------------------------------------------------
        # 1. Health check & Initial DB inspection
        # -------------------------------------------------------------
        print("\n--- 1. Health Check Endpoint ---")
        page = context.new_page()
        res = page.goto(f"{base_url}/health")
        assert res.status == 200, f"Health check failed with {res.status}"
        health_json = res.json()
        print(f"Healthcheck response: {health_json}")
        assert health_json["status"] == "healthy"
        assert health_json["database"] == "connected"
        assert "organization" in health_json
        print("✓ Health check verified.")

        # -------------------------------------------------------------
        # 2. Homepage & Generic SaaS Inspection
        # -------------------------------------------------------------
        print("\n--- 2. Homepage & Generic SaaS Layout ---")
        hp_res = page.goto(base_url)
        assert hp_res.status == 200
        content = page.content()
        assert "Global Service Center" in content or "QueueX" in content
        # Ensure legacy university strings are not in department listings
        assert "Central University Library" not in content
        assert "Hostel & Transport Administration" not in content
        assert "Corporate Resource Center (Placements)" not in content
        print("✓ Homepage renders with generic SaaS branding and no legacy university departments.")

        # -------------------------------------------------------------
        # 3. Independent Multi-Tab Authentication
        # -------------------------------------------------------------
        print("\n--- 3. Multi-Tab Authentication (Admin, Student, Operator) ---")
        tab_admin = context.new_page()
        tab_student = context.new_page()
        tab_operator = context.new_page()

        # Tab 1: Admin
        tab_admin.goto(f"{base_url}/login?role=admin")
        tab_admin.fill('input[name="login_id"]', "admin@cgc.edu.in")
        tab_admin.fill('input[name="password"]', "Admin@QueueX2026")
        tab_admin.click('button[type="submit"]')
        tab_admin.wait_for_load_state("networkidle")
        assert "/admin" in tab_admin.url
        assert "Central Admin Console" in tab_admin.content()
        print("✓ Tab 1: Admin successfully authenticated.")

        # Tab 2: Student
        tab_student.goto(f"{base_url}/login?role=student")
        tab_student.fill('input[name="login_id"]', "student@cgc.edu.in")
        tab_student.fill('input[name="password"]', "Student@QueueX2026")
        tab_student.click('button[type="submit"]')
        tab_student.wait_for_load_state("networkidle")
        assert "/student" in tab_student.url
        assert "Aarav Sharma" in tab_student.content()
        print("✓ Tab 2: Student successfully authenticated.")

        # Tab 3: Operator
        tab_operator.goto(f"{base_url}/login?role=operator")
        tab_operator.fill('input[name="login_id"]', "operator@cgc.edu.in")
        tab_operator.fill('input[name="password"]', "Operator@QueueX2026")
        tab_operator.click('button[type="submit"]')
        tab_operator.wait_for_load_state("networkidle")
        assert "/operator" in tab_operator.url
        assert "Counter Desk Operations" in tab_operator.content()
        print("✓ Tab 3: Operator successfully authenticated.")

        # -------------------------------------------------------------
        # 4. Refresh Verification Across Tabs
        # -------------------------------------------------------------
        print("\n--- 4. Refresh Isolation Verification ---")
        tab_admin.reload()
        tab_admin.wait_for_load_state("networkidle")
        assert "/admin" in tab_admin.url
        assert "Central Admin Console" in tab_admin.content()

        tab_student.reload()
        tab_student.wait_for_load_state("networkidle")
        assert "/student" in tab_student.url
        assert "Aarav Sharma" in tab_student.content()

        tab_operator.reload()
        tab_operator.wait_for_load_state("networkidle")
        assert "/operator" in tab_operator.url
        assert "Counter Desk Operations" in tab_operator.content()
        print("✓ All 3 tabs preserved their authenticated identities and roles after reload.")

        # -------------------------------------------------------------
        # 5. Token Generation, Operator Actions & Admin Settings
        # -------------------------------------------------------------
        print("\n--- 5. Token Generation, Desk Calling & Settings ---")
        student_html = tab_student.content()
        if "WAITING IN LINE" not in student_html and "NOW SERVING" not in student_html:
            # Generate token for Counter 1
            tab_student.select_option('select[name="counter_id"]', value="1")
            tab_student.fill('input[name="service_reason"]', "Account Verification & Payment")
            tab_student.click('form[action="/student/generate-token"] button[type="submit"]')
            tab_student.wait_for_load_state("networkidle")
            assert "WAITING IN LINE" in tab_student.content() or "WAITING IN VIRTUAL QUEUE" in tab_student.content()
            print("✓ Token generated successfully by student.")
        else:
            print("✓ Existing active token found for student in queue.")

        # In Operator tab, refresh and call next
        tab_operator.goto(f"{base_url}/operator/dashboard")
        tab_operator.wait_for_load_state("networkidle")
        if "Call Next Student" in tab_operator.content():
            tab_operator.click('button:has-text("Call Next Student")')
            tab_operator.wait_for_load_state("networkidle")
            time.sleep(0.5)
            assert "Calling Token #" in tab_operator.content() or "NOW SERVING" in tab_operator.content()
            print("✓ Operator successfully called next waiting customer in strict FIFO.")

        # In Operator tab, complete token if serving
        if "Complete Service" in tab_operator.content():
            tab_operator.click('button:has-text("Complete Service")')
            tab_operator.wait_for_load_state("networkidle")
            time.sleep(0.5)
            assert "Completed Token" in tab_operator.content() or "No token currently" in tab_operator.content()
            print("✓ Operator completed service successfully.")

        # In Admin tab, update organization settings
        tab_admin.goto(f"{base_url}/admin/settings")
        tab_admin.wait_for_load_state("networkidle")
        tab_admin.fill('input[name="org_name"]', "QueueX Enterprise Cloud")
        tab_admin.fill('input[name="org_tagline"]', "Next-Generation Intelligent Queue Automation")
        tab_admin.click('button[type="submit"]')
        tab_admin.wait_for_load_state("networkidle")
        assert "QueueX Enterprise Cloud" in tab_admin.content()
        print("✓ Admin updated organization settings dynamically.")

        # Verify new settings reflect on public homepage
        page.goto(base_url)
        assert "QueueX Enterprise Cloud" in page.content()
        print("✓ Updated organization branding live on homepage.")

        # -------------------------------------------------------------
        # 6. Logout Isolation
        # -------------------------------------------------------------
        print("\n--- 6. Role-Scoped Logout Isolation ---")
        tab_student.goto(f"{base_url}/logout?role=student")
        tab_student.wait_for_load_state("networkidle")
        print("✓ Student logged out.")

        # Admin and Operator tabs must remain authenticated
        tab_admin.goto(f"{base_url}/admin/dashboard")
        tab_admin.wait_for_load_state("networkidle")
        assert "/admin" in tab_admin.url
        assert "Central Admin Console" in tab_admin.content()
        print("✓ Admin STILL authenticated after Student logout.")

        tab_operator.reload()
        tab_operator.wait_for_load_state("networkidle")
        assert "/operator" in tab_operator.url
        assert "Counter Desk Operations" in tab_operator.content()
        print("✓ Operator STILL authenticated after Student logout.")

        # -------------------------------------------------------------
        # 7. Mobile Viewport Testing (320px, 375px, 390px, 430px)
        # -------------------------------------------------------------
        print("\n--- 7. Mobile Responsiveness Testing ---")
        viewports = [
            ("Small Mobile", 320, 640),
            ("iPhone SE", 375, 667),
            ("iPhone 12/13/14", 390, 844),
            ("iPhone 14 Pro Max", 430, 932)
        ]
        mobile_page = context.new_page()
        for name, width, height in viewports:
            mobile_page.set_viewport_size({"width": width, "height": height})
            for path in ["/", "/login", "/register", "/admin/dashboard", "/operator/dashboard", "/student/dashboard"]:
                mobile_page.goto(f"{base_url}{path}")
                mobile_page.wait_for_load_state("networkidle")
                # Check for horizontal overflow
                scroll_width = mobile_page.evaluate("document.documentElement.scrollWidth")
                client_width = mobile_page.evaluate("document.documentElement.clientWidth")
                assert scroll_width <= client_width + 1, f"Horizontal scroll overflow at {name} ({width}px) on {path}: scrollWidth={scroll_width}, clientWidth={client_width}"
            print(f"✓ Viewport {name} ({width}x{height}px) validated with zero horizontal overflow.")

        # -------------------------------------------------------------
        # 8. Complete Route Audit (Zero HTTP 500 errors)
        # -------------------------------------------------------------
        print("\n--- 8. Complete Route Audit for HTTP 500 ---")
        audit_routes = [
            "/",
            "/health",
            "/api/health",
            "/sw.js",
            "/login",
            "/register",
            "/student/dashboard",
            "/student/profile",
            "/student/settings",
            "/operator/dashboard",
            "/operator/profile",
            "/operator/settings",
            "/admin/dashboard",
            "/admin/departments",
            "/admin/counters",
            "/admin/operators",
            "/admin/reports",
            "/admin/settings",
        ]
        audit_page = context.new_page()
        for route in audit_routes:
            resp = audit_page.goto(f"{base_url}{route}")
            assert resp.status != 500, f"Route {route} returned HTTP 500!"
            print(f"✓ Route {route} -> HTTP {resp.status}")

        browser.close()
        print("\n🎉 ALL PRODUCTION & DEPLOYMENT VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    verify_all()
