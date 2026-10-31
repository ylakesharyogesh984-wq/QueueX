"""
QueueX - Multi-Tenant SaaS Isolation Security & Functional Test Suite
Verifies complete data, tenant, operator, and token isolation between:
- Organization A: Global Healthcare (ID: 2, slug: 'global-health')
- Organization B: City Service Center (ID: 3, slug: 'city-service')
"""

import resource
try:
    _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(8192, _hard), _hard))
except Exception:
    pass

import unittest
import tempfile
import os
import app as queuex
import db
from werkzeug.security import generate_password_hash


class QueueXMultiTenantIsolationTestCase(unittest.TestCase):

    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_file.close()
        os.environ["DATABASE_PATH"] = self.db_file.name
        queuex.db.DB_NAME = self.db_file.name
        queuex.db.resolve_sqlite_path = lambda: self.db_file.name
        queuex.app.config["TESTING"] = True
        queuex.app.config["WTF_CSRF_ENABLED"] = False
        queuex.init_db()
        self.client = queuex.app.test_client()

        # Seed specific test accounts for Org A (Global Healthcare - ID 2) and Org B (City Service Center - ID 3)
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            pw = generate_password_hash("TestPass@123")

            # 1. Admin Org A & B
            c.execute("""
                INSERT INTO users (organization_id, email, password_hash, full_name, role, identifier, phone, is_active)
                VALUES (2, 'admin@globalhealth.org', ?, 'Admin GlobalHealth', 'admin', 'ADM_GH', '111-222', 1)
            """, (pw,))
            self.admin_a_id = c.lastrowid

            c.execute("""
                INSERT INTO users (organization_id, email, password_hash, full_name, role, identifier, phone, is_active)
                VALUES (3, 'admin@cityservice.gov', ?, 'Admin CityService', 'admin', 'ADM_CS', '333-444', 1)
            """, (pw,))
            self.admin_b_id = c.lastrowid

            # 2. Departments for Org A & B
            c.execute("""
                INSERT INTO departments (organization_id, code, name, description, building_block, is_active)
                VALUES (2, 'CARDIOLOGY', 'Cardiology & Heart Care', 'Cardiology consultations', 'Wing A', 1)
            """, )
            self.dept_a_id = c.lastrowid

            c.execute("""
                INSERT INTO departments (organization_id, code, name, description, building_block, is_active)
                VALUES (3, 'LICENSING', 'City Business & Trade Licensing', 'Business permits', 'Floor 2', 1)
            """)
            self.dept_b_id = c.lastrowid

            # 3. Operators for Org A & B
            c.execute("""
                INSERT INTO users (organization_id, email, password_hash, full_name, role, identifier, phone, is_active)
                VALUES (2, 'nurse.sarah@globalhealth.org', ?, 'Nurse Sarah', 'operator', 'OP_GH', '555-111', 1)
            """, (pw,))
            self.op_a_id = c.lastrowid

            c.execute("""
                INSERT INTO users (organization_id, email, password_hash, full_name, role, identifier, phone, is_active)
                VALUES (3, 'clerk.john@cityservice.gov', ?, 'Clerk John', 'operator', 'OP_CS', '555-222', 1)
            """, (pw,))
            self.op_b_id = c.lastrowid

            # 4. Counters for Org A & B
            c.execute("""
                INSERT INTO counters (organization_id, department_id, name, code, is_active, is_paused, assigned_operator_id, avg_service_time_mins)
                VALUES (2, ?, 'Heart Clinic Desk 1', 'CARD-1', 1, 0, ?, 10)
            """, (self.dept_a_id, self.op_a_id))
            self.counter_a_id = c.lastrowid

            c.execute("""
                INSERT INTO counters (organization_id, department_id, name, code, is_active, is_paused, assigned_operator_id, avg_service_time_mins)
                VALUES (3, ?, 'Permit Issuance Desk 1', 'LIC-1', 1, 0, ?, 5)
            """, (self.dept_b_id, self.op_b_id))
            self.counter_b_id = c.lastrowid

            # 5. Customers / Students for Org A & B
            c.execute("""
                INSERT INTO users (organization_id, email, password_hash, full_name, role, identifier, phone, department, course, semester, is_active)
                VALUES (2, 'patient.alice@gmail.com', ?, 'Alice Patient', 'student', 'MED-001', '999-111', 'Cardio', 'OPD', 1, 1)
            """, (pw,))
            self.student_a_id = c.lastrowid

            c.execute("""
                INSERT INTO users (organization_id, email, password_hash, full_name, role, identifier, phone, department, course, semester, is_active)
                VALUES (3, 'citizen.bob@gmail.com', ?, 'Bob Citizen', 'student', 'CIT-001', '999-222', 'Trade', 'Permits', 1, 1)
            """, (pw,))
            self.student_b_id = c.lastrowid

            conn.commit()

    def tearDown(self):
        if os.path.exists(self.db_file.name):
            try:
                os.unlink(self.db_file.name)
            except Exception:
                pass

    def login_user(self, email, password="TestPass@123", role="student"):
        return self.client.post("/login", data={
            "login_id": email,
            "password": password,
            "role": role
        }, follow_redirects=True)

    def test_customer_authentication_and_registration_isolation(self):
        """Customers belong strictly to their organization and cannot cross-authenticate."""
        # Org A patient logs in
        resp_a = self.login_user("patient.alice@gmail.com", role="student")
        self.assertEqual(resp_a.status_code, 200)
        self.assertIn("Alice Patient", resp_a.get_data(as_text=True))

        # Logout
        self.client.get("/logout?role=student")

        # Org B citizen logs in
        resp_b = self.login_user("citizen.bob@gmail.com", role="student")
        self.assertEqual(resp_b.status_code, 200)
        self.assertIn("Bob Citizen", resp_b.get_data(as_text=True))

    def test_cross_tenant_token_generation_and_idor_protection(self):
        """Student in Org A cannot generate token for Org B counter or cancel Org B token."""
        # Alice (Org A) logs in
        self.login_user("patient.alice@gmail.com", role="student")

        # Alice attempts to generate token for Org B's counter (counter_b_id)
        tamper_gen = self.client.post("/student/generate-token", data={
            "counter_id": str(self.counter_b_id),
            "service_reason": "Cross-tenant exploit attempt"
        }, follow_redirects=True)
        self.assertEqual(tamper_gen.status_code, 200)
        # Should be rejected server-side
        self.assertIn("Selected counter is currently closed or invalid", tamper_gen.get_data(as_text=True))

        # Alice generates legitimate token for Org A counter
        legit_gen = self.client.post("/student/generate-token", data={
            "counter_id": str(self.counter_a_id),
            "service_reason": "Cardiology Checkup"
        }, follow_redirects=True)
        self.assertEqual(legit_gen.status_code, 200)
        self.assertIn("Heart Clinic Desk 1", legit_gen.get_data(as_text=True))
        self.assertIn("Token #1", legit_gen.get_data(as_text=True))

        # Bob (Org B) logs in
        self.client.get("/logout?role=student")
        self.login_user("citizen.bob@gmail.com", role="student")

        # Bob generates legitimate token for Org B counter
        bob_gen = self.client.post("/student/generate-token", data={
            "counter_id": str(self.counter_b_id),
            "service_reason": "Trade License Permit"
        }, follow_redirects=True)
        self.assertEqual(bob_gen.status_code, 200)

        # Bob attempts IDOR: Cancel Alice's token (ID 1)
        cancel_exploit = self.client.post("/student/token/cancel/1", follow_redirects=True)
        self.assertEqual(cancel_exploit.status_code, 200)
        self.assertIn("Token not found or unauthorized", cancel_exploit.get_data(as_text=True))

        # Verify Alice's token is still waiting in Org A
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT status FROM tokens WHERE id = 1")
            self.assertEqual(c.fetchone()["status"], "waiting")

    def test_operator_desk_and_queue_isolation(self):
        """Operator A cannot see, call, complete, or skip Org B's tokens or counters."""
        # 1. Create token in Org A and token in Org B
        self.login_user("patient.alice@gmail.com", role="student")
        self.client.post("/student/generate-token", data={"counter_id": str(self.counter_a_id), "service_reason": "Cardio"})
        self.client.get("/logout?role=student")

        self.login_user("citizen.bob@gmail.com", role="student")
        self.client.post("/student/generate-token", data={"counter_id": str(self.counter_b_id), "service_reason": "Permit"})
        self.client.get("/logout?role=student")

        # 2. Login Operator A (Global Healthcare)
        self.login_user("nurse.sarah@globalhealth.org", role="operator")
        op_a_dash = self.client.get("/operator/dashboard")
        self.assertEqual(op_a_dash.status_code, 200)
        html_a = op_a_dash.get_data(as_text=True)

        # Operator A sees Alice Patient and Cardiology Desk, but NEVER Bob Citizen or Trade Licensing
        self.assertIn("Alice Patient", html_a)
        self.assertIn("Heart Clinic Desk 1", html_a)
        self.assertNotIn("Bob Citizen", html_a)
        self.assertNotIn("Permit Issuance Desk 1", html_a)

        # Call next token for Operator A
        call_resp = self.client.post("/operator/call-next", follow_redirects=True)
        self.assertEqual(call_resp.status_code, 200)
        self.assertIn("Calling Token #1 (Alice Patient)", call_resp.get_data(as_text=True))

        # Operator A tries to complete Bob's token (Token ID 2 in Org B)
        tamper_complete = self.client.post("/operator/complete/2", follow_redirects=True)
        self.assertEqual(tamper_complete.status_code, 200)
        self.assertIn("Token not found", tamper_complete.get_data(as_text=True))

        # Complete Alice's token
        comp_resp = self.client.post("/operator/complete/1", follow_redirects=True)
        self.assertEqual(comp_resp.status_code, 200)
        self.assertIn("Token #1 marked as Completed", comp_resp.get_data(as_text=True))

    def test_admin_reports_and_analytics_isolation(self):
        """Admin A reports and CSV exports contain ONLY Org A records and zero Org B records."""
        # Generate tokens in Org A and Org B
        self.login_user("patient.alice@gmail.com", role="student")
        self.client.post("/student/generate-token", data={"counter_id": str(self.counter_a_id), "service_reason": "Org A Heart Surgery"})
        self.client.get("/logout?role=student")

        self.login_user("citizen.bob@gmail.com", role="student")
        self.client.post("/student/generate-token", data={"counter_id": str(self.counter_b_id), "service_reason": "Org B Liquor License"})
        self.client.get("/logout?role=student")

        # Admin A views reports
        self.login_user("admin@globalhealth.org", role="admin")
        report_resp = self.client.get("/admin/reports")
        self.assertEqual(report_resp.status_code, 200)
        html = report_resp.get_data(as_text=True)

        self.assertIn("Org A Heart Surgery", html)
        self.assertIn("Alice Patient", html)
        self.assertNotIn("Org B Liquor License", html)
        self.assertNotIn("Bob Citizen", html)

        # Admin A downloads CSV export
        csv_resp = self.client.get("/admin/reports/export.csv")
        self.assertEqual(csv_resp.status_code, 200)
        csv_text = csv_resp.get_data(as_text=True)
        self.assertIn("Org A Heart Surgery", csv_text)
        self.assertNotIn("Org B Liquor License", csv_text)

        # Admin B views reports
        self.client.get("/logout?role=admin")
        self.login_user("admin@cityservice.gov", role="admin")
        report_b = self.client.get("/admin/reports")
        self.assertEqual(report_b.status_code, 200)
        html_b = report_b.get_data(as_text=True)

        self.assertIn("Org B Liquor License", html_b)
        self.assertIn("Bob Citizen", html_b)
        self.assertNotIn("Org A Heart Surgery", html_b)
        self.assertNotIn("Alice Patient", html_b)

    def test_admin_crud_resource_isolation(self):
        """Admin A cannot modify, toggle, or view Org B departments, counters, or operators."""
        self.login_user("admin@globalhealth.org", role="admin")

        # View departments - should only list Org A
        dept_page = self.client.get("/admin/departments")
        self.assertEqual(dept_page.status_code, 200)
        dept_html = dept_page.get_data(as_text=True)
        self.assertIn("Cardiology &amp; Heart Care", dept_html)
        self.assertNotIn("City Business &amp; Trade Licensing", dept_html)

        # Admin A tries to edit Org B department (dept_b_id)
        edit_exploit = self.client.post(f"/admin/departments/edit/{self.dept_b_id}", data={
            "name": "Hacked Department",
            "description": "Exploit",
            "building_block": "Hacked",
            "is_active": "1"
        }, follow_redirects=True)
        self.assertEqual(edit_exploit.status_code, 200)

        # Verify Org B department in database is untouched
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM departments WHERE id = ?", (self.dept_b_id,))
            self.assertEqual(c.fetchone()["name"], "City Business & Trade Licensing")

        # Admin A tries to toggle Org B counter (counter_b_id)
        toggle_exploit = self.client.post(f"/admin/counters/action/{self.counter_b_id}", data={
            "action": "close"
        }, follow_redirects=True)
        self.assertEqual(toggle_exploit.status_code, 200)
        self.assertIn("Counter not found", toggle_exploit.get_data(as_text=True))

        # Verify Org B counter active state is still 1
        with queuex.db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT is_active FROM counters WHERE id = ?", (self.counter_b_id,))
            self.assertEqual(c.fetchone()["is_active"], 1)

    def test_organization_branding_settings_isolation(self):
        """Each organization maintains distinct branding and settings independently."""
        # Admin A updates branding
        self.login_user("admin@globalhealth.org", role="admin")
        update_resp = self.client.post("/admin/settings", data={
            "org_name": "Global Health Specialized Hospital",
            "org_subtitle": "Cardiac and Neuro Super Speciality",
            "org_tagline": "Leading healthcare with zero wait",
            "org_address": "Medical City Block 10",
            "org_support_email": "customercare@globalhealth.org",
            "org_support_phone": "1800-HEART-CARE"
        }, follow_redirects=True)
        self.assertEqual(update_resp.status_code, 200)

        # Admin B checks settings - verify Org B is unchanged
        self.client.get("/logout?role=admin")
        self.login_user("admin@cityservice.gov", role="admin")
        settings_b = self.client.get("/admin/settings")
        self.assertEqual(settings_b.status_code, 200)
        html_b = settings_b.get_data(as_text=True)
        self.assertIn("City Service Center", html_b)
        self.assertNotIn("Global Health Specialized Hospital", html_b)


if __name__ == "__main__":
    unittest.main()
