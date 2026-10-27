"""
Medicare Comprehensive Security & Authentication Test Suite
Tests all 59 scenarios from the security requirements.
"""
import os
import sys
import json

# Ensure project root is on path
project_dir = os.path.dirname(os.path.abspath(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

os.environ["FLASK_ENV"] = "development"

from app import app
from db import get_connection

passed = 0
failed = 0
results = []

def check(name, actual, expected, desc=""):
    global passed, failed
    ok = actual == expected if not isinstance(expected, (list, tuple)) else actual in expected
    tag = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    results.append((name, tag, desc))
    print("  %s: status=%s expect=%s %s  %s" % (name, actual, expected, tag, desc))


def run_all_tests():
    global passed, failed
    client = app.test_client()

    print("\n" + "="*70)
    print(" MEDICARE SECURITY TEST SUITE")
    print("="*70)

    # ====================================================================
    # SECTION 1: PUBLIC ROUTES (should return 200)
    # ====================================================================
    print("\n[1] PUBLIC ROUTES")
    check("T01", client.get("/").status_code, 200, "Home page public")
    check("T02", client.get("/login").status_code, 200, "Login page public")
    check("T03", client.get("/doctor/login").status_code, 200, "Doctor login page public")
    check("T04", client.get("/authority/login").status_code, 200, "Authority login page public")
    check("T05", client.get("/registration").status_code, 200, "Registration page public")
    check("T06", client.get("/test-db").status_code, 200, "DB health check public")

    # ====================================================================
    # SECTION 2: UNAUTHENTICATED ACCESS BLOCKED (should redirect 302)
    # ====================================================================
    print("\n[2] UNAUTHENTICATED ACCESS BLOCKED")
    protected = [
        ("/dashboard", "T07"),
        ("/health-profile/1", "T08"),
        ("/medical-records", "T09"),
        ("/family-history", "T10"),
        ("/genetic-history", "T11"),
        ("/ai-assistant", "T12"),
        ("/qr/1", "T13"),
        ("/card/1", "T14"),
        ("/settings", "T15"),
        ("/authority-dashboard", "T16"),
        ("/doctor/dashboard", "T17"),
        ("/authority/doctors", "T18"),
        ("/authority/audit-logs", "T19"),
    ]
    for path, tid in protected:
        r = client.get(path, follow_redirects=False)
        check(tid, r.status_code, 302, "Unauthenticated %s blocked" % path)

    # ====================================================================
    # SECTION 3: DECOMMISSIONED INSECURE ENDPOINTS
    # ====================================================================
    print("\n[3] DECOMMISSIONED ENDPOINTS")
    r = client.get("/api/lookup-password?query=8788625747")
    check("T20", r.status_code, 403, "Password lookup API permanently blocked")
    data = r.get_json()
    has_no_pw = "password" not in json.dumps(data).lower().replace("decommissioned", "")
    check("T21", has_no_pw, True, "No password data leaked in response")

    r = client.post("/api/ai-chat", json={"query": "test"})
    check("T22", r.status_code, 401, "AI chat API requires auth")

    # ====================================================================
    # SECTION 4: EMERGENCY VIEW (limited public triage)
    # ====================================================================
    print("\n[4] EMERGENCY PUBLIC TRIAGE VIEW")
    r = client.get("/emergency/1")
    check("T23", r.status_code, 200, "Emergency triage view loads")
    body = r.data.lower()
    check("T24", b"password" not in body, True, "No password in emergency view")
    # Verify emergency view contains only triage data (no full medical history, no addresses, no login forms)
    check("T25", b"address" not in body and b"occupation" not in body, True, "Limited scope data only (no private fields)")

    r = client.get("/emergency/99999")
    check("T26", r.status_code, 404, "Non-existent patient returns 404")

    # ====================================================================
    # SECTION 5: PATIENT LOGIN & AUTHORIZATION
    # ====================================================================
    print("\n[5] PATIENT LOGIN & AUTHORIZATION")
    # Wrong password
    r = client.post("/login", data={"role": "patient", "identifier": "8788625747", "password": "wrong"}, follow_redirects=True)
    check("T27", r.status_code, 200, "Wrong password rejected (form re-rendered)")
    check("T28", b"Incorrect password" in r.data or b"Invalid credentials" in r.data, True, "Error message shown")

    # Correct login
    r = client.post("/login", data={"role": "patient", "identifier": "8788625747", "password": "kumkum123"}, follow_redirects=False)
    check("T29", r.status_code, 302, "Patient login success redirects")

    # Dashboard accessible
    check("T30", client.get("/dashboard").status_code, 200, "Patient dashboard accessible")

    # Own profile accessible
    check("T31", client.get("/health-profile/4").status_code, 200, "Patient own profile (ID 4)")

    # IDOR: Other patient's profile blocked
    check("T32", client.get("/health-profile/1").status_code, 403, "IDOR: Patient 4 -> Patient 1 profile blocked")
    check("T33", client.get("/card/1").status_code, 403, "IDOR: Patient 4 -> Patient 1 card blocked")
    check("T34", client.get("/qr/1").status_code, 403, "IDOR: Patient 4 -> Patient 1 QR blocked")

    # POST IDOR: cannot update another patient
    r = client.post("/update-health-profile", data={"patient_id": "1", "full_name": "Hacked"}, follow_redirects=False)
    check("T35", r.status_code, 403, "IDOR: POST update other patient blocked")

    # Patient role boundary: cannot access doctor/authority dashboards
    check("T36", client.get("/doctor/dashboard", follow_redirects=False).status_code, 403, "Patient -> Doctor dashboard forbidden")
    check("T37", client.get("/authority-dashboard", follow_redirects=False).status_code, 403, "Patient -> Authority dashboard forbidden")
    check("T38", client.get("/authority/doctors", follow_redirects=False).status_code, 403, "Patient -> Authority doctors forbidden")
    check("T39", client.get("/authority/audit-logs", follow_redirects=False).status_code, 403, "Patient -> Audit logs forbidden")

    # Logout
    client.get("/logout")
    check("T40", client.get("/dashboard", follow_redirects=False).status_code, 302, "Logout invalidates session")

    # ====================================================================
    # SECTION 6: DOCTOR LOGIN WORKFLOW
    # ====================================================================
    print("\n[6] DOCTOR LOGIN WORKFLOW")

    # Code request with wrong password -> 401
    r = client.post("/doctor/request-code", json={"email": "dr.sharma@medicare.io", "password": "wrongpass"})
    check("T41", r.status_code, 401, "Doctor code request: wrong pw rejected")

    # Code request with correct password -> 200
    r = client.post("/doctor/request-code", json={"email": "dr.sharma@medicare.io", "password": "doctor123"})
    check("T42", r.status_code, 200, "Doctor code request: correct pw accepted")
    data = r.get_json()
    check("T43", data.get("success"), True, "Doctor code dispatch success=true")

    # Login without access code -> re-renders form (200)
    r = client.post("/doctor/login", data={"email": "dr.sharma@medicare.io", "password": "doctor123", "access_code": ""}, follow_redirects=False)
    check("T44", r.status_code, 200, "Doctor login: missing code rejected")

    # Login with wrong access code -> re-renders form (200)
    r = client.post("/doctor/login", data={"email": "dr.sharma@medicare.io", "password": "doctor123", "access_code": "999999"}, follow_redirects=False)
    check("T45", r.status_code, 200, "Doctor login: wrong code rejected")

    # Login with seed fallback code (DOC201) -> success
    # Must re-request code to reset code_used flag
    client.post("/doctor/request-code", json={"email": "dr.sharma@medicare.io", "password": "doctor123"})
    r = client.post("/doctor/login", data={"email": "dr.sharma@medicare.io", "password": "doctor123", "access_code": "DOC201"}, follow_redirects=False)
    check("T46", r.status_code, 302, "Doctor login: seed code accepted -> redirect")

    # Doctor dashboard accessible
    check("T47", client.get("/doctor/dashboard").status_code, 200, "Doctor dashboard accessible after login")

    # Doctor can view patient profile
    check("T48", client.get("/health-profile/1").status_code, 200, "Doctor can view patient profile")

    # Doctor CANNOT access authority pages
    check("T49", client.get("/authority-dashboard", follow_redirects=False).status_code, 403, "Doctor -> Authority dashboard forbidden")
    check("T50", client.get("/authority/doctors", follow_redirects=False).status_code, 403, "Doctor -> Authority doctors forbidden")

    # Doctor logout
    client.get("/logout")

    # Code reuse blocked (DOC201 now marked used)
    r = client.post("/doctor/login", data={"email": "dr.sharma@medicare.io", "password": "doctor123", "access_code": "DOC201"}, follow_redirects=False)
    check("T51", r.status_code, 200, "Doctor: code reuse rejected (form re-rendered)")

    # ====================================================================
    # SECTION 7: AUTHORITY LOGIN WORKFLOW
    # ====================================================================
    print("\n[7] AUTHORITY LOGIN WORKFLOW")

    # Code request with wrong password -> 401
    r = client.post("/authority/request-code", json={"email": "admin@medicare.io", "password": "wrongpass"})
    check("T52", r.status_code, 401, "Authority code request: wrong pw rejected")

    # Code request with correct password -> 200
    r = client.post("/authority/request-code", json={"email": "admin@medicare.io", "password": "admin123"})
    check("T53", r.status_code, 200, "Authority code request: correct pw accepted")
    data = r.get_json()
    check("T54", data.get("success"), True, "Authority code dispatch success=true")

    # Login without code -> reject
    r = client.post("/authority/login", data={"email": "admin@medicare.io", "password": "admin123", "access_code": ""}, follow_redirects=False)
    check("T55", r.status_code, 200, "Authority login: missing code rejected")

    # Login with wrong code -> reject
    r = client.post("/authority/login", data={"email": "admin@medicare.io", "password": "admin123", "access_code": "000000"}, follow_redirects=False)
    check("T56", r.status_code, 200, "Authority login: wrong code rejected")

    # Login with seed code (AUTH101 fallback)
    client.post("/authority/request-code", json={"email": "admin@medicare.io", "password": "admin123"})
    r = client.post("/authority/login", data={"email": "admin@medicare.io", "password": "admin123", "access_code": "AUTH101"}, follow_redirects=False)
    check("T57", r.status_code, 302, "Authority login: seed code accepted -> redirect")

    # Authority dashboard accessible
    check("T58", client.get("/authority-dashboard").status_code, 200, "Authority dashboard accessible")

    # Authority can view patient profiles
    check("T59", client.get("/health-profile/1").status_code, 200, "Authority can view patient profile")

    # Authority can manage doctors
    check("T60", client.get("/authority/doctors").status_code, 200, "Authority doctors page accessible")

    # Authority audit logs
    check("T61", client.get("/authority/audit-logs").status_code, 200, "Authority audit logs accessible")

    # Authority logout
    client.get("/logout")

    # Code reuse blocked
    r = client.post("/authority/login", data={"email": "admin@medicare.io", "password": "admin123", "access_code": "AUTH101"}, follow_redirects=False)
    check("T62", r.status_code, 200, "Authority: code reuse rejected")

    # ====================================================================
    # SECTION 8: PATIENT REGISTRATION STILL WORKS
    # ====================================================================
    print("\n[8] PATIENT REGISTRATION PRESERVED")
    r = client.post("/register", data={
        "full_name": "Test NewPatient",
        "password": "securePass789",
        "dob": "2000-01-15",
        "age": "26",
        "gender": "Male",
        "blood_group": "A+",
        "marital_status": "Single",
        "occupation": "Engineer",
        "mobile": "7777777777",
        "email": "testpatient@test.io",
        "address": "123 Test St",
        "city": "TestCity",
        "state": "TestState",
        "pin_code": "123456",
        "emergency_name": "Emergency Friend",
        "emergency_relationship": "Friend",
        "emergency_number": "6666666666",
        "allergies": "None",
        "existing_conditions": "None",
        "current_medications": "None",
    })
    check("T63", r.status_code, 200, "Patient registration returns success page")
    check("T64", b"Registered Successfully" in r.data, True, "Registration success message present")

    # New patient can login
    client.get("/logout")
    r = client.post("/login", data={"role": "patient", "identifier": "7777777777", "password": "securePass789"}, follow_redirects=False)
    check("T65", r.status_code, 302, "New patient can login")
    check("T66", client.get("/dashboard").status_code, 200, "New patient dashboard accessible")
    client.get("/logout")

    # ====================================================================
    # SUMMARY
    # ====================================================================
    print("\n" + "="*70)
    print(" MEDICARE SECURITY TEST RESULTS")
    print("="*70)
    total = passed + failed
    print("  Total:  %d" % total)
    print("  Passed: %d" % passed)
    print("  Failed: %d" % failed)

    if failed > 0:
        print("\n  FAILED TESTS:")
        for name, tag, desc in results:
            if tag == "FAIL":
                print("    %s: %s" % (name, desc))

    print("="*70)
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
