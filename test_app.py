import os
import re
import tempfile
import threading
import unittest

import app as queuex
import db


class QueueXTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()

        queuex.DB_NAME = self.db_file.name
        queuex.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        queuex.init_db()
        self.client = queuex.app.test_client()

    def tearDown(self):
        os.unlink(self.db_file.name)

    def login_operator(self):
        return self.client.post(
            "/operator/login",
            data={"username": "operator", "password": "operator123"},
            follow_redirects=True,
        )

    def create_token(self, counter="library"):
        return self.client.post(
            "/get-token",
            data={
                "student_name": "Test Student",
                "roll_no": "21CS001",
                "father_name": "Test Parent",
                "phone": "9876543210",
                "counter": counter,
            },
            follow_redirects=False,
        )

    # ------------------------------------------------------------------ #
    #  Original tests (preserved)                                         #
    # ------------------------------------------------------------------ #

    def test_get_token_redirects_to_status(self):
        response = self.create_token()

        self.assertEqual(response.status_code, 302)
        self.assertIn("/status?counter=library&token=1", response.headers["Location"])

    def test_invalid_status_token_returns_bad_request(self):
        response = self.client.get("/api/status?counter=library&token=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid counter or token")

    def test_call_next_rejects_empty_queue(self):
        self.login_operator()

        response = self.client.post("/api/operator/call-next", data={"counter": "library"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "queue is empty")

    def test_call_next_serves_first_waiting_token(self):
        self.create_token()
        self.login_operator()

        response = self.client.post("/api/operator/call-next", data={"counter": "library"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["current_token"], 1)

        status = self.client.get("/api/status?counter=library&token=1")
        self.assertEqual(status.get_json()["status"], "served")

    def test_index_page_contains_burger_menu(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="burger-btn"', html)
        self.assertIn('id="burger-btn"', html)
        self.assertIn('id="nav-links"', html)
        self.assertIn('aria-controls="nav-links"', html)
        self.assertIn('navbar.js', html)

    def test_student_page_contains_burger_menu(self):
        response = self.client.get("/student")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="burger-btn"', html)
        self.assertIn('id="nav-links"', html)
        self.assertIn('navbar.js', html)

    def test_operator_dashboard_contains_burger_menu(self):
        self.login_operator()
        response = self.client.get("/operator")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="burger-btn"', html)
        self.assertIn('id="nav-links"', html)
        self.assertIn('navbar.js', html)

    def test_admin_dashboard_contains_burger_menu(self):
        self.client.post("/admin/login", data={"username": "superadmin", "password": "super123"})
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="burger-btn"', html)
        self.assertIn('id="nav-links"', html)
        self.assertIn('navbar.js', html)

    def test_static_navbar_js_available(self):
        response = self.client.get("/static/js/navbar.js")
        self.assertEqual(response.status_code, 200)
        js = response.get_data(as_text=True)
        response.close()
        self.assertIn("burgerBtn", js)
        self.assertIn("toggleMenu", js)

    # ------------------------------------------------------------------ #
    #  Fix 1 — Student logout clears both user_id AND role               #
    # ------------------------------------------------------------------ #

    def test_student_logout_clears_session(self):
        """After logout, /my-tokens must redirect to login (session is fully cleared)."""
        # Register and log in a student
        self.client.post("/register", data={
            "full_name": "Alice Test",
            "email": "alice@test.com",
            "phone": "9000000001",
            "roll_no": "21CS999",
            "department": "CS",
            "semester": "3",
            "password": "password1",
            "confirm_password": "password1",
        })
        # Confirm logged in
        r = self.client.get("/my-tokens")
        self.assertEqual(r.status_code, 200)

        # Logout
        self.client.get("/student/logout")

        # Must now be redirected to login — session is cleared
        r2 = self.client.get("/my-tokens")
        self.assertEqual(r2.status_code, 302)
        self.assertIn("/login", r2.headers["Location"])

    # ------------------------------------------------------------------ #
    #  Fix 2 — No duplicate token numbers under concurrent requests      #
    # ------------------------------------------------------------------ #

    def test_no_duplicate_token_numbers(self):
        """Concurrent token requests must produce unique token numbers."""
        results = []
        errors = []

        def make_token():
            with queuex.app.test_client() as c:
                resp = c.post("/get-token", data={
                    "student_name": "Concurrent Student",
                    "roll_no": "21CS002",
                    "father_name": "Parent",
                    "phone": "9000000002",
                    "counter": "library",
                }, follow_redirects=False)
                if resp.status_code == 302:
                    loc = resp.headers["Location"]
                    # Extract token number from redirect URL
                    token_part = [p for p in loc.split("&") if "token=" in p]
                    if token_part:
                        results.append(int(token_part[0].split("=")[1]))
                else:
                    errors.append(resp.status_code)

        threads = [threading.Thread(target=make_token) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Some requests failed: {errors}")
        self.assertEqual(len(results), 5, "Expected 5 successful tokens")
        self.assertEqual(len(set(results)), 5, f"Duplicate tokens found: {results}")

    # ------------------------------------------------------------------ #
    #  Fix 3 — Skipped tokens show 'skipped', not 'served'              #
    # ------------------------------------------------------------------ #

    def test_skipped_token_reports_skipped_status(self):
        """A token that is skipped must return status='skipped', not 'served'."""
        self.create_token()
        self.login_operator()

        self.client.post("/api/operator/skip", data={"counter": "library"})

        status = self.client.get("/api/status?counter=library&token=1")
        data = status.get_json()
        self.assertEqual(data["status"], "skipped")

    def test_served_token_reports_served_status(self):
        """A token that is called/served must return status='served'."""
        self.create_token()
        self.login_operator()
        self.client.post("/api/operator/call-next", data={"counter": "library"})

        status = self.client.get("/api/status?counter=library&token=1")
        self.assertEqual(status.get_json()["status"], "served")

    def test_waiting_token_reports_waiting_status(self):
        """A token still in queue must return status='waiting'."""
        self.create_token()   # token 1
        self.create_token()   # token 2

        self.login_operator()
        self.client.post("/api/operator/call-next", data={"counter": "library"})  # serves token 1

        status = self.client.get("/api/status?counter=library&token=2")
        self.assertEqual(status.get_json()["status"], "waiting")

    def test_skipped_token_has_zero_people_ahead(self):
        """A skipped token must not show a queue position."""
        self.create_token()
        self.login_operator()
        self.client.post("/api/operator/skip", data={"counter": "library"})

        data = self.client.get("/api/status?counter=library&token=1").get_json()
        self.assertEqual(data["people_ahead"], 0)
        self.assertEqual(data["estimated_wait"], 0)

    # ------------------------------------------------------------------ #
    #  Fix 4 — DB-backed operator auth                                   #
    # ------------------------------------------------------------------ #

    def test_operator_login_succeeds_with_correct_credentials(self):
        """Default operator account seeded in init_db must allow login."""
        resp = self.client.post(
            "/operator/login",
            data={"username": "operator", "password": "operator123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/operator", resp.headers["Location"])

    def test_operator_login_fails_with_wrong_password(self):
        resp = self.client.post(
            "/operator/login",
            data={"username": "operator", "password": "wrongpassword"},
            follow_redirects=False,
        )
        # Should stay on login page, not redirect
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Invalid", resp.get_data(as_text=True))

    def test_operator_in_users_table_after_init(self):
        """init_db must create a users row with role='operator'."""
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE role = 'operator'")
        row = c.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["email"], "operator@queuex.internal")

    def test_operator_in_operators_table_after_init(self):
        """init_db must create an operators row linked to the operator user."""
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute(
            """SELECT op.id FROM operators op
               JOIN users u ON u.id = op.user_id
               WHERE u.role = 'operator' AND op.active = 1"""
        )
        row = c.fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_operator_api_rejects_unauthenticated(self):
        """Operator API endpoints must reject requests without a valid session."""
        resp = self.client.post("/api/operator/call-next", data={"counter": "library"})
        self.assertEqual(resp.status_code, 401)

    def test_operator_session_stores_operator_id(self):
        """After login, session must contain operator_id (not just role)."""
        with self.client as c:
            c.post(
                "/operator/login",
                data={"username": "operator", "password": "operator123"},
            )
            with c.session_transaction() as sess:
                self.assertIn("operator_id", sess)
                self.assertIsNotNone(sess["operator_id"])

    def test_student_register_with_email_only(self):
        """Student can register with email only and is automatically logged in."""
        resp = self.client.post(
            "/register",
            data={
                "full_name": "Email Student",
                "email": "email_student@college.edu",
                "phone": "",
                "roll_no": "21CS101",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/student", resp.headers["Location"])

    def test_student_register_with_phone_only(self):
        """Student can register with 10-digit mobile phone only."""
        resp = self.client.post(
            "/register",
            data={
                "full_name": "Phone Student",
                "email": "",
                "phone": "9876543210",
                "roll_no": "21CS102",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/student", resp.headers["Location"])

    def test_student_login_with_phone(self):
        """Student can log in using their 10-digit mobile phone number."""
        # First register with phone
        self.client.post(
            "/register",
            data={
                "full_name": "Mobile User",
                "email": "",
                "phone": "9812345678",
                "roll_no": "21CS103",
                "password": "mypassword",
                "confirm_password": "mypassword",
            },
        )
        # Logout
        self.client.get("/student/logout")

        # Login with mobile number
        resp = self.client.post(
            "/login",
            data={
                "identifier": "9812345678",
                "password": "mypassword",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/student", resp.headers["Location"])

    def test_logged_in_student_can_get_token(self):
        """Logged-in student can issue token without re-typing their details."""
        # Register and log in
        self.client.post(
            "/register",
            data={
                "full_name": "Logged In Student",
                "email": "loggedin@college.edu",
                "phone": "9998887776",
                "roll_no": "21CS104",
                "password": "password123",
                "confirm_password": "password123",
            },
        )

        # Issue token with just counter
        resp = self.client.post(
            "/get-token",
            data={"counter": "library"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/status?counter=library&token=", resp.headers["Location"])

    def test_operator_register_with_phone_only(self):
        """Operator can register with mobile phone number and is redirected to dashboard."""
        resp = self.client.post(
            "/operator/register",
            data={
                "full_name": "Test Op Phone",
                "email": "",
                "phone": "9811122233",
                "employee_id": "OP-999",
                "assigned_counter": "library",
                "password": "operatorpass",
                "confirm_password": "operatorpass",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/operator", resp.headers["Location"])

    def test_operator_login_with_phone(self):
        """Operator can log in using their 10-digit mobile phone number."""
        # Register operator with phone
        self.client.post(
            "/operator/register",
            data={
                "full_name": "Op Phone User",
                "email": "",
                "phone": "9822233344",
                "employee_id": "OP-888",
                "assigned_counter": "library",
                "password": "passoperator",
                "confirm_password": "passoperator",
            },
        )
        # Logout
        self.client.get("/operator/logout")

        # Login with mobile number
        resp = self.client.post(
            "/operator/login",
            data={
                "username": "9822233344",
                "password": "passoperator",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/operator", resp.headers["Location"])

    def test_admin_register_with_phone_only(self):
        """Admin can register with mobile phone number and authorization key."""
        resp = self.client.post(
            "/admin/register",
            data={
                "full_name": "Test Admin Phone",
                "email": "",
                "phone": "9833344455",
                "department": "Dean Office",
                "admin_key": "super123",
                "password": "adminpass123",
                "confirm_password": "adminpass123",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin", resp.headers["Location"])

    def test_admin_login_with_phone(self):
        """Admin can log in using their 10-digit mobile phone number."""
        self.client.post(
            "/admin/register",
            data={
                "full_name": "Admin Phone User",
                "email": "",
                "phone": "9844455566",
                "department": "Campus Security",
                "admin_key": "super123",
                "password": "adminpass456",
                "confirm_password": "adminpass456",
            },
        )
        self.client.get("/admin/logout")

        resp = self.client.post(
            "/admin/login",
            data={
                "username": "9844455566",
                "password": "adminpass456",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin", resp.headers["Location"])

    def test_operator_set_counter_status(self):
        """Operator can change counter status between open, paused, and closed."""
        self.login_operator()
        resp = self.client.post(
            "/api/operator/set-status",
            data={"counter": "library", "status": "paused"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "paused")

        # In paused state, getting token should be rejected
        token_resp = self.client.post("/get-token", data={"counter": "library"})
        self.assertEqual(token_resp.status_code, 400)

        # Reopen
        resp2 = self.client.post(
            "/api/operator/set-status",
            data={"counter": "library", "status": "open"}
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.get_json()["status"], "open")

    def test_status_page_authenticated_student_navigation(self):
        """Logged-in student sees My Tokens and Logout in navbar on status page."""
        self.client.post("/register", data={
            "full_name": "Pass Nav User",
            "email": "navuser@college.edu",
            "roll_no": "21CS777",
            "password": "mypassword1",
            "confirm_password": "mypassword1"
        })
        self.client.post("/get-token", data={"counter": "library"})
        resp = self.client.get("/status?counter=library&token=1")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("/student/logout", html)
        self.assertIn("/my-tokens", html)

    def test_index_shows_dynamic_counter_count(self):
        """Index page renders active counter count matching configured counters."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(f"{len(queuex.COUNTERS)}", html)
        self.assertIn(f"LIVE ACROSS {len(queuex.COUNTERS)} CAMPUS COUNTERS", html)

    def test_100_students_seeded_in_database(self):
        """Database seeds 100 realistic student records with valid unique IDs."""
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student' AND student_uid LIKE 'AIT-24-%'")
        count = c.fetchone()["cnt"]
        conn.close()
        self.assertEqual(count, 100, f"Expected 100 seeded students, got {count}")

    def test_student_login_with_unique_id(self):
        """Student can sign in directly using their Unique Student ID (e.g. AIT-24-CS001)."""
        resp = self.client.post("/login", data={
            "identifier": "AIT-24-CS001",
            "password": "student123"
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/student", resp.headers["Location"])

    def test_admin_can_access_student_database_api(self):
        """Admin can access /api/admin/students to browse and search the student database."""
        # Login admin
        self.client.post("/admin/login", data={"username": "superadmin", "password": "super123"})
        resp = self.client.get("/api/admin/students")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertGreaterEqual(data["total_count"], 100)
        self.assertIn("students", data)
        self.assertEqual(data["college"]["code"], "AIT")

    def test_admin_student_search_and_filter(self):
        """Admin can filter student database by search term and department."""
        self.client.post("/admin/login", data={"username": "superadmin", "password": "super123"})
        
        # Search by unique ID
        resp = self.client.get("/api/admin/students?q=AIT-24-CS001")
        self.assertEqual(resp.status_code, 200)
        students = resp.get_json()["students"]
        self.assertEqual(len(students), 1)
        self.assertEqual(students[0]["student_uid"], "AIT-24-CS001")
        self.assertEqual(students[0]["full_name"], "Aarav Sharma")

        # Filter by department
        resp_dept = self.client.get("/api/admin/students?dept=Computer%20Science")
        self.assertEqual(resp_dept.status_code, 200)
        cs_students = resp_dept.get_json()["students"]
        self.assertEqual(len(cs_students), 20)
        self.assertTrue(all(s["department"] == "Computer Science" for s in cs_students))

    def test_admin_view_student_tokens(self):
        """Admin can inspect individual student tokens via /api/admin/student/<id>/tokens."""
        # Log in student and take token
        self.client.post("/login", data={"identifier": "AIT-24-CS001", "password": "student123"})
        self.client.post("/get-token", data={"counter": "library"})
        self.client.get("/student/logout")

        # Find user ID
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE student_uid = 'AIT-24-CS001'")
        user_id = c.fetchone()["id"]
        conn.close()

        # Admin inspects tokens
        self.client.post("/admin/login", data={"username": "superadmin", "password": "super123"})
        resp = self.client.get(f"/api/admin/student/{user_id}/tokens")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["student"]["student_uid"], "AIT-24-CS001")
        self.assertGreaterEqual(len(data["tokens"]), 1)
        self.assertEqual(data["tokens"][0]["counter_slug"], "library")

    def test_admin_employees_api_and_add_delete(self):
        """Admin can list, provision, and remove operator terminals."""
        self.client.post("/admin/login", data={"username": "superadmin", "password": "super123"})
        
        # List employees
        resp = self.client.get("/api/admin/employees")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("employees", data)

        # Provision new employee
        add_resp = self.client.post("/api/admin/employees/add", data={
            "full_name": "Test Staff Operator",
            "employee_id": "OP-TEST-99",
            "assigned_counter": "library",
            "email": "teststaff99@queuex.internal",
            "phone": "9819999999",
            "password": "operatorpassword"
        })
        self.assertEqual(add_resp.status_code, 200)
        self.assertTrue(add_resp.get_json()["success"])

        # Verify added in DB
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE email = 'teststaff99@queuex.internal'")
        new_user = c.fetchone()
        conn.close()
        self.assertIsNotNone(new_user)

        # Delete employee
        del_resp = self.client.post(f"/api/admin/employees/{new_user['id']}/delete")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.get_json()["success"])

    def test_admin_add_and_delete_student(self):
        """Admin can add a new enrolled student and delete student."""
        self.client.post("/admin/login", data={"username": "superadmin", "password": "super123"})

        add_resp = self.client.post("/api/admin/students/add", data={
            "full_name": "New Enrolled Student",
            "roll_no": "24CS88",
            "department": "Computer Science",
            "semester": "1st",
            "student_uid": "AIT-24-CS088",
            "email": "new_student88@ait.edu",
            "phone": "9818888888",
            "password": "studentpassword"
        })
        self.assertEqual(add_resp.status_code, 200)
        self.assertTrue(add_resp.get_json()["success"])
        new_id = add_resp.get_json()["student"]["id"]

        # Delete student
        del_resp = self.client.post(f"/api/admin/students/{new_id}/delete")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.get_json()["success"])

    # ------------------------------------------------------------------ #
    #  Student System Enhancements Tests                                  #
    # ------------------------------------------------------------------ #

    def test_student_cancel_waiting_token_success(self):
        """Authorized student can cancel their waiting token."""
        # Create token
        resp = self.create_token(counter="library")
        self.assertEqual(resp.status_code, 302)

        # Cancel the waiting token
        cancel_resp = self.client.post("/api/student/cancel-token", json={
            "counter": "library",
            "token": 1
        })
        self.assertEqual(cancel_resp.status_code, 200)
        data = cancel_resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "cancelled")

        # Verify status endpoint reflects cancellation
        status_resp = self.client.get("/api/status?counter=library&token=1")
        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_resp.get_json()["status"], "cancelled")
        self.assertEqual(status_resp.get_json()["people_ahead"], 0)
        self.assertEqual(status_resp.get_json()["estimated_wait"], 0)

    def test_student_cancel_non_waiting_token_rejected(self):
        """Tokens that are served or skipped cannot be cancelled."""
        self.create_token(counter="library")
        self.login_operator()
        # Serve token 1
        self.client.post("/api/operator/call-next", data={"counter": "library"})

        # Try to cancel served token
        cancel_resp = self.client.post("/api/student/cancel-token", json={
            "counter": "library",
            "token": 1
        })
        self.assertEqual(cancel_resp.status_code, 400)
        self.assertIn("already served", cancel_resp.get_json()["error"])

    def test_student_cancel_unauthorized_token_rejected(self):
        """Users cannot cancel tokens they did not create."""
        # Create token with test client 1
        self.create_token(counter="library")

        # Create another test client with fresh session
        with queuex.app.test_client() as stranger_client:
            cancel_resp = stranger_client.post("/api/student/cancel-token", json={
                "counter": "library",
                "token": 1
            })
            self.assertEqual(cancel_resp.status_code, 403)
            self.assertIn("Unauthorized", cancel_resp.get_json()["error"])

    def test_student_token_history_in_my_tokens(self):
        """Logged-in student can view their full token history in /my-tokens."""
        # Register and login student
        self.client.post("/register", data={
            "full_name": "History Student",
            "email": "history_student@ait.edu",
            "phone": "9800055555",
            "roll_no": "24CS55",
            "department": "Computer Science",
            "semester": "5th",
            "password": "password123",
            "confirm_password": "password123"
        })

        # Take two tokens
        self.client.post("/get-token", data={"counter": "library"})
        self.client.post("/get-token", data={"counter": "cafeteria"})

        # Cancel the first token
        self.client.post("/api/student/cancel-token", json={"counter": "library", "token": 1})

        # Fetch my-tokens page
        resp = self.client.get("/my-tokens")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Token #1", html)
        self.assertIn("CANCELLED", html)
        self.assertIn("Token #1", html)
        self.assertIn("WAITING", html)

    def test_status_page_contains_qr_code_element_and_direct_url(self):
        """Status page renders the scannable QR code wrapper and shareable direct link."""
        self.create_token(counter="library")
        resp = self.client.get("/status?counter=library&token=1")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="qr-code"', html)
        self.assertIn('qrcode.min.js', html)
        self.assertIn('id="status-share-url"', html)
        self.assertIn('copyStatusUrl', html)

    def test_estimated_wait_and_people_ahead(self):
        """api_status correctly returns people ahead and estimated waiting time."""
        # Create 3 tokens
        self.create_token(counter="library") # token 1
        self.create_token(counter="library") # token 2
        self.create_token(counter="library") # token 3

        # Check status for token 3 before operator serves anything (current_token is 0)
        resp = self.client.get("/api/status?counter=library&token=3")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["people_ahead"], 2)
        self.assertGreaterEqual(data["estimated_wait"], 4)
        self.assertEqual(data["status"], "waiting")

    def test_student_submit_feedback_page_and_form(self):
        """Students can submit feedback / grievance via the web form."""
        # GET feedback page
        get_resp = self.client.get("/feedback")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn("Student Grievance & Feedback", get_resp.get_data(as_text=True))

        # POST feedback form
        post_resp = self.client.post("/feedback", data={
            "student_name": "Feedback Tester",
            "roll_no": "24CS99",
            "email": "tester@ait.edu",
            "counter": "library",
            "category": "Long Wait Time",
            "subject": "Book checkout queue is very slow today",
            "message": "Waiting over 30 minutes for clearance. Please open another terminal."
        })
        self.assertEqual(post_resp.status_code, 200)
        html = post_resp.get_data(as_text=True)
        self.assertIn("Your feedback has been submitted successfully", html)

        # Verify saved in SQLite database
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE roll_no = '24CS99'")
        complaint = c.fetchone()
        conn.close()
        self.assertIsNotNone(complaint)
        self.assertEqual(complaint["category"], "Long Wait Time")
        self.assertEqual(complaint["subject"], "Book checkout queue is very slow today")
        self.assertEqual(complaint["status"], "pending")

    def test_student_submit_feedback_api(self):
        """Students can submit feedback via JSON API endpoint."""
        resp = self.client.post("/api/feedback", json={
            "student_name": "API Student",
            "roll_no": "24AI01",
            "email": "apistudent@ait.edu",
            "counter": "cafeteria",
            "category": "Suggestion",
            "subject": "Add digital payment counter",
            "message": "Please add UPI QR scanner at counter 2."
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("complaint_id", data)

    def test_feedback_validation_rejects_missing_fields(self):
        """Feedback submission validates required fields."""
        resp = self.client.post("/api/feedback", json={
            "student_name": "",
            "category": "",
            "subject": "",
            "message": ""
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("required", resp.get_json()["error"])

    # ------------------------------------------------------------------ #
    #  Operator Dashboard Feature & Security Tests                       #
    # ------------------------------------------------------------------ #

    def create_assigned_operator(self, username="op_cafe", password="password123", counter_slug="cafeteria"):
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM counters WHERE slug = ?", (counter_slug,))
        crow = c.fetchone()
        cid = crow["id"] if crow else 1
        from werkzeug.security import generate_password_hash
        c.execute(
            """INSERT INTO users (full_name, email, phone, password_hash, role, status)
               VALUES (?, ?, ?, ?, 'operator', 'active')""",
            ("Assigned Operator", f"{username}@test.edu", "9876543299", generate_password_hash(password))
        )
        uid = c.lastrowid
        c.execute(
            """INSERT INTO operators (user_id, employee_id, assigned_counter_id, active)
               VALUES (?, ?, ?, 1)""",
            (uid, username, cid)
        )
        op_id = c.lastrowid
        conn.commit()
        conn.close()
        return username, password, op_id

    def test_operator_assigned_counter_access_control(self):
        """Assigned operators cannot view or manage other counters."""
        username, password, _ = self.create_assigned_operator(
            username="cafe_op", password="cafepassword", counter_slug="cafeteria"
        )
        # Login as cafe operator
        login_resp = self.client.post("/operator/login", data={
            "username": username,
            "password": password
        }, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)

        # Accessing assigned counter (cafeteria) succeeds
        cafe_resp = self.client.get("/api/operator/queue?counter=cafeteria")
        self.assertEqual(cafe_resp.status_code, 200)

        # Accessing unassigned counter (library) is forbidden with 403
        lib_resp = self.client.get("/api/operator/queue?counter=library")
        self.assertEqual(lib_resp.status_code, 403)
        self.assertIn("Unauthorized", lib_resp.get_json()["error"])

        # Mutating unassigned counter is forbidden
        call_resp = self.client.post("/api/operator/call-next", data={"counter": "library"})
        self.assertEqual(call_resp.status_code, 403)

        recall_resp = self.client.post("/api/operator/recall", data={"counter": "library"})
        self.assertEqual(recall_resp.status_code, 403)

        skip_resp = self.client.post("/api/operator/skip", data={"counter": "library"})
        self.assertEqual(skip_resp.status_code, 403)

        reset_resp = self.client.post("/api/operator/reset", data={"counter": "library"})
        self.assertEqual(reset_resp.status_code, 403)

        status_resp = self.client.post("/api/operator/set-status", data={"counter": "library", "status": "paused"})
        self.assertEqual(status_resp.status_code, 403)

    def test_operator_queue_returns_serving_and_student_details(self):
        """Queue API returns currently serving student and detailed waiting queue."""
        # Create 2 tokens with distinct student details
        self.client.post("/get-token", data={
            "student_name": "Alice CS",
            "roll_no": "21CS001",
            "father_name": "Mr. CS",
            "phone": "9876543210",
            "counter": "library"
        })
        self.client.post("/get-token", data={
            "student_name": "Bob EE",
            "roll_no": "21EE002",
            "father_name": "Mr. EE",
            "phone": "9876543211",
            "counter": "library"
        })

        self.login_operator()

        # Call next to serve token 1
        call_resp = self.client.post("/api/operator/call-next", data={"counter": "library"})
        self.assertEqual(call_resp.status_code, 200)

        # Inspect queue data
        queue_resp = self.client.get("/api/operator/queue?counter=library")
        self.assertEqual(queue_resp.status_code, 200)
        data = queue_resp.get_json()

        self.assertEqual(data["current_token"], 1)
        self.assertIsNotNone(data["serving_student"])
        self.assertEqual(data["serving_student"]["student_name"], "Alice CS")
        self.assertEqual(data["serving_student"]["roll_no"], "21CS001")
        self.assertEqual(data["serving_student"]["phone"], "9876543210")
        self.assertIsNotNone(data["serving_student"]["called_at"])

        # Waiting queue contains Bob EE
        self.assertEqual(data["waiting_count"], 1)
        self.assertEqual(len(data["queue"]), 1)
        self.assertEqual(data["queue"][0]["token_number"], 2)
        self.assertEqual(data["queue"][0]["student_name"], "Bob EE")
        self.assertEqual(data["queue"][0]["roll_no"], "21EE002")
        self.assertEqual(data["queue"][0]["phone"], "9876543211")

    def test_operator_pause_and_resume_queue(self):
        """Operators can pause, resume (open), and close counter stations."""
        self.login_operator()

        # Pause counter
        resp = self.client.post("/api/operator/set-status", data={"counter": "library", "status": "paused"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "paused")

        # Students cannot get token when paused
        token_resp = self.create_token(counter="library")
        self.assertEqual(token_resp.status_code, 400)
        self.assertIn("not accepting", token_resp.get_json()["error"])

        # Resume counter
        resp_resume = self.client.post("/api/operator/set-status", data={"counter": "library", "status": "open"})
        self.assertEqual(resp_resume.status_code, 200)
        self.assertEqual(resp_resume.get_json()["status"], "open")

        # Students can now take tokens
        token_ok = self.create_token(counter="library")
        self.assertEqual(token_ok.status_code, 302)

        # Close counter
        resp_close = self.client.post("/api/operator/set-status", data={"counter": "library", "status": "closed"})
        self.assertEqual(resp_close.status_code, 200)
        self.assertEqual(resp_close.get_json()["status"], "closed")

    def test_operator_recall_current_token(self):
        """Operators can recall the current serving token."""
        self.create_token(counter="library")
        self.login_operator()

        self.client.post("/api/operator/call-next", data={"counter": "library"})

        recall_resp = self.client.post("/api/operator/recall", data={"counter": "library"})
        self.assertEqual(recall_resp.status_code, 200)
        data = recall_resp.get_json()
        self.assertEqual(data["current_token"], 1)
        self.assertIn("recalled", data["message"].lower())

    def test_operator_concurrent_call_next_prevents_duplicate_serving(self):
        """Concurrent call-next operations do not double serve the same token."""
        for i in range(4):
            self.client.post("/get-token", data={
                "student_name": f"Student {i}",
                "roll_no": f"21CS00{i}",
                "father_name": "Parent",
                "phone": f"987654321{i}",
                "counter": "library"
            })

        self.login_operator()

        served_tokens = []
        lock = threading.Lock()

        def do_call():
            with queuex.app.test_client() as c:
                c.post("/operator/login", data={"username": "operator", "password": "operator123"})
                res = c.post("/api/operator/call-next", data={"counter": "library"})
                if res.status_code == 200:
                    tok = res.get_json().get("current_token")
                    with lock:
                        served_tokens.append(tok)

        threads = [threading.Thread(target=do_call) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Check that all served tokens are unique (no duplicates)
        self.assertEqual(len(served_tokens), len(set(served_tokens)), f"Duplicate served tokens: {served_tokens}")

    def login_admin(self):
        return self.client.post(
            "/admin/login",
            data={"username": "superadmin", "password": "super123"},
            follow_redirects=True,
        )

    # ------------------------------------------------------------------ #
    #  Admin Dashboard Upgrade Tests                                     #
    # ------------------------------------------------------------------ #

    def test_admin_auth_required_on_all_admin_endpoints(self):
        """Unauthorized access to admin endpoints returns 401."""
        endpoints = [
            ("/api/admin/overview", "GET", None),
            ("/api/admin/analytics", "GET", None),
            ("/api/admin/counters", "GET", None),
            ("/api/admin/counters/add", "POST", {"name": "Test Counter", "location": "Room 101"}),
            ("/api/admin/counters/1/edit", "POST", {"name": "Updated Counter", "location": "Room 102"}),
            ("/api/admin/counters/1/toggle-status", "POST", {"status": "deactivated"}),
            ("/api/admin/counters/1/delete", "POST", None),
            ("/api/admin/students/1/edit", "POST", {"full_name": "New Name", "roll_no": "24CS99"}),
            ("/api/admin/students/1/toggle-status", "POST", {"status": "deactivated"}),
            ("/api/admin/employees/1/edit", "POST", {"full_name": "New Staff", "employee_id": "OP-999"}),
            ("/api/admin/employees/1/toggle-status", "POST", {"active": 0}),
            ("/api/admin/complaints", "GET", None),
            ("/api/admin/complaints/1/reply", "POST", {"admin_reply": "Resolved", "status": "resolved"}),
        ]
        for url, method, data in endpoints:
            if method == "GET":
                resp = self.client.get(url)
            else:
                resp = self.client.post(url, data=data or {})
            self.assertEqual(resp.status_code, 401, f"Expected 401 for unauthorized {method} {url}, got {resp.status_code}")

    def test_admin_overview_metrics_and_kpis(self):
        """Admin overview returns real database KPIs and counters array."""
        self.login_admin()
        resp = self.client.get("/api/admin/overview")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("counters", data)
        self.assertIn("kpis", data)
        kpis = data["kpis"]
        self.assertIn("total_students", kpis)
        self.assertIn("active_students", kpis)
        self.assertIn("total_employees", kpis)
        self.assertIn("active_employees", kpis)
        self.assertIn("total_counters", kpis)
        self.assertIn("active_counters", kpis)
        self.assertIn("waiting_tokens", kpis)
        self.assertIn("served_tokens", kpis)
        self.assertIn("skipped_tokens", kpis)
        self.assertIn("cancelled_tokens", kpis)
        self.assertIn("avg_wait", kpis)
        self.assertIn("pending_complaints", kpis)

    def test_admin_analytics_date_filters_and_breakdowns(self):
        """Admin analytics correctly handles presets and custom date filters, returning status distribution and department throughput."""
        self.login_admin()
        # Today
        resp_today = self.client.get("/api/admin/analytics?date=today")
        self.assertEqual(resp_today.status_code, 200)
        d_today = resp_today.get_json()
        self.assertIn("status_distribution", d_today)
        self.assertIn("tokens_per_counter", d_today)
        self.assertIn("peak_hours", d_today)
        self.assertIn("department_analytics", d_today)

        # Presets and custom YYYY-MM-DD
        for f in ["yesterday", "7days", "30days", "all", "2026-10-31"]:
            resp = self.client.get(f"/api/admin/analytics?date={f}")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["filter_date"], f)

    def test_admin_counter_crud_and_status_toggle(self):
        """Admin can add, edit, toggle status, and delete counters."""
        self.login_admin()

        # Add counter
        resp_add = self.client.post("/api/admin/counters/add", data={
            "name": "Exam Cell",
            "slug": "exam-cell",
            "location": "Academic Block 201",
            "operating_hours": "09:00 AM - 04:00 PM",
            "description": "Admit cards and exam transcripts",
        })
        self.assertEqual(resp_add.status_code, 200)
        c_id = resp_add.get_json()["counter_id"]

        # Check list contains Exam Cell
        resp_list = self.client.get("/api/admin/counters")
        self.assertEqual(resp_list.status_code, 200)
        counters = resp_list.get_json()["counters"]
        self.assertTrue(any(c["id"] == c_id for c in counters))

        # Edit counter
        resp_edit = self.client.post(f"/api/admin/counters/{c_id}/edit", data={
            "name": "Exam & Evaluation Cell",
            "location": "Academic Block 202",
            "operating_hours": "10:00 AM - 05:00 PM",
            "description": "Updated description",
            "status": "paused",
        })
        self.assertEqual(resp_edit.status_code, 200)

        # Toggle status to deactivated
        resp_deact = self.client.post(f"/api/admin/counters/{c_id}/toggle-status", data={
            "status": "deactivated",
        })
        self.assertEqual(resp_deact.status_code, 200)

        # Soft delete counter
        resp_del = self.client.post(f"/api/admin/counters/{c_id}/delete")
        self.assertEqual(resp_del.status_code, 200)

        # Ensure counter is no longer in active/admin list
        resp_after = self.client.get("/api/admin/counters")
        counters_after = resp_after.get_json()["counters"]
        self.assertFalse(any(c["id"] == c_id for c in counters_after))

    def test_admin_student_and_operator_management(self):
        """Admin can edit student/operator profiles and toggle active status."""
        self.login_admin()

        # Get existing students
        resp_s = self.client.get("/api/admin/students")
        students = resp_s.get_json()["students"]
        if students:
            s_id = students[0]["id"]
            # Edit student
            resp_edit = self.client.post(f"/api/admin/students/{s_id}/edit", data={
                "full_name": "Updated Student Name",
                "roll_no": "UPDATED001",
                "department": "AI & Data Science",
                "semester": "5th",
                "phone": "9998887777",
                "email": "updated@ait.edu",
            })
            self.assertEqual(resp_edit.status_code, 200)

            # Toggle status
            resp_tog = self.client.post(f"/api/admin/students/{s_id}/toggle-status", data={
                "status": "deactivated",
            })
            self.assertEqual(resp_tog.status_code, 200)
            self.assertEqual(resp_tog.get_json()["status"], "deactivated")

        # Get existing employees
        resp_e = self.client.get("/api/admin/employees")
        employees = resp_e.get_json()["employees"]
        if employees:
            u_id = employees[0]["user_id"]
            # Edit employee
            resp_edit_e = self.client.post(f"/api/admin/employees/{u_id}/edit", data={
                "full_name": "Updated Operator Name",
                "employee_id": "OP-UPDATED",
                "assigned_counter": "library",
                "phone": "8887776666",
                "email": "op_updated@queuex.internal",
            })
            self.assertEqual(resp_edit_e.status_code, 200)

            # Toggle status
            resp_tog_e = self.client.post(f"/api/admin/employees/{u_id}/toggle-status", data={
                "active": 0,
            })
            self.assertEqual(resp_tog_e.status_code, 200)
            self.assertEqual(resp_tog_e.get_json()["active"], 0)

    def test_admin_complaints_review_and_reply(self):
        """Admin can view complaints, reply with resolution, and notify student."""
        # Student registers/logs in and files complaint
        self.client.post("/student/register", data={
            "full_name": "Complaint Tester",
            "roll_no": "COMP001",
            "department": "Computer Science",
            "semester": "3rd",
            "phone": "9123456789",
            "email": "complaint@ait.edu",
            "password": "pass1234",
            "confirm_password": "pass1234",
        })
        fb_resp = self.client.post("/api/student/complaints", data={
            "student_name": "Complaint Tester",
            "roll_no": "COMP001",
            "email": "complaint@ait.edu",
            "category": "Counter Issue",
            "subject": "Delay at Fee Counter",
            "message": "Waiting for over an hour without counter movement.",
        })
        self.assertEqual(fb_resp.status_code, 200)

        # Admin logs in
        self.login_admin()
        resp_c = self.client.get("/api/admin/complaints?status=pending")
        self.assertEqual(resp_c.status_code, 200)
        complaints = resp_c.get_json()["complaints"]
        self.assertTrue(len(complaints) > 0)
        c_id = complaints[0]["id"]

        # Admin replies
        resp_reply = self.client.post(f"/api/admin/complaints/{c_id}/reply", data={
            "admin_reply": "Investigated and resolved. Counter staff has been assigned.",
            "status": "resolved",
        })
        self.assertEqual(resp_reply.status_code, 200)
        self.assertEqual(resp_reply.get_json()["success"], True)

        # Verify complaint status is now resolved
        resp_resolved = self.client.get("/api/admin/complaints?status=resolved")
        self.assertTrue(any(c["id"] == c_id for c in resp_resolved.get_json()["complaints"]))

    # ------------------------------------------------------------------ #
    #  Security & Functionality Audit Test Suite                         #
    # ------------------------------------------------------------------ #

    def test_csrf_protection_enforced_when_enabled(self):
        """CSRF validation returns 403 on missing or invalid token when CSRF is enabled."""
        try:
            queuex.app.config["CSRF_ENABLED"] = True

            # 1. Missing CSRF token -> 403
            resp_no_csrf = self.client.post("/cancel-token", data={"counter": "library", "token": 1})
            self.assertEqual(resp_no_csrf.status_code, 403)

            # 2. Invalid CSRF token -> 403
            resp_bad_csrf = self.client.post(
                "/cancel-token",
                data={"counter": "library", "token": 1, "csrf_token": "fake_token_12345"}
            )
            self.assertEqual(resp_bad_csrf.status_code, 403)

            # 3. Valid CSRF token -> permitted
            with self.client.session_transaction() as sess:
                sess["csrf_seed"] = "test_valid_seed_12345"
            with queuex.app.test_request_context():
                with self.client.session_transaction() as sess:
                    valid_token = queuex.hmac.new(
                        queuex.app.secret_key.encode() if isinstance(queuex.app.secret_key, str) else queuex.app.secret_key,
                        b"test_valid_seed_12345",
                        queuex.hashlib.sha256
                    ).hexdigest()

            # Now issue request with valid header
            resp_valid = self.client.post(
                "/api/status?counter=library&token=999",
                headers={"X-CSRFToken": valid_token}
            )
            # Route should proceed past CSRF check (e.g. 200 or 400 for bad token parameter, not 403)
            self.assertNotEqual(resp_valid.status_code, 403)
        finally:
            queuex.app.config["CSRF_ENABLED"] = False

    def test_session_fixation_protection(self):
        """Session fixation protection resets prior session state upon authenticating."""
        # Plant attacker data
        with self.client.session_transaction() as sess:
            sess["attacker_planted_token"] = "evil_payload_123"

        # Login as operator
        self.login_operator()

        with self.client.session_transaction() as sess:
            self.assertNotIn("attacker_planted_token", sess)
            self.assertEqual(sess.get("role"), "operator")

        # Plant attacker data again before admin login
        with self.client.session_transaction() as sess:
            sess["attacker_planted_token"] = "evil_payload_456"

        self.login_admin()

        with self.client.session_transaction() as sess:
            self.assertNotIn("attacker_planted_token", sess)
            self.assertEqual(sess.get("role"), "admin")

    def test_password_hashing_security(self):
        """Passwords in database are hashed with strong cryptographic hashes and not plaintext."""
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("SELECT email, password_hash FROM users WHERE password_hash IS NOT NULL")
        rows = c.fetchall()
        conn.close()

        self.assertTrue(len(rows) > 0)
        for r in rows:
            h = r["password_hash"]
            # Werkzeug hashes start with scrypt: or pbkdf2:
            self.assertTrue(h.startswith("scrypt:") or h.startswith("pbkdf2:"), f"Insecure password hash: {h}")
            # Passwords must never match raw test passwords
            self.assertNotEqual(h, "super123")
            self.assertNotEqual(h, "operator123")
            self.assertNotEqual(h, "student123")

    def test_sql_injection_defense(self):
        """SQL injection attacks via parameters are safely thwarted."""
        self.login_admin()

        # 1. Date param injection
        resp_date = self.client.get("/api/admin/analytics?date=' OR 1=1 --")
        self.assertEqual(resp_date.status_code, 200)  # Validated and sanitized to default

        # 2. LIKE query with wildcard escaping
        resp_wildcard = self.client.get("/api/admin/students?q=%25")
        self.assertEqual(resp_wildcard.status_code, 200)

        # 3. Counter slug injection
        resp_counter = self.client.post("/get-token", data={
            "student_name": "Test",
            "roll_no": "24CS01",
            "phone": "9876543210",
            "counter": "library' OR '1'='1"
        })
        self.assertEqual(resp_counter.status_code, 400)
        self.assertEqual(resp_counter.get_json()["error"], "invalid counter")

        # 4. Token id injection
        resp_tok = self.client.post("/cancel-token", data={
            "counter": "library",
            "token": "1; DROP TABLE tokens; --"
        })
        self.assertEqual(resp_tok.status_code, 400)

    def test_token_generation_concurrency(self):
        """Simultaneous token generation across 10 threads produces unique sequential tokens without duplicate numbers."""
        # Ensure library counter is open
        conn = queuex.get_db()
        c = conn.cursor()
        c.execute("UPDATE counters SET status = 'open' WHERE slug = 'library'")
        conn.commit()
        conn.close()

        generated_tokens = []
        lock = threading.Lock()
        errors = []

        def worker(index):
            with queuex.app.test_client() as client:
                res = client.post("/get-token", data={
                    "student_name": f"Concurrent Student {index}",
                    "roll_no": f"CONCUR_{index:03d}",
                    "father_name": "Guardian",
                    "phone": f"98765432{index:02d}",
                    "counter": "library"
                }, follow_redirects=False)

                if res.status_code == 302:
                    loc = res.headers.get("Location", "")
                    tok_match = re.search(r"token=(\d+)", loc)
                    if tok_match:
                        with lock:
                            generated_tokens.append(int(tok_match.group(1)))
                else:
                    with lock:
                        errors.append(f"Worker {index} failed with status {res.status_code}: {res.get_data(as_text=True)}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered errors: {errors}")
        self.assertEqual(len(generated_tokens), 10)
        # Check every generated token is unique
        self.assertEqual(len(generated_tokens), len(set(generated_tokens)), f"Duplicate tokens generated: {generated_tokens}")

    def test_socketio_room_authorization(self):
        """Socket.IO rooms enforce strict authentication & authorization."""
        # 1. Unauthenticated client attempting to join admin_global
        anon_sio = queuex.socketio.test_client(queuex.app)
        anon_sio.emit("join", {"room": "admin_global"})
        received = anon_sio.get_received()
        self.assertTrue(any(r["name"] == "error" and "Unauthorized" in str(r.get("args")) for r in received))
        anon_sio.disconnect()

        # 2. Authenticated Admin joining admin_global succeeds
        with queuex.app.test_client() as admin_client:
            admin_client.post("/admin/login", data={"username": "superadmin", "password": "super123"})
            admin_sio = queuex.socketio.test_client(queuex.app, flask_test_client=admin_client)
            admin_sio.emit("join", {"room": "admin_global"})
            admin_received = admin_sio.get_received()
            self.assertFalse(any(r["name"] == "error" for r in admin_received))
            admin_sio.disconnect()

        # 3. Student joining another student's private user channel is blocked
        with queuex.app.test_client() as student_client:
            # Login student with id 1
            student_client.post("/login", data={"identifier": "AIT-24-CS001", "password": "student123"})
            student_sio = queuex.socketio.test_client(queuex.app, flask_test_client=student_client)
            # Try to join user_999 (another student)
            student_sio.emit("join", {"room": "user_999"})
            received_s = student_sio.get_received()
            self.assertTrue(any(r["name"] == "error" and "Unauthorized" in str(r.get("args")) for r in received_s))
            student_sio.disconnect()

    def test_security_headers_present(self):
        """HTTP responses contain all required modern security headers."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("Content-Security-Policy", resp.headers)
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("Permissions-Policy", resp.headers)

    def test_error_handling_json_vs_html(self):
        """API endpoints return JSON errors while web pages render HTML error cards."""
        # 404 for API route returns JSON
        resp_api = self.client.get("/api/non-existent-endpoint")
        self.assertEqual(resp_api.status_code, 404)
        self.assertTrue(resp_api.is_json)
        self.assertIn("error", resp_api.get_json())

        # 404 for page route returns HTML with error page layout
        resp_page = self.client.get("/non-existent-page-url")
        self.assertEqual(resp_page.status_code, 404)
        self.assertFalse(resp_page.is_json)
        html = resp_page.get_data(as_text=True)
        self.assertIn("Page Not Found", html)
        self.assertIn("offline-card", html)

    def test_input_validation_and_sanitization(self):
        """Input validation rejects invalid phone numbers and enforces length constraints."""
        # Invalid phone (< 10 digits)
        resp_bad_phone = self.client.post("/get-token", data={
            "student_name": "Test Student",
            "roll_no": "24CS01",
            "phone": "12345",
            "counter": "library"
        })
        self.assertEqual(resp_bad_phone.status_code, 400)
        self.assertIn("10 digits", resp_bad_phone.get_json()["error"])

        # Excessively long strings get truncated cleanly without throwing errors
        long_name = "A" * 500
        resp_token = self.client.post("/get-token", data={
            "student_name": long_name,
            "roll_no": "24CS99",
            "phone": "9876543210",
            "counter": "library"
        })
        self.assertEqual(resp_token.status_code, 302)

    # ------------------------------------------------------------------ #
    #  Railway Production Readiness Tests                                #
    # ------------------------------------------------------------------ #

    def test_health_check_endpoint(self):
        """Health-check endpoints /health and /api/health report 200 OK and database connectivity."""
        for path in ("/health", "/api/health"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["database"], "connected")
            self.assertIn("timestamp", data)
            self.assertIn("uptime_seconds", data)

    def test_resolve_database_path_env_vars(self):
        """Database resolver respects volume and environment paths."""
        temp_dir = tempfile.mkdtemp()
        try:
            os.environ["DATABASE_PATH"] = os.path.join(temp_dir, "custom.db")
            resolved = queuex.resolve_database_path()
            self.assertEqual(resolved, os.path.join(temp_dir, "custom.db"))

            os.environ.pop("DATABASE_PATH", None)
            os.environ["DATA_DIR"] = temp_dir
            resolved_dir = queuex.resolve_database_path()
            self.assertEqual(resolved_dir, os.path.join(temp_dir, "queuex.db"))
        finally:
            os.environ.pop("DATABASE_PATH", None)
            os.environ.pop("DATA_DIR", None)
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    def test_session_cookie_settings_in_production(self):
        """Session cookies enforce HttpOnly and SameSite."""
        self.assertTrue(queuex.app.config.get("SESSION_COOKIE_HTTPONLY"))
        self.assertEqual(queuex.app.config.get("SESSION_COOKIE_SAMESITE"), "Lax")

    def test_production_database_safety_enforcement(self):
        """Production environment blocks ephemeral SQLite unless explicitly overridden."""
        old_railway = os.environ.get("RAILWAY_ENVIRONMENT")
        old_url = os.environ.get("DATABASE_URL")
        old_allow = os.environ.get("ALLOW_SQLITE_IN_PRODUCTION")
        try:
            os.environ["RAILWAY_ENVIRONMENT"] = "production"
            os.environ.pop("DATABASE_URL", None)
            os.environ.pop("ALLOW_SQLITE_IN_PRODUCTION", None)

            # 1. Blocks SQLite by default in production
            with self.assertRaises(RuntimeError):
                db.verify_production_database_safety()

            # 2. Allows SQLite with explicit volume override
            os.environ["ALLOW_SQLITE_IN_PRODUCTION"] = "1"
            db.verify_production_database_safety()  # Should not raise

            # 3. Allows PostgreSQL when DATABASE_URL is set
            os.environ.pop("ALLOW_SQLITE_IN_PRODUCTION", None)
            os.environ["DATABASE_URL"] = "postgresql://postgres:secret@localhost:5432/railway"
            db.verify_production_database_safety()  # Should not raise
        finally:
            if old_railway is not None:
                os.environ["RAILWAY_ENVIRONMENT"] = old_railway
            else:
                os.environ.pop("RAILWAY_ENVIRONMENT", None)
            if old_url is not None:
                os.environ["DATABASE_URL"] = old_url
            else:
                os.environ.pop("DATABASE_URL", None)
            if old_allow is not None:
                os.environ["ALLOW_SQLITE_IN_PRODUCTION"] = old_allow
            else:
                os.environ.pop("ALLOW_SQLITE_IN_PRODUCTION", None)

    def test_postgres_cursor_query_adaptation(self):
        """PostgresCursorWrapper translates SQLite SQL syntax to PostgreSQL."""
        # 1. Placeholder replacement
        sql1 = "SELECT * FROM tokens WHERE id = ? AND counter = ?"
        self.assertEqual(
            db.PostgresCursorWrapper.adapt_query(sql1),
            "SELECT * FROM tokens WHERE id = %s AND counter = %s"
        )

        # 2. DDL AUTOINCREMENT replacement
        sql2 = "CREATE TABLE test (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        self.assertEqual(
            db.PostgresCursorWrapper.adapt_query(sql2),
            "CREATE TABLE test (id SERIAL PRIMARY KEY, name TEXT)"
        )

        # 3. PRAGMA stripping
        sql3 = "PRAGMA foreign_keys = ON;"
        self.assertEqual(db.PostgresCursorWrapper.adapt_query(sql3).strip(), "")

        # 4. Date functions
        sql4 = "SELECT * FROM tokens WHERE date(created_at) = date('now')"
        self.assertEqual(
            db.PostgresCursorWrapper.adapt_query(sql4),
            "SELECT * FROM tokens WHERE created_at::DATE = CURRENT_DATE"
        )

        # 5. Strftime hour extraction
        sql5 = "SELECT strftime('%H', created_at) as hr FROM tokens"
        self.assertEqual(
            db.PostgresCursorWrapper.adapt_query(sql5),
            "SELECT TO_CHAR(created_at, 'HH24') as hr FROM tokens"
        )

    def test_postgres_row_wrapper_access(self):
        """PostgresRowWrapper supports case-insensitive dict and index access."""
        class MockCol:
            def __init__(self, name):
                self.name = name

        desc = [MockCol("id"), MockCol("STUDENT_NAME"), MockCol("counter")]
        row = db.PostgresRowWrapper([101, "Alice Smith", "library"], desc)

        # Index access
        self.assertEqual(row[0], 101)
        self.assertEqual(row[1], "Alice Smith")
        self.assertEqual(row[2], "library")

        # Dict access & case-insensitivity
        self.assertEqual(row["id"], 101)
        self.assertEqual(row["student_name"], "Alice Smith")
        self.assertEqual(row["STUDENT_NAME"], "Alice Smith")
        self.assertEqual(row["counter"], "library")
        self.assertEqual(row.get("nonexistent", "fallback"), "fallback")

        # Container methods
        self.assertIn("student_name", row)
        self.assertEqual(row.keys(), ["id", "student_name", "counter"])

    def test_database_url_normalization(self):
        """postgres:// scheme is normalized to postgresql:// for SQLAlchemy/psycopg2."""
        old_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = "postgres://user:pass@ep-host.railway.app:5432/railway"
            self.assertEqual(
                db.get_database_url(),
                "postgresql://user:pass@ep-host.railway.app:5432/railway"
            )
            self.assertTrue(db.is_postgres())
        finally:
            if old_url is not None:
                os.environ["DATABASE_URL"] = old_url
            else:
                os.environ.pop("DATABASE_URL", None)





if __name__ == "__main__":
    unittest.main()
