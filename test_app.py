"""
QueueX Test Suite - Phase 1 Foundation & Phase 2/3 Student Portal Verification
"""

import os
import resource
import tempfile
import unittest

try:
    _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(8192, _hard), _hard))
except Exception:
    pass

import app as queuex
import db


class QueueXComprehensiveTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()

        queuex.db.DB_NAME = self.db_file.name
        queuex.app.config.update(TESTING=True, SECRET_KEY="test-queux-secret")
        
        # Override sqlite resolver for temporary test database
        queuex.db.resolve_sqlite_path = lambda: self.db_file.name
        queuex.init_db()
        self.client = queuex.app.test_client()

    def tearDown(self):
        if os.path.exists(self.db_file.name):
            try:
                os.unlink(self.db_file.name)
            except Exception:
                pass

    def login_student(self):
        return self.client.post("/login", data={
            "login_id": "student@cgc.edu.in",
            "password": "Student@QueueX2026",
            "role": "student"
        }, follow_redirects=True)

    # -------------------------------------------------------------------------
    # Foundation Tests
    # -------------------------------------------------------------------------

    def test_health_check_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["system"], "QueueX Smart Virtual Queue System")

    def test_landing_page_active_counters(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("QueueX", html)
        self.assertIn("Fee Deposit Counter 1", html)

    def test_student_registration_and_login(self):
        reg_resp = self.client.post("/register", data={
            "full_name": "Simran Preet",
            "email": "simran@cgc.edu.in",
            "roll_no": "2201099",
            "phone": "9812345678",
            "department": "CSE",
            "course": "B.Tech",
            "semester": "6",
            "password": "Password@123",
            "confirm_password": "Password@123"
        }, follow_redirects=True)
        self.assertEqual(reg_resp.status_code, 200)

        login_resp = self.client.post("/login", data={
            "login_id": "2201099",
            "password": "Password@123",
            "role": "student"
        }, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn("Student Queue Portal", login_resp.get_data(as_text=True))

    def test_operator_and_admin_logins(self):
        op_resp = self.client.post("/login", data={
            "login_id": "operator@cgc.edu.in",
            "password": "Operator@QueueX2026",
            "role": "operator"
        }, follow_redirects=True)
        self.assertEqual(op_resp.status_code, 200)

        adm_resp = self.client.post("/login", data={
            "login_id": "admin@cgc.edu.in",
            "password": "Admin@QueueX2026",
            "role": "admin"
        }, follow_redirects=True)
        self.assertEqual(adm_resp.status_code, 200)

    # -------------------------------------------------------------------------
    # Phase 3 Student Portal Tests
    # -------------------------------------------------------------------------

    def test_student_dashboard_view(self):
        self.login_student()
        resp = self.client.get("/student/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Customer / Student Queue Portal", html)
        self.assertIn("Aarav Sharma", html)
        self.assertTrue("Fee &amp; Accounts Section" in html or "Billing &amp; Financial Services" in html)

    def test_token_generation_workflow(self):
        """Student generates a token for Counter 1, then verifies status and QR."""
        self.login_student()
        gen_resp = self.client.post("/student/generate-token", data={
            "counter_id": "1",
            "service_reason": "Semester Tuition Fee Payment"
        }, follow_redirects=True)
        self.assertEqual(gen_resp.status_code, 200)
        html = gen_resp.get_data(as_text=True)
        self.assertIn("Token #1", html)
        self.assertIn("Fee Deposit Counter 1", html)
        self.assertIn("WAITING IN VIRTUAL QUEUE", html)
        self.assertIn("data:image/png;base64,", html)  # QR code generated

    def test_duplicate_active_token_prevention(self):
        """Student cannot generate a second token while an active token exists."""
        self.login_student()
        # Generate token 1
        self.client.post("/student/generate-token", data={
            "counter_id": "1",
            "service_reason": "First Token"
        })
        # Attempt to generate token 2
        dup_resp = self.client.post("/student/generate-token", data={
            "counter_id": "2",
            "service_reason": "Second Token"
        }, follow_redirects=True)
        self.assertEqual(dup_resp.status_code, 200)
        html = dup_resp.get_data(as_text=True)
        self.assertIn("You already have an active queue token", html)

    def test_token_cancellation(self):
        """Student can cancel their waiting token."""
        self.login_student()
        self.client.post("/student/generate-token", data={
            "counter_id": "1",
            "service_reason": "Cancel Me"
        })
        cancel_resp = self.client.post("/student/token/cancel/1", follow_redirects=True)
        self.assertEqual(cancel_resp.status_code, 200)
        html = cancel_resp.get_data(as_text=True)
        self.assertIn("Your queue token has been cancelled", html)

    def test_api_token_status_polling(self):
        """Live API endpoint returns real-time queue position and wait time."""
        self.login_student()
        self.client.post("/student/generate-token", data={
            "counter_id": "1",
            "service_reason": "Live Polling Test"
        })
        api_resp = self.client.get("/api/student/token/1/status")
        self.assertEqual(api_resp.status_code, 200)
        data = api_resp.get_json()
        self.assertEqual(data["status"], "waiting")
        self.assertEqual(data["token_number"], 1)
        self.assertEqual(data["people_ahead"], 0)
        self.assertEqual(data["estimated_mins"], 0)

    def test_student_profile_update(self):
        """Student can update profile information."""
        self.login_student()
        resp = self.client.post("/student/profile", data={
            "full_name": "Aarav S. Sharma",
            "phone": "9988776655",
            "department": "IT",
            "course": "B.Tech",
            "semester": "7"
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Profile updated successfully!", resp.get_data(as_text=True))

    def test_student_change_password(self):
        """Student can change account password."""
        self.login_student()
        resp = self.client.post("/student/settings", data={
            "action": "change_password",
            "current_password": "Student@QueueX2026",
            "new_password": "NewSecretPassword@123",
            "confirm_password": "NewSecretPassword@123"
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Password changed successfully!", resp.get_data(as_text=True))

    # -------------------------------------------------------------------------
    # Phase 4 Operator Portal Tests
    # -------------------------------------------------------------------------

    def login_operator(self):
        return self.client.post("/login", data={
            "login_id": "operator@cgc.edu.in",
            "password": "Operator@QueueX2026",
            "role": "operator"
        }, follow_redirects=True)

    def test_operator_dashboard_view(self):
        """Operator can access counter desk with assigned counter."""
        self.login_operator()
        resp = self.client.get("/operator/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Counter Desk Operations", html)
        self.assertTrue("ACCOUNTS-W1" in html or "FIN-W1" in html)
        self.assertTrue("Accounts Counter Officer" in html or "Service Counter Officer" in html)

    def test_operator_call_next_and_complete(self):
        """Student generates token, operator calls next, and completes service."""
        # 1. Student generates Token #1 for Counter 1
        self.login_student()
        self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "Exam Fee"})

        # 2. Operator logs in and calls next
        self.login_operator()
        call_resp = self.client.post("/operator/call-next", follow_redirects=True)
        self.assertEqual(call_resp.status_code, 200)
        html_call = call_resp.get_data(as_text=True)
        self.assertIn("Calling Token #1", html_call)
        self.assertIn("Aarav Sharma", html_call)

        # 3. Operator marks token completed
        comp_resp = self.client.post("/operator/complete/1", follow_redirects=True)
        self.assertEqual(comp_resp.status_code, 200)
        self.assertIn("marked as Completed", comp_resp.get_data(as_text=True))

    def test_operator_skip_and_recall(self):
        """Operator can skip a token and recall it."""
        # 1. Student generates Token #1
        self.login_student()
        self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "No Show Test"})

        # 2. Operator calls next
        self.login_operator()
        self.client.post("/operator/call-next")

        # 3. Operator skips token
        skip_resp = self.client.post("/operator/skip/1", follow_redirects=True)
        self.assertEqual(skip_resp.status_code, 200)
        self.assertIn("has been skipped", skip_resp.get_data(as_text=True))

        # 4. Operator recalls skipped token
        recall_resp = self.client.post("/operator/recall/1", follow_redirects=True)
        self.assertEqual(recall_resp.status_code, 200)
        self.assertIn("Recalled Token #1 back to Counter Desk", recall_resp.get_data(as_text=True))

    def test_operator_pause_resume_counter(self):
        """Operator can pause and resume the queue."""
        self.login_operator()
        pause_resp = self.client.post("/operator/pause", follow_redirects=True)
        self.assertEqual(pause_resp.status_code, 200)
        self.assertIn("Queue has been paused temporarily", pause_resp.get_data(as_text=True))

        resume_resp = self.client.post("/operator/resume", follow_redirects=True)
        self.assertEqual(resume_resp.status_code, 200)
        self.assertIn("Queue operations resumed", resume_resp.get_data(as_text=True))

    def test_operator_close_reopen_counter(self):
        """Operator can close and reopen counter desk."""
        self.login_operator()
        close_resp = self.client.post("/operator/toggle-counter", data={"action": "close"}, follow_redirects=True)
        self.assertEqual(close_resp.status_code, 200)
        self.assertIn("is now Closed", close_resp.get_data(as_text=True))

        open_resp = self.client.post("/operator/toggle-counter", data={"action": "open"}, follow_redirects=True)
        self.assertEqual(open_resp.status_code, 200)
        self.assertIn("is now Open", open_resp.get_data(as_text=True))

    def test_operator_profile_and_settings(self):
        """Operator can update profile and change password."""
        self.login_operator()
        prof_resp = self.client.post("/operator/profile", data={
            "full_name": "Accounts Officer Incharge",
            "phone": "9998887776"
        }, follow_redirects=True)
        self.assertEqual(prof_resp.status_code, 200)
        self.assertIn("Profile updated successfully!", prof_resp.get_data(as_text=True))

        pw_resp = self.client.post("/operator/settings", data={
            "action": "change_password",
            "current_password": "Operator@QueueX2026",
            "new_password": "NewOperatorPass@2026",
            "confirm_password": "NewOperatorPass@2026"
        }, follow_redirects=True)
        self.assertEqual(pw_resp.status_code, 200)
        self.assertIn("Password updated successfully!", pw_resp.get_data(as_text=True))

    # -------------------------------------------------------------------------
    # Phase 5 Admin Portal Tests
    # -------------------------------------------------------------------------

    def login_admin(self):
        return self.client.post("/login", data={
            "login_id": "admin@cgc.edu.in",
            "password": "Admin@QueueX2026",
            "role": "admin"
        }, follow_redirects=True)

    def test_admin_dashboard_metrics(self):
        """Admin can access central dashboard with traffic and counter metrics."""
        self.login_admin()
        resp = self.client.get("/admin/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Central Queue Administration", html)
        self.assertIn("Tokens Today", html)
        self.assertIn("Active Desks", html)
        self.assertIn("Weekly Queue Traffic Trend", html)

    def test_admin_department_crud(self):
        """Admin can add, edit, and toggle departments."""
        self.login_admin()
        # Create
        create_resp = self.client.post("/admin/departments/create", data={
            "code": "ADMISSIONS",
            "name": "Admissions & Counselling Cell",
            "description": "New admissions, fee seat allotments, documents",
            "building_block": "Block 2 Ground Floor"
        }, follow_redirects=True)
        self.assertEqual(create_resp.status_code, 200)
        self.assertIn("Admissions & Counselling Cell", create_resp.get_data(as_text=True))

        # Edit
        edit_resp = self.client.post("/admin/departments/edit/7", data={
            "name": "Admissions, Counselling & Visas",
            "description": "Updated description",
            "building_block": "Block 2 First Floor",
            "is_active": "1"
        }, follow_redirects=True)
        self.assertEqual(edit_resp.status_code, 200)
        self.assertIn("Department updated successfully", edit_resp.get_data(as_text=True))

        # Toggle Active
        toggle_resp = self.client.post("/admin/departments/toggle/7", follow_redirects=True)
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertIn("status changed", toggle_resp.get_data(as_text=True))

    def test_admin_counter_management(self):
        """Admin can create counters and control their open/close states."""
        self.login_admin()
        # Create Counter
        create_resp = self.client.post("/admin/counters/create", data={
            "name": "Express Clearance Window",
            "code": "EXAM-W2",
            "department_id": "4",
            "avg_service_time_mins": "5"
        }, follow_redirects=True)
        self.assertEqual(create_resp.status_code, 200)
        self.assertIn("EXAM-W2", create_resp.get_data(as_text=True))

        # Pause counter action
        pause_resp = self.client.post("/admin/counters/action/8", data={"action": "pause"}, follow_redirects=True)
        self.assertEqual(pause_resp.status_code, 200)
        self.assertIn("is now updated (pause)", pause_resp.get_data(as_text=True))

        # Close counter action
        close_resp = self.client.post("/admin/counters/action/8", data={"action": "close"}, follow_redirects=True)
        self.assertEqual(close_resp.status_code, 200)
        self.assertIn("is now updated (close)", close_resp.get_data(as_text=True))

    def test_admin_operator_provision_and_assign(self):
        """Admin creates operator accounts and assigns them to counter windows."""
        self.login_admin()
        # Provision operator
        create_resp = self.client.post("/admin/operators/create", data={
            "full_name": "Gurmeet Singh",
            "identifier": "OP202",
            "email": "gurmeet@cgc.edu.in",
            "phone": "9811223344",
            "password": "Password@2026",
            "counter_id": "3"  # Counter 3: Bonafide & Character Certificate Window
        }, follow_redirects=True)
        self.assertEqual(create_resp.status_code, 200)
        self.assertIn("Operator account created for Gurmeet Singh", create_resp.get_data(as_text=True))

        # Reassign to another counter
        assign_resp = self.client.post("/admin/operators/assign/4", data={"counter_id": "4"}, follow_redirects=True)
        self.assertEqual(assign_resp.status_code, 200)
        self.assertIn("Operator desk assignment updated", assign_resp.get_data(as_text=True))

        # Toggle operator status (deactivate)
        toggle_resp = self.client.post("/admin/operators/toggle/4", follow_redirects=True)
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertIn("account status changed", toggle_resp.get_data(as_text=True))

    def test_admin_reports_and_csv_export(self):
        """Admin can view filtered daily reports and download CSV exports."""
        # 1. Create a token first
        self.login_student()
        self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "CSV Report Verification"})

        # 2. View Admin Report
        self.login_admin()
        resp = self.client.get("/admin/reports")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Daily Queue Audit & Analytics", html)
        self.assertIn("CSV Report Verification", html)

        # 3. Download CSV
        csv_resp = self.client.get("/admin/reports/export.csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertEqual(csv_resp.mimetype, "text/csv")
        csv_text = csv_resp.get_data(as_text=True)
        self.assertIn("Token ID,Token Number,Department", csv_text)
        self.assertIn("CSV Report Verification", csv_text)

    def test_admin_settings_branding(self):
        """Admin can configure dynamic SaaS organization branding and details."""
        self.login_admin()
        resp = self.client.get("/admin/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Organization & SaaS Branding", resp.get_data(as_text=True))

        post_resp = self.client.post("/admin/settings", data={
            "org_name": "Apex Health Systems",
            "org_subtitle": "Clinical Care & Patient Flow",
            "org_tagline": "Next-Gen Healthcare Virtual Queue",
            "org_address": "Medical Plaza • Suite 400",
            "org_support_email": "help@apexhealth.com",
            "org_support_phone": "+1 (888) 555-0100"
        }, follow_redirects=True)
        self.assertEqual(post_resp.status_code, 200)
        self.assertIn("Apex Health Systems", post_resp.get_data(as_text=True))

    def test_admin_access_control(self):
        """Students and Operators are strictly blocked from admin routes."""
        # Student access blocked
        self.login_student()
        resp = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/student", resp.headers["Location"])

        # Operator access blocked
        self.login_operator()
        resp_op = self.client.get("/admin/departments", follow_redirects=False)
        self.assertEqual(resp_op.status_code, 302)
        self.assertIn("/operator", resp_op.headers["Location"])

    # -------------------------------------------------------------------------
    # Phase 6: Real Functionality, Concurrency Hardening & Security Tests
    # -------------------------------------------------------------------------

    def test_concurrent_token_generation_unique_and_sequential(self):
        """Simultaneous token generation across concurrent threads generates sequential tokens with no duplicates."""
        import concurrent.futures

        # Seed 10 distinct students
        created_student_ids = []
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            for i in range(1, 11):
                email = f"concurrent_student_{i}@cgc.edu.in"
                roll = f"CGC2026CC{i:03d}"
                c.execute("""
                    INSERT INTO users (email, password_hash, full_name, role, identifier, phone, department, course, semester)
                    VALUES (?, ?, ?, 'student', ?, '9876543210', 'CSE', 'B.Tech', 6)
                """, (email, "hash", f"Student {i}", roll))
                created_student_ids.append(c.lastrowid)
            conn.commit()

        results = []

        def generate_for_student(idx, uid):
            with queuex.app.test_client() as c_thread:
                # Set server-side session token cookie
                token = f"test_session_token_concurrent_{idx}"
                c_thread.set_cookie(queuex.SESSION_COOKIE_NAME, token)
                with queuex.db.get_db() as conn:
                    c = conn.cursor()
                    c.execute("""
                        INSERT OR REPLACE INTO auth_sessions (session_token, role, user_id, user_name, user_email, user_identifier, expires_at)
                        VALUES (?, 'student', ?, ?, ?, ?, datetime('now', '+7 days'))
                    """, (token, uid, f"Student {idx}", f"concurrent_student_{idx}@cgc.edu.in", f"CGC2026CC{idx:03d}"))
                    conn.commit()

                resp = c_thread.post("/student/generate-token", data={"counter_id": "1", "service_reason": f"Concurrency Test {idx}"}, follow_redirects=True)
                return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(generate_for_student, i+1, uid) for i, uid in enumerate(created_student_ids)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        self.assertEqual(len(results), 10)
        for code in results:
            self.assertEqual(code, 200)

        # Verify tokens in DB
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT token_number FROM tokens WHERE counter_id = 1 ORDER BY token_number ASC")
            tokens = [row["token_number"] for row in c.fetchall()]

        # All 10 tokens must be strictly unique and sequential
        self.assertEqual(len(tokens), 10)
        self.assertEqual(len(set(tokens)), 10)
        self.assertEqual(tokens, list(range(1, 11)))

    def test_prevent_duplicate_active_tokens_for_same_student(self):
        """A student cannot hold multiple active waiting/serving tokens."""
        self.login_student()

        # Token 1
        resp1 = self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "First Token"}, follow_redirects=True)
        self.assertIn("Token #1 generated successfully", resp1.get_data(as_text=True))

        # Attempt Token 2 while Token 1 is active
        resp2 = self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "Second Token"}, follow_redirects=True)
        self.assertIn("You already have an active queue token", resp2.get_data(as_text=True))

        # Verify only 1 token exists in DB for this student (user id = 3)
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as count FROM tokens WHERE student_id = 3 AND status IN ('waiting', 'serving')")
            self.assertEqual(c.fetchone()["count"], 1)

    def test_cannot_generate_token_for_closed_or_paused_counter(self):
        """Students cannot generate tokens when a counter is paused or closed."""
        self.login_student()

        # Pause counter 1
        with queuex.db.get_db() as conn:
            conn.cursor().execute("UPDATE counters SET is_paused = 1 WHERE id = 1")
            conn.commit()

        resp_paused = self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "Paused Test"}, follow_redirects=True)
        self.assertIn("currently paused", resp_paused.get_data(as_text=True))

        # Close counter 1
        with queuex.db.get_db() as conn:
            conn.cursor().execute("UPDATE counters SET is_paused = 0, is_active = 0 WHERE id = 1")
            conn.commit()

        resp_closed = self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "Closed Test"}, follow_redirects=True)
        self.assertIn("currently closed", resp_closed.get_data(as_text=True))

    def test_idor_protection_student_cannot_cancel_others_token(self):
        """A student cannot cancel another student's token."""
        # 1. Student 1 generates token
        self.login_student()
        self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "Student 1 Token"})

        # 2. Register and login Student 2
        self.client.post("/register", data={
            "full_name": "Second Student",
            "email": "student2@cgc.edu.in",
            "roll_no": "CGC2026S002",
            "phone": "9876543211",
            "department": "CSE",
            "course": "B.Tech",
            "semester": "6",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        self.client.post("/login", data={"login_id": "student2@cgc.edu.in", "password": "Password123!", "role": "student"})

        # Student 2 tries to cancel Student 1's token (id=1)
        resp = self.client.post("/student/token/cancel/1", follow_redirects=True)
        self.assertIn("Token not found or unauthorized", resp.get_data(as_text=True))

        # Check Token 1 is still waiting
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT status FROM tokens WHERE id = 1")
            self.assertEqual(c.fetchone()["status"], "waiting")

    def test_operator_strict_fifo_and_state_guards(self):
        """Tokens are strictly called in FIFO order, and invalid transitions are rejected."""
        # Seed 2 students and 2 tokens
        self.login_student()
        self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "Order 1"})

        # Seed student 2 token directly with valid token_salt
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO tokens (token_number, student_id, student_name, student_roll, counter_id, department_id, service_reason, status, token_salt)
                VALUES (2, 99, 'Student Two', 'CGC99', 1, 1, 'Order 2', 'waiting', 'mock_salt_99')
            """)
            conn.commit()

        # Login operator
        self.login_operator()

        # Call next -> Must be Token #1
        resp1 = self.client.post("/operator/call-next", follow_redirects=True)
        self.assertIn("Calling Token #1", resp1.get_data(as_text=True))

        # Operator tries to call next AGAIN without completing or skipping Token #1 -> Must be blocked
        resp_blocked = self.client.post("/operator/call-next", follow_redirects=True)
        self.assertIn("currently being served. Complete or skip it before calling next", resp_blocked.get_data(as_text=True))

        # Operator completes Token #1
        resp_comp = self.client.post("/operator/complete/1", follow_redirects=True)
        self.assertIn("marked as Completed", resp_comp.get_data(as_text=True))

        # Operator attempts to complete Token #1 again -> Must fail with warning
        resp_repeat = self.client.post("/operator/complete/1", follow_redirects=True)
        self.assertIn("Only currently serving tokens can be marked completed", resp_repeat.get_data(as_text=True))

        # Now call next -> Must be Token #2
        resp2 = self.client.post("/operator/call-next", follow_redirects=True)
        self.assertIn("Calling Token #2", resp2.get_data(as_text=True))

        # Skip Token #2
        resp_skip = self.client.post("/operator/skip/2", follow_redirects=True)
        self.assertIn("has been skipped", resp_skip.get_data(as_text=True))

        # Recall Token #2
        resp_recall = self.client.post("/operator/recall/2", follow_redirects=True)
        self.assertIn("Recalled Token #2 back to Counter Desk", resp_recall.get_data(as_text=True))

    # -------------------------------------------------------------------------
    # Phase 7: Production Readiness & Deployment Verification Tests
    # -------------------------------------------------------------------------

    def test_production_security_headers_present(self):
        """Security headers (nosniff, SAMEORIGIN, etc.) are attached to HTTP responses."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_database_idempotent_restart_data_preservation(self):
        """Re-running init_db() preserves user records, tokens, and departmental configuration."""
        # 1. Register a student
        self.client.post("/register", data={
            "full_name": "Idempotent User",
            "email": "idempotent@cgc.edu.in",
            "roll_no": "CGC2026ID01",
            "phone": "9876543210",
            "department": "CSE",
            "course": "B.Tech",
            "semester": "6",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })

        # 2. Simulate server restart
        queuex.init_db()

        # 3. Verify student still exists and can login
        login_resp = self.client.post("/login", data={
            "login_id": "idempotent@cgc.edu.in",
            "password": "Password123!",
            "role": "student"
        }, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn("Idempotent User", login_resp.get_data(as_text=True))

    def test_end_to_end_student_to_operator_lifecycle(self):
        """End-to-end flow: Student registers, generates token, operator opens counter, calls, and completes."""
        # Step A: Register student
        self.client.post("/register", data={
            "full_name": "E2E Student",
            "email": "e2e@cgc.edu.in",
            "roll_no": "CGC2026E2E",
            "phone": "9123456789",
            "department": "CSE",
            "course": "B.Tech",
            "semester": "6",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })

        # Step B: Login and generate token
        self.client.post("/login", data={"login_id": "e2e@cgc.edu.in", "password": "Password123!", "role": "student"})
        gen_resp = self.client.post("/student/generate-token", data={"counter_id": "1", "service_reason": "Semester Exam Fee"}, follow_redirects=True)
        self.assertEqual(gen_resp.status_code, 200)
        self.assertIn("Token #1 generated successfully", gen_resp.get_data(as_text=True))

        # Check status JSON API
        status_resp = self.client.get("/api/student/token/1/status")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.get_json()
        self.assertEqual(status_data["status"], "waiting")
        self.assertEqual(status_data["token_number"], 1)

        # Step C: Operator calls next
        self.login_operator()
        call_resp = self.client.post("/operator/call-next", follow_redirects=True)
        self.assertIn("Calling Token #1", call_resp.get_data(as_text=True))

        # Check token status in database after call
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT status FROM tokens WHERE id = 1")
            self.assertEqual(c.fetchone()["status"], "serving")

        # Step D: Operator completes service
        comp_resp = self.client.post("/operator/complete/1", follow_redirects=True)
        self.assertIn("marked as Completed", comp_resp.get_data(as_text=True))

        # Check token status in database after completion
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT status FROM tokens WHERE id = 1")
            self.assertEqual(c.fetchone()["status"], "served")

    def test_null_resilience_in_templates_and_dashboards(self):
        """Templates render safely without 500 errors when created_at, called_at, or role are NULL."""
        # 1. Insert audit log with NULL created_at and NULL user_role
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details, created_at)
                VALUES ('TEST_NULL_ACTION', NULL, NULL, 'Simulating legacy null created_at', NULL)
            """)
            # Insert token with NULL created_at and NULL called_at
            c.execute("""
                INSERT INTO tokens (token_number, counter_id, department_id, student_id, student_name, student_roll, status, token_salt, created_at, called_at)
                VALUES (999, 1, 1, 3, 'Null Date Student', '2201099', 'serving', 'salt', NULL, NULL)
            """)
            conn.commit()

        # 2. Test Admin Dashboard with NULL audit log
        self.login_admin()
        admin_resp = self.client.get("/admin/dashboard")
        self.assertEqual(admin_resp.status_code, 200)
        self.assertIn("N/A", admin_resp.get_data(as_text=True))
        self.assertIn("TEST_NULL_ACTION", admin_resp.get_data(as_text=True))

        # 3. Test Operator Portal with NULL called_at currently serving
        self.login_operator()
        op_resp = self.client.get("/operator/dashboard")
        self.assertEqual(op_resp.status_code, 200)
        self.assertIn("Null Date Student", op_resp.get_data(as_text=True))

        # 4. Test Student Portal with NULL token created_at
        self.login_student()
        st_resp = self.client.get("/student/dashboard")
        self.assertEqual(st_resp.status_code, 200)

        # 5. Test sw.js endpoint returns 200
        sw_resp = self.client.get("/sw.js")
        self.assertEqual(sw_resp.status_code, 200)
        self.assertEqual(sw_resp.mimetype, "application/javascript")

    def test_multi_tab_independent_authentication(self):
        """
        Verify that a single browser (shared cookie jar across tabs) can be logged in
        simultaneously as Student, Operator, and Admin without overwriting each other.
        Also verify that refreshing each portal retains role identity and logging out
        from one role does not log out the other roles.
        """
        # Step 1: In the same client (simulating shared browser cookie jar), log in as Student
        resp_st = self.client.post("/login", data={
            "login_id": "student@cgc.edu.in",
            "password": "Student@QueueX2026",
            "role": "student"
        }, follow_redirects=True)
        self.assertEqual(resp_st.status_code, 200)
        self.assertIn("Student Dashboard", resp_st.get_data(as_text=True))

        # Step 2: In Tab 2, log in as Operator
        resp_op = self.client.post("/login", data={
            "login_id": "operator@cgc.edu.in",
            "password": "Operator@QueueX2026",
            "role": "operator"
        }, follow_redirects=True)
        self.assertEqual(resp_op.status_code, 200)
        self.assertIn("Operator Dashboard", resp_op.get_data(as_text=True))

        # Step 3: In Tab 3, log in as Admin
        resp_adm = self.client.post("/login", data={
            "login_id": "admin@cgc.edu.in",
            "password": "Admin@QueueX2026",
            "role": "admin"
        }, follow_redirects=True)
        self.assertEqual(resp_adm.status_code, 200)
        self.assertIn("Central Admin Console", resp_adm.get_data(as_text=True))

        # Step 4: Refresh / access Tab 1 (Student Dashboard) -> Should still be Student
        refresh_st = self.client.get("/student/dashboard")
        self.assertEqual(refresh_st.status_code, 200)
        st_content = refresh_st.get_data(as_text=True)
        self.assertIn("Student Dashboard", st_content)
        self.assertIn("Aarav Sharma", st_content)  # Student name

        # Step 5: Refresh / access Tab 2 (Operator Dashboard) -> Should still be Operator
        refresh_op = self.client.get("/operator/dashboard")
        self.assertEqual(refresh_op.status_code, 200)
        op_content = refresh_op.get_data(as_text=True)
        self.assertIn("Operator Dashboard", op_content)
        self.assertTrue("Service Counter Officer" in op_content or "Accounts Counter Officer" in op_content)

        # Step 6: Refresh / access Tab 3 (Admin Dashboard) -> Should still be Admin
        refresh_adm = self.client.get("/admin/dashboard")
        self.assertEqual(refresh_adm.status_code, 200)
        adm_content = refresh_adm.get_data(as_text=True)
        self.assertIn("Central Admin Console", adm_content)
        self.assertTrue("Central Queue Administrator" in adm_content or "System Admin" in adm_content)

        # Step 7: Logout from Tab 1 (Student logout)
        logout_st = self.client.get("/logout?role=student", follow_redirects=True)
        self.assertEqual(logout_st.status_code, 200)

        # Tab 1 should no longer have student session
        with self.client.session_transaction() as sess:
            self.assertNotIn("student", sess.get("roles", {}))

        # Step 8: Tab 2 (Operator) and Tab 3 (Admin) must STILL be authenticated!
        op_after_st_logout = self.client.get("/operator/dashboard")
        self.assertEqual(op_after_st_logout.status_code, 200)
        self.assertIn("Operator Dashboard", op_after_st_logout.get_data(as_text=True))
        self.assertTrue("Service Counter Officer" in op_after_st_logout.get_data(as_text=True) or "Accounts Counter Officer" in op_after_st_logout.get_data(as_text=True))

        adm_after_st_logout = self.client.get("/admin/dashboard")
        self.assertEqual(adm_after_st_logout.status_code, 200)
        self.assertIn("Central Admin Console", adm_after_st_logout.get_data(as_text=True))
        self.assertTrue("Central Queue Administrator" in adm_after_st_logout.get_data(as_text=True) or "System Admin" in adm_after_st_logout.get_data(as_text=True))

        # Step 9: Logout Operator
        logout_op = self.client.get("/logout?role=operator", follow_redirects=True)
        self.assertEqual(logout_op.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn("operator", sess.get("roles", {}))

        # Admin must STILL be authenticated
        adm_after_op_logout = self.client.get("/admin/dashboard")
        self.assertEqual(adm_after_op_logout.status_code, 200)
        self.assertIn("Central Admin Console", adm_after_op_logout.get_data(as_text=True))
        self.assertTrue("Central Queue Administrator" in adm_after_op_logout.get_data(as_text=True) or "System Admin" in adm_after_op_logout.get_data(as_text=True))

        # Step 10: Logout Admin
        logout_adm = self.client.get("/logout?role=admin", follow_redirects=True)
        self.assertEqual(logout_adm.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn("admin", sess.get("roles", {}))
            self.assertEqual(len(sess.get("roles", {})), 0)


if __name__ == "__main__":
    unittest.main()
