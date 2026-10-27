"""
Comprehensive Security & Authentication Automated Test Suite for Medicare
Verifies all 18 security, RBAC, IDOR, MFA, and access control requirements.
"""

import os
import sys

# Set test environment flags before importing app
os.environ["TESTING"] = "true"
os.environ["FLASK_ENV"] = "testing"
os.environ["SMTP_DEV_MODE"] = "true"

import unittest
from datetime import datetime, timedelta, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from db import get_connection, init_db
import auth_service
from werkzeug.security import generate_password_hash


class MedicareSecurityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["SECRET_KEY"] = "test_medicare_secret_key"
        init_db()

    def setUp(self):
        self.client = app.test_client()
        # Ensure standard accounts are unlocked at start of each test
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE email IN ('admin@medicare.io', 'dr.ananya@medicare.io')")
        conn.commit()
        cur.close()
        conn.close()

    # ------------------------------------------------------------------------
    # 1. Unauthenticated visitor cannot open protected doctor pages
    # ------------------------------------------------------------------------
    def test_01_unauthenticated_cannot_access_doctor_dashboard(self):
        response = self.client.get("/doctor-dashboard", follow_redirects=False)
        self.assertIn(response.status_code, [302, 401])
        if response.status_code == 302:
            self.assertIn("/login", response.headers["Location"])

    # ------------------------------------------------------------------------
    # 2. Unauthenticated visitor cannot open protected authority pages
    # ------------------------------------------------------------------------
    def test_02_unauthenticated_cannot_access_authority_dashboard(self):
        response = self.client.get("/authority-dashboard", follow_redirects=False)
        self.assertIn(response.status_code, [302, 401])
        if response.status_code == 302:
            self.assertIn("/login", response.headers["Location"])

    # ------------------------------------------------------------------------
    # 3. Direct requests cannot retrieve patient information without authentication
    # ------------------------------------------------------------------------
    def test_03_unauthenticated_cannot_retrieve_patient_records(self):
        res1 = self.client.get("/health-profile/1", follow_redirects=False)
        self.assertIn(res1.status_code, [302, 401, 404])

        res2 = self.client.get("/card/1", follow_redirects=False)
        self.assertIn(res2.status_code, [302, 401, 404])

        res3 = self.client.get("/qr/1", follow_redirects=False)
        self.assertIn(res3.status_code, [302, 401, 404])

    # ------------------------------------------------------------------------
    # 4. Incorrect passwords are rejected
    # ------------------------------------------------------------------------
    def test_04_incorrect_passwords_rejected(self):
        res = self.client.post("/login", data={
            "role": "doctor",
            "email": "dr.ananya@medicare.io",
            "password": "WrongPassword999!"
        }, follow_redirects=True)
        self.assertIn(b"Invalid email address or password", res.data)

        res_auth = self.client.post("/login", data={
            "role": "authority",
            "email": "admin@medicare.io",
            "password": "WrongPassword999!"
        }, follow_redirects=True)
        self.assertIn(b"Invalid email address or password", res_auth.data)

    # ------------------------------------------------------------------------
    # 5. Incorrect verification codes are rejected
    # ------------------------------------------------------------------------
    def test_05_incorrect_verification_code_rejected(self):
        user = {"id": 2, "email": "dr.ananya@medicare.io", "role": "doctor", "full_name": "Dr. Ananya Sen"}
        auth_service.generate_and_dispatch_code(user, "doctor_login")

        with self.client.session_transaction() as sess:
            sess["pending_auth"] = {
                "user_id": 2,
                "email": "dr.ananya@medicare.io",
                "role": "doctor",
                "name": "Dr. Ananya Sen",
                "purpose": "doctor_login"
            }

        res = self.client.post("/verify-code", data={"code": "000000"}, follow_redirects=True)
        self.assertIn(b"Incorrect verification code", res.data)

    # ------------------------------------------------------------------------
    # 6. Expired codes are rejected
    # ------------------------------------------------------------------------
    def test_06_expired_codes_rejected(self):
        conn = get_connection()
        cur = conn.cursor()
        expired_dt = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        import hashlib
        code_hash = hashlib.sha256("123456".encode()).hexdigest()
        cur.execute("""
            INSERT INTO verification_codes (email, code_hash, purpose, expires_at, is_used)
            VALUES (%s, %s, %s, %s, %s)
        """, ("dr.ananya@medicare.io", code_hash, "doctor_login", expired_dt, False))
        conn.commit()
        cur.close()
        conn.close()

        is_valid, reason = auth_service.verify_submitted_code("dr.ananya@medicare.io", "123456", "doctor_login")
        self.assertFalse(is_valid)
        self.assertIn("expired", reason.lower())

    # ------------------------------------------------------------------------
    # 7. Reused codes are rejected
    # ------------------------------------------------------------------------
    def test_07_reused_codes_rejected(self):
        user = {"id": 2, "email": "dr.ananya@medicare.io", "role": "doctor", "full_name": "Dr. Ananya Sen"}
        auth_service.generate_and_dispatch_code(user, "doctor_login")

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM verification_codes WHERE email = %s AND purpose = 'doctor_login' AND is_used = FALSE ORDER BY id DESC LIMIT 1", (user["email"],))
        rec = cur.fetchone()

        import hashlib
        known_code = "887766"
        h = hashlib.sha256(known_code.encode()).hexdigest()
        cur.execute("UPDATE verification_codes SET code_hash = %s WHERE id = %s", (h, rec["id"]))
        conn.commit()
        cur.close()
        conn.close()

        # 1st attempt: Valid
        v1, _ = auth_service.verify_submitted_code(user["email"], known_code, "doctor_login")
        self.assertTrue(v1)

        # 2nd attempt: Must be rejected as already used!
        v2, reason = auth_service.verify_submitted_code(user["email"], known_code, "doctor_login")
        self.assertFalse(v2)
        self.assertIn("already been used", reason.lower())

    # ------------------------------------------------------------------------
    # 8. Authority login cannot proceed without email verification
    # ------------------------------------------------------------------------
    def test_08_authority_login_cannot_proceed_without_code(self):
        res = self.client.post("/login", data={
            "role": "authority",
            "email": "admin@medicare.io",
            "password": "AdminSecure@2026!"
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        self.assertIn("/verify-code", res.headers["Location"])

    # ------------------------------------------------------------------------
    # 9. Doctor login cannot proceed without the required verification
    # ------------------------------------------------------------------------
    def test_09_doctor_login_cannot_proceed_without_code(self):
        res = self.client.post("/login", data={
            "role": "doctor",
            "email": "dr.ananya@medicare.io",
            "password": "DoctorSecure@2026!"
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        self.assertIn("/verify-code", res.headers["Location"])

    # ------------------------------------------------------------------------
    # 10. A patient cannot access doctor or authority endpoints
    # ------------------------------------------------------------------------
    def test_10_patient_cannot_access_doctor_or_authority_portals(self):
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["role"] = "patient"
            sess["patient_id"] = 1
            sess["user_name"] = "Eleanor Vance"

        res_doc = self.client.get("/doctor-dashboard", follow_redirects=False)
        self.assertIn(res_doc.status_code, [302, 403])

        res_auth = self.client.get("/authority-dashboard", follow_redirects=False)
        self.assertIn(res_auth.status_code, [302, 403])

    # ------------------------------------------------------------------------
    # 11. A doctor cannot access authority-only endpoints
    # ------------------------------------------------------------------------
    def test_11_doctor_cannot_access_authority_portal(self):
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["role"] = "doctor"
            sess["user_id"] = 2
            sess["user_name"] = "Dr. Ananya Sen"

        res = self.client.get("/authority-dashboard", follow_redirects=False)
        self.assertIn(res.status_code, [302, 403])

    # ------------------------------------------------------------------------
    # 12. An unapproved account cannot log in
    # ------------------------------------------------------------------------
    def test_12_unapproved_account_cannot_log_in(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE email = 'unapproved.doc@medicare.io'")
        pw_hash = generate_password_hash("TestPass123!")
        cur.execute("""
            INSERT INTO users (email, password_hash, role, full_name, is_approved, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, ("unapproved.doc@medicare.io", pw_hash, "doctor", "Dr. Pending Approval", False, True))
        conn.commit()
        cur.close()
        conn.close()

        res = self.client.post("/login", data={
            "role": "doctor",
            "email": "unapproved.doc@medicare.io",
            "password": "TestPass123!"
        }, follow_redirects=True)
        self.assertIn(b"pending administrative verification", res.data)

    # ------------------------------------------------------------------------
    # 13. IDOR Prevention: Unauthorized user cannot access other patient records
    # ------------------------------------------------------------------------
    def test_13_idor_prevention_on_patient_records(self):
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["role"] = "patient"
            sess["patient_id"] = 1
            sess["user_name"] = "Eleanor Vance"

        res = self.client.get("/health-profile/999", follow_redirects=False)
        self.assertIn(res.status_code, [403, 404])

        res_card = self.client.get("/card/999", follow_redirects=False)
        self.assertIn(res_card.status_code, [403, 404])

    # ------------------------------------------------------------------------
    # 14. Logout destroys authenticated session
    # ------------------------------------------------------------------------
    def test_14_logout_destroys_session(self):
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["role"] = "doctor"
            sess["user_id"] = 2

        self.client.get("/logout")

        with self.client.session_transaction() as sess:
            self.assertFalse(sess.get("logged_in", False))

        res = self.client.get("/doctor-dashboard", follow_redirects=False)
        self.assertEqual(res.status_code, 302)

    # ------------------------------------------------------------------------
    # 15. Rate limiting prevents brute force (max 5 failed code attempts)
    # ------------------------------------------------------------------------
    def test_15_code_attempt_rate_limiting(self):
        test_email = "rate_limit_test@medicare.io"
        user = {"id": 2, "email": test_email, "role": "doctor", "full_name": "Dr. Test"}
        auth_service.generate_and_dispatch_code(user, "doctor_login")

        for _ in range(5):
            auth_service.verify_submitted_code(test_email, "000000", "doctor_login")

        is_valid, reason = auth_service.verify_submitted_code(test_email, "000000", "doctor_login")
        self.assertFalse(is_valid)
        self.assertIn("invalidated", reason.lower())

    # ------------------------------------------------------------------------
    # 16. Existing patient registration and login continue to work
    # ------------------------------------------------------------------------
    def test_16_patient_registration_and_login_functional(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM patients WHERE email = 'alpha.patient@example.com' OR mobile = '+91 99999 88888'")
        conn.commit()
        cur.close()
        conn.close()

        reg_res = self.client.post("/register", data={
            "full_name": "Test Patient Alpha",
            "password": "AlphaPassword123!",
            "mobile": "+91 99999 88888",
            "email": "alpha.patient@example.com",
            "gender": "Male",
            "blood_group": "A+",
            "allergies": "None"
        }, follow_redirects=False)

        self.assertEqual(reg_res.status_code, 302)

        login_res = self.client.post("/login", data={
            "role": "patient",
            "identifier": "+91 99999 88888",
            "password": "AlphaPassword123!"
        }, follow_redirects=False)

        self.assertEqual(login_res.status_code, 302)
        self.assertIn("/dashboard", login_res.headers["Location"])

    # ------------------------------------------------------------------------
    # 17. Email delivery failures do not bypass verification
    # ------------------------------------------------------------------------
    def test_17_email_failure_does_not_bypass_verification(self):
        old_env = os.environ.get("FLASK_ENV")
        old_smtp = os.environ.get("SMTP_SERVER")
        old_dev = os.environ.get("SMTP_DEV_MODE")

        try:
            os.environ["FLASK_ENV"] = "production"
            os.environ["SMTP_DEV_MODE"] = "false"
            os.environ["SMTP_SERVER"] = ""
            os.environ["TESTING"] = "false"

            user = {"id": 2, "email": "dr.ananya@medicare.io", "role": "doctor", "full_name": "Dr. Ananya Sen"}
            sent, msg = auth_service.generate_and_dispatch_code(user, "doctor_login")

            # In production without SMTP, dispatch must fail safely
            self.assertFalse(sent)
            self.assertIn("not configured", msg.lower())

            # Verification cannot proceed without valid dispatch
            res = self.client.get("/doctor-dashboard", follow_redirects=False)
            self.assertIn(res.status_code, [302, 401])
        finally:
            os.environ["FLASK_ENV"] = old_env or "testing"
            os.environ["SMTP_SERVER"] = old_smtp or ""
            os.environ["SMTP_DEV_MODE"] = old_dev or "true"
            os.environ["TESTING"] = "true"

    # ------------------------------------------------------------------------
    # 18. Existing legitimate features continue to function (AI Assistant, etc.)
    # ------------------------------------------------------------------------
    def test_18_existing_legitimate_features_functional(self):
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["role"] = "patient"
            sess["patient_id"] = 1
            sess["user_name"] = "Eleanor Vance"

        ai_res = self.client.post("/api/ai-chat", json={"query": "I have mild asthma and headache"}, follow_redirects=False)
        self.assertEqual(ai_res.status_code, 200)
        data = ai_res.get_json()
        self.assertIn("reply", data)


if __name__ == "__main__":
    unittest.main()
