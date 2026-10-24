import os
import tempfile
import unittest

import app as queuex


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
        self.assertIn("burgerBtn", js)
        self.assertIn("toggleMenu", js)


if __name__ == "__main__":
    unittest.main()
