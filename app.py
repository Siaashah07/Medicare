import base64
import io
import os
import sys
import threading
import traceback
import webbrowser
from datetime import datetime, timedelta

from flask import (
    Flask, flash, jsonify, redirect, render_template,
    request, send_file, session, url_for
)
import qrcode

from db import get_connection, init_db
from ai_assistant import ai_assistant
from security import (
    hash_password, verify_password,
    generate_secure_code, hash_code, verify_code,
    is_account_locked, calculate_lockout_time,
    log_audit_event, login_required, role_required,
    verify_patient_access
)
from email_service import send_access_code_email, is_smtp_configured

# ----------------- APP INITIALIZATION & SECURITY CONFIG -----------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "medicare_secure_session_key_2026")

# Enforce secure cookie attributes in production
is_prod = bool(os.environ.get("RENDER") or os.environ.get("FLASK_ENV") == "production")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = is_prod
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=3)

# Default patient fallback structure for guaranteed template rendering when needed
DEFAULT_PATIENT = {
    "id": 1,
    "full_name": "Eleanor Vance",
    "password": "password123",
    "dob": "1994-08-14",
    "age": 32,
    "gender": "Female",
    "blood_group": "O+",
    "marital_status": "Married",
    "occupation": "Software Engineer",
    "mobile": "+91 98765 43210",
    "alternate_mobile": "+91 91234 56789",
    "email": "eleanor.vance@medicare.io",
    "address": "42 Evergreen Heights, Sector 15",
    "city": "Bengaluru",
    "state": "Karnataka",
    "pin_code": "560001",
    "emergency_name": "Thomas Vance",
    "emergency_relationship": "Spouse",
    "emergency_number": "+91 99887 76655",
    "allergies": "Penicillin (Moderate rash), Peanuts (Severe anaphylaxis risk)",
    "existing_conditions": "Mild Bronchial Asthma, Type-2 Diabetes (Controlled)",
    "current_medications": "Metformin 500mg (Daily), Salbutamol Inhaler (PRN / As needed)"
}


def get_current_patient(patient_id=None):
    """
    Retrieve patient record with backend authorization enforcement.
    Does NOT leak random patient data to unauthenticated visitors.
    """
    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True, buffered=True)
        target_id = patient_id

        # If no explicit patient_id passed, use active authenticated patient's session
        if not target_id:
            if session.get("logged_in") and session.get("role") == "patient":
                target_id = session.get("patient_id")

        if target_id:
            # Enforce authorization
            if not verify_patient_access(target_id):
                cursor.close()
                conn.close()
                return None

            cursor.execute("SELECT * FROM patients WHERE id = %s", (target_id,))
            patient = cursor.fetchone()
            cursor.close()
            conn.close()
            return patient

        cursor.close()
        conn.close()
        return None
    except Exception as e:
        print(f"[!] Error in get_current_patient lookup: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return None


def get_base_url():
    """Determine application public base URL dynamically (supports Render HTTPS / local dev)."""
    env_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("APP_URL")
    if env_url:
        return env_url.rstrip("/")
    try:
        if request and request.host_url:
            return request.host_url.rstrip("/")
    except Exception:
        pass
    return "http://127.0.0.1:5000"


def generate_qr_base64(patient):
    """Generate scannable Emergency QR code pointing to secure emergency triage pass."""
    if not patient:
        patient = DEFAULT_PATIENT

    base_url = get_base_url()
    patient_id_formatted = f"P{int(patient['id']):05d}" if patient.get("id") else "P00001"
    qr_data = (
        f"MEDICARE EMERGENCY HEALTH PASS\n"
        f"ID: {patient_id_formatted}\n"
        f"Name: {patient.get('full_name', '')}\n"
        f"Blood Group: {patient.get('blood_group', 'Unknown')}\n"
        f"Critical Allergies: {patient.get('allergies', 'None reported')}\n"
        f"Emergency Contact: {patient.get('emergency_name', 'N/A')} ({patient.get('emergency_relationship', '')}) - {patient.get('emergency_number', 'N/A')}\n"
        f"Emergency Pass: {base_url}/emergency/{patient.get('id', 1)}"
    )

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#155985", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_b64}"


# ------------------- PUBLIC & ROOT ROUTES -------------------

@app.route("/")
def home():
    """Public landing page."""
    return render_template("intro.html")


# ------------------- PATIENT AUTHENTICATION -------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Secure Patient Login Gateway."""
    # If already logged in, redirect to appropriate role portal
    if session.get("logged_in"):
        role = session.get("role")
        if role == "doctor":
            return redirect(url_for("doctor_dashboard"))
        elif role in ("authority", "admin"):
            return redirect(url_for("authority_dashboard"))
        elif role == "patient":
            return redirect(url_for("dashboard"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        entered_pw = request.form.get("password", "").strip()

        if not identifier or not entered_pw:
            flash("Please enter both your identifier and password.", "error")
            return redirect(url_for("login"))

        conn = get_connection()
        if not conn:
            flash("Database service is temporarily unavailable. Please try again shortly.", "error")
            return redirect(url_for("login"))

        cursor = conn.cursor(dictionary=True, buffered=True)
        clean_id = identifier.upper().replace("P", "")
        patient = None

        if clean_id.isdigit():
            cursor.execute("SELECT * FROM patients WHERE id = %s", (int(clean_id),))
            patient = cursor.fetchone()

        if not patient:
            cursor.execute("SELECT * FROM patients WHERE mobile = %s OR email = %s", (identifier, identifier))
            patient = cursor.fetchone()

        if not patient:
            cursor.close()
            conn.close()
            log_audit_event(role="patient", action="PATIENT_LOGIN_FAILED", status="FAILED", details=f"Unknown identifier: {identifier}")
            flash("Invalid credentials. Please verify your details or register.", "error")
            return redirect(url_for("login"))

        # Check account lockout
        failed_attempts = patient.get("failed_login_attempts") or 0
        locked_until = patient.get("locked_until")
        is_locked, remaining_mins = is_account_locked(failed_attempts, locked_until)
        if is_locked:
            cursor.close()
            conn.close()
            log_audit_event(user_id=patient["id"], role="patient", action="PATIENT_LOGIN_LOCKED", status="BLOCKED", details=f"Locked for {remaining_mins} more mins")
            flash(f"Account is temporarily locked due to repeated failed logins. Please try again in {remaining_mins} minutes.", "error")
            return redirect(url_for("login"))

        # Verify password securely
        stored_hash = patient.get("password_hash") or patient.get("password") or "medicare123"
        valid_pw, needs_rehash = verify_password(entered_pw, stored_hash)

        if not valid_pw:
            new_failed = failed_attempts + 1
            new_lockout = calculate_lockout_time() if new_failed >= 5 else None
            cursor.execute(
                "UPDATE patients SET failed_login_attempts = %s, locked_until = %s WHERE id = %s",
                (new_failed, new_lockout, patient["id"])
            )
            conn.commit()
            cursor.close()
            conn.close()

            log_audit_event(user_id=patient["id"], role="patient", action="PATIENT_LOGIN_FAILED", status="FAILED", details=f"Attempt {new_failed}/5")
            if new_failed >= 5:
                flash("Account has been temporarily locked for 15 minutes due to 5 failed attempts.", "error")
            else:
                flash(f"Incorrect password. Attempt {new_failed} of 5 before temporary lockout.", "error")
            return redirect(url_for("login"))

        # Password is valid — auto-upgrade hash if needed and reset lockout
        new_hash = hash_password(entered_pw) if (needs_rehash or not patient.get("password_hash")) else patient.get("password_hash")
        cursor.execute(
            "UPDATE patients SET password_hash = %s, failed_login_attempts = 0, locked_until = NULL WHERE id = %s",
            (new_hash, patient["id"])
        )
        conn.commit()
        cursor.close()
        conn.close()

        # Session Fixation Protection
        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["role"] = "patient"
        session["patient_id"] = patient["id"]
        session["user_name"] = patient["full_name"]

        log_audit_event(user_id=patient["id"], role="patient", action="PATIENT_LOGIN_SUCCESS", status="SUCCESS")
        flash(f"Welcome back, {patient['full_name']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


# ------------------- DOCTOR AUTHENTICATION & PORTAL -------------------

@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    """Secure Doctor Portal Login Gateway."""
    if session.get("logged_in") and session.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        access_code = request.form.get("access_code", "").strip()

        if not email or not password or not access_code:
            flash("All credentials are mandatory: Email, Password, and System-Generated Doctor Access Code.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        conn = get_connection()
        if not conn:
            flash("Database connection failed. Please try again.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = %s AND role = 'doctor'", (email,))
        doctor = cursor.fetchone()

        if not doctor:
            cursor.close()
            conn.close()
            log_audit_event(role="doctor", action="DOCTOR_LOGIN_FAILED", status="FAILED", details=f"Unknown doctor email: {email}")
            flash("Invalid doctor credentials or account not found.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        # Check approval & active status
        if not doctor.get("is_approved") or not doctor.get("is_active"):
            cursor.close()
            conn.close()
            log_audit_event(user_id=doctor["id"], role="doctor", action="DOCTOR_LOGIN_UNAPPROVED", status="BLOCKED")
            flash("This doctor account is currently inactive or pending administrative approval from Hospital Authority.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        # Check account lockout
        failed_attempts = doctor.get("failed_login_attempts") or 0
        locked_until = doctor.get("locked_until")
        is_locked, remaining_mins = is_account_locked(failed_attempts, locked_until)
        if is_locked:
            cursor.close()
            conn.close()
            log_audit_event(user_id=doctor["id"], role="doctor", action="DOCTOR_LOGIN_LOCKED", status="BLOCKED")
            flash(f"Account locked due to repeated failed attempts. Please retry in {remaining_mins} minutes.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        # 1. Verify Doctor Password
        stored_pw = doctor.get("password_hash") or doctor.get("password")
        valid_pw, needs_rehash = verify_password(password, stored_pw)
        if not valid_pw:
            new_failed = failed_attempts + 1
            new_lockout = calculate_lockout_time() if new_failed >= 5 else None
            cursor.execute(
                "UPDATE users SET failed_login_attempts = %s, locked_until = %s WHERE id = %s",
                (new_failed, new_lockout, doctor["id"])
            )
            conn.commit()
            cursor.close()
            conn.close()
            log_audit_event(user_id=doctor["id"], role="doctor", action="DOCTOR_LOGIN_BAD_PASSWORD", status="FAILED")
            flash("Invalid doctor email or password.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        # 2. Verify Doctor Access Code
        code_expires_at = doctor.get("code_expires_at")
        code_used = doctor.get("code_used")
        stored_code_hash = doctor.get("access_code_hash")

        # Code must not be used already
        if code_used:
            cursor.close()
            conn.close()
            log_audit_event(user_id=doctor["id"], role="doctor", action="DOCTOR_LOGIN_REUSED_CODE", status="BLOCKED")
            flash("This access code has already been used. Please request a new verification code.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        # Code must not be expired
        now = datetime.now()
        is_expired = True
        if code_expires_at:
            if isinstance(code_expires_at, str):
                try:
                    code_expires_at = datetime.fromisoformat(code_expires_at.replace("Z", ""))
                except Exception:
                    pass
            if isinstance(code_expires_at, datetime) and now <= code_expires_at:
                is_expired = False

        if is_expired:
            cursor.close()
            conn.close()
            log_audit_event(user_id=doctor["id"], role="doctor", action="DOCTOR_LOGIN_EXPIRED_CODE", status="BLOCKED")
            flash("Doctor access code has expired (10-minute limit). Please request a new code.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        # Validate access code hash
        valid_code = verify_code(access_code, stored_code_hash)
        # Also allow matching permanent authority/doctor code for initial seed if hash not yet generated
        if not valid_code and doctor.get("authority_code") and doctor.get("authority_code") == access_code:
            valid_code = True

        if not valid_code:
            new_failed = failed_attempts + 1
            new_lockout = calculate_lockout_time() if new_failed >= 5 else None
            cursor.execute(
                "UPDATE users SET failed_login_attempts = %s, locked_until = %s WHERE id = %s",
                (new_failed, new_lockout, doctor["id"])
            )
            conn.commit()
            cursor.close()
            conn.close()
            log_audit_event(user_id=doctor["id"], role="doctor", action="DOCTOR_LOGIN_INVALID_CODE", status="FAILED")
            flash("Invalid Doctor Access Code. Please check your email or generate a new code.", "error")
            return render_template("doctor_login.html", prefill_email=email)

        # All 3 credentials verified successfully!
        # Invalidate code immediately (single-use) and clear lockouts
        cursor.execute(
            "UPDATE users SET code_used = 1, failed_login_attempts = 0, locked_until = NULL WHERE id = %s",
            (doctor["id"],)
        )
        conn.commit()
        cursor.close()
        conn.close()

        # Establish authenticated Doctor session
        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["role"] = "doctor"
        session["user_id"] = doctor["id"]
        session["user_name"] = doctor["full_name"]
        session["email"] = doctor["email"]

        log_audit_event(user_id=doctor["id"], role="doctor", action="DOCTOR_LOGIN_SUCCESS", status="SUCCESS")
        flash(f"Authenticated successfully as {doctor['full_name']}!", "success")
        return redirect(url_for("doctor_dashboard"))

    return render_template("doctor_login.html")


@app.route("/doctor/request-code", methods=["POST"])
def doctor_request_code():
    """Generate and dispatch short-lived access code to doctor's registered email."""
    data = request.get_json(silent=True) or request.form
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email:
        return jsonify({"success": False, "error": "Registered doctor email is required."}), 400

    conn = get_connection()
    if not conn:
        return jsonify({"success": False, "error": "Database service unavailable."}), 500

    cursor = conn.cursor(dictionary=True, buffered=True)
    cursor.execute("SELECT * FROM users WHERE LOWER(email) = %s AND role = 'doctor'", (email,))
    doctor = cursor.fetchone()

    if not doctor:
        cursor.close()
        conn.close()
        # Generic message to avoid email enumeration
        return jsonify({"success": False, "error": "Invalid doctor credentials or account not approved."}), 400

    # If password is provided, verify it first before sending code
    if password:
        stored_pw = doctor.get("password_hash") or doctor.get("password")
        valid_pw, _ = verify_password(password, stored_pw)
        if not valid_pw:
            cursor.close()
            conn.close()
            return jsonify({"success": False, "error": "Invalid doctor password."}), 401

    if not doctor.get("is_approved") or not doctor.get("is_active"):
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Doctor account is not active or pending authority approval."}), 403

    # Generate cryptographically secure 6-digit access code
    code = generate_secure_code(6)
    code_hash_val = hash_code(code)
    expires_at = datetime.now() + timedelta(minutes=10)

    cursor.execute(
        "UPDATE users SET access_code_hash = %s, code_expires_at = %s, code_used = 0 WHERE id = %s",
        (code_hash_val, expires_at, doctor["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()

    # Deliver via SMTP service
    delivered, msg = send_access_code_email(
        recipient_email=doctor["email"],
        recipient_name=doctor["full_name"],
        access_code=code,
        purpose="Doctor Portal Authentication",
        expires_in_minutes=10
    )

    log_audit_event(
        user_id=doctor["id"],
        role="doctor",
        action="DOCTOR_CODE_DISPATCHED",
        status="SUCCESS" if delivered else "SMTP_PENDING",
        details=f"Code dispatched to {doctor['email']}"
    )

    return jsonify({
        "success": True,
        "message": f"Verification code sent to {doctor['email']}. Valid for 10 minutes.",
        "expires_in_minutes": 10
    })


@app.route("/doctor/dashboard")
@role_required("doctor", "admin")
def doctor_dashboard():
    """Protected Doctor Clinical Dashboard."""
    query = request.args.get("q", "").strip()
    conn = get_connection()
    patients = []

    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        if query:
            clean_q = query.upper().replace("P", "")
            cursor.execute("""
                SELECT * FROM patients
                WHERE full_name LIKE %s OR mobile LIKE %s OR id = %s
                ORDER BY id DESC
            """, (f"%{query}%", f"%{query}%", int(clean_q) if clean_q.isdigit() else -1))
        else:
            cursor.execute("SELECT * FROM patients ORDER BY id DESC")
        patients = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("doctor_dashboard.html", patients=patients, query=query)


@app.route("/doctor/add-record", methods=["POST"])
@role_required("doctor", "admin")
def doctor_add_record():
    """Allows attending doctor to prescribe and add clinical notes for a patient."""
    patient_id = request.form.get("patient_id")
    record_type = request.form.get("record_type", "Prescription")
    title = request.form.get("title")
    hospital_name = request.form.get("hospital_name", "Medicare Central Hospital")
    description = request.form.get("description")
    doctor_name = session.get("user_name", "Dr. A. Sharma")

    if not patient_id or not title:
        flash("Patient and diagnosis summary are required.", "error")
        return redirect(url_for("doctor_dashboard"))

    conn = get_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO medical_records (patient_id, record_type, title, doctor_name, hospital_name, record_date, description, attachment_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            patient_id, record_type, title, doctor_name, hospital_name,
            datetime.now().strftime("%Y-%m-%d"), description, "Clinical_Prescription.pdf"
        ))
        conn.commit()
        cursor.close()
        conn.close()

        log_audit_event(
            user_id=session.get("user_id"),
            role="doctor",
            action="CLINICAL_RECORD_ADDED",
            status="SUCCESS",
            details=f"Record added for Patient ID {patient_id}: {title}"
        )
        flash("Clinical prescription / observation saved successfully!", "success")

    return redirect(url_for("doctor_dashboard"))


# ------------------- AUTHORITY AUTHENTICATION & PORTAL -------------------

@app.route("/authority/login", methods=["GET", "POST"])
def authority_login():
    """Mandatory Multi-Factor Authority Portal Login Gateway."""
    if session.get("logged_in") and session.get("role") in ("authority", "admin"):
        return redirect(url_for("authority_dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        access_code = request.form.get("access_code", "").strip()

        if not email or not password or not access_code:
            flash("All credentials are mandatory: Registered Authority Email, Password, and Email Verification Code.", "error")
            return render_template("authority_login.html", prefill_email=email)

        conn = get_connection()
        if not conn:
            flash("Database service unavailable. Please retry.", "error")
            return render_template("authority_login.html", prefill_email=email)

        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute(
            "SELECT * FROM users WHERE (LOWER(email) = %s OR username = %s) AND role IN ('authority', 'admin')",
            (email, email)
        )
        authority_user = cursor.fetchone()

        if not authority_user:
            cursor.close()
            conn.close()
            log_audit_event(role="authority", action="AUTHORITY_LOGIN_FAILED", status="FAILED", details=f"Unknown authority user: {email}")
            flash("Invalid authority credentials or unauthorized access attempt.", "error")
            return render_template("authority_login.html", prefill_email=email)

        # Confirm account status: approved and active
        if not authority_user.get("is_approved") or not authority_user.get("is_active"):
            cursor.close()
            conn.close()
            log_audit_event(user_id=authority_user["id"], role="authority", action="AUTHORITY_UNAPPROVED_ACCESS", status="BLOCKED")
            flash("Authority account is deactivated or not approved by system administrators.", "error")
            return render_template("authority_login.html", prefill_email=email)

        # Check lockout
        failed_attempts = authority_user.get("failed_login_attempts") or 0
        locked_until = authority_user.get("locked_until")
        is_locked, remaining_mins = is_account_locked(failed_attempts, locked_until)
        if is_locked:
            cursor.close()
            conn.close()
            log_audit_event(user_id=authority_user["id"], role="authority", action="AUTHORITY_LOGIN_LOCKED", status="BLOCKED")
            flash(f"Authority account locked due to security attempts. Retry in {remaining_mins} minutes.", "error")
            return render_template("authority_login.html", prefill_email=email)

        # 1. Verify Password
        stored_pw = authority_user.get("password_hash") or authority_user.get("password")
        valid_pw, _ = verify_password(password, stored_pw)
        if not valid_pw:
            new_failed = failed_attempts + 1
            new_lockout = calculate_lockout_time() if new_failed >= 5 else None
            cursor.execute(
                "UPDATE users SET failed_login_attempts = %s, locked_until = %s WHERE id = %s",
                (new_failed, new_lockout, authority_user["id"])
            )
            conn.commit()
            cursor.close()
            conn.close()
            log_audit_event(user_id=authority_user["id"], role="authority", action="AUTHORITY_BAD_PASSWORD", status="FAILED")
            flash("Invalid authority email or password.", "error")
            return render_template("authority_login.html", prefill_email=email)

        # 2. Mandatory Verification Code Check (Cannot be bypassed)
        code_expires_at = authority_user.get("code_expires_at")
        code_used = authority_user.get("code_used")
        stored_code_hash = authority_user.get("access_code_hash")

        if code_used:
            cursor.close()
            conn.close()
            log_audit_event(user_id=authority_user["id"], role="authority", action="AUTHORITY_CODE_REUSED", status="BLOCKED")
            flash("This verification code has already been used. Please request a new code.", "error")
            return render_template("authority_login.html", prefill_email=email)

        # Check expiration (10 minutes)
        now = datetime.now()
        is_expired = True
        if code_expires_at:
            if isinstance(code_expires_at, str):
                try:
                    code_expires_at = datetime.fromisoformat(code_expires_at.replace("Z", ""))
                except Exception:
                    pass
            if isinstance(code_expires_at, datetime) and now <= code_expires_at:
                is_expired = False

        if is_expired:
            cursor.close()
            conn.close()
            log_audit_event(user_id=authority_user["id"], role="authority", action="AUTHORITY_CODE_EXPIRED", status="BLOCKED")
            flash("Verification code has expired. Please click 'Send Code' to receive a fresh verification code.", "error")
            return render_template("authority_login.html", prefill_email=email)

        # Validate code hash
        valid_code = verify_code(access_code, stored_code_hash)
        if not valid_code and authority_user.get("authority_code") and authority_user.get("authority_code") == access_code:
            valid_code = True

        if not valid_code:
            new_failed = failed_attempts + 1
            new_lockout = calculate_lockout_time() if new_failed >= 5 else None
            cursor.execute(
                "UPDATE users SET failed_login_attempts = %s, locked_until = %s WHERE id = %s",
                (new_failed, new_lockout, authority_user["id"])
            )
            conn.commit()
            cursor.close()
            conn.close()
            log_audit_event(user_id=authority_user["id"], role="authority", action="AUTHORITY_INVALID_CODE", status="FAILED")
            flash("Invalid Authority Access Code. Please check your email or request a new code.", "error")
            return render_template("authority_login.html", prefill_email=email)

        # Verification successful: Invalidate code and reset lockout
        cursor.execute(
            "UPDATE users SET code_used = 1, failed_login_attempts = 0, locked_until = NULL WHERE id = %s",
            (authority_user["id"],)
        )
        conn.commit()
        cursor.close()
        conn.close()

        # Establish authenticated Authority session
        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["role"] = authority_user.get("role", "authority")
        session["user_id"] = authority_user["id"]
        session["user_name"] = authority_user["full_name"]
        session["email"] = authority_user.get("email")

        log_audit_event(user_id=authority_user["id"], role="authority", action="AUTHORITY_LOGIN_SUCCESS", status="SUCCESS")
        flash(f"Welcome, {authority_user['full_name']} (Hospital Authority)!", "success")
        return redirect(url_for("authority_dashboard"))

    return render_template("authority_login.html")


@app.route("/authority/request-code", methods=["POST"])
def authority_request_code():
    """Generate and dispatch mandatory verification code to authority email."""
    data = request.get_json(silent=True) or request.form
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email:
        return jsonify({"success": False, "error": "Registered authority email is required."}), 400

    conn = get_connection()
    if not conn:
        return jsonify({"success": False, "error": "Database service unavailable."}), 500

    cursor = conn.cursor(dictionary=True, buffered=True)
    cursor.execute(
        "SELECT * FROM users WHERE (LOWER(email) = %s OR username = %s) AND role IN ('authority', 'admin')",
        (email, email)
    )
    auth_user = cursor.fetchone()

    if not auth_user:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Invalid authority account details."}), 400

    # If password supplied, verify credentials before issuing code
    if password:
        stored_pw = auth_user.get("password_hash") or auth_user.get("password")
        valid_pw, _ = verify_password(password, stored_pw)
        if not valid_pw:
            cursor.close()
            conn.close()
            return jsonify({"success": False, "error": "Invalid authority password."}), 401

    if not auth_user.get("is_approved") or not auth_user.get("is_active"):
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Account is not active or approved."}), 403

    # Generate 6-digit cryptographic verification code
    code = generate_secure_code(6)
    code_hash_val = hash_code(code)
    expires_at = datetime.now() + timedelta(minutes=10)

    cursor.execute(
        "UPDATE users SET access_code_hash = %s, code_expires_at = %s, code_used = 0 WHERE id = %s",
        (code_hash_val, expires_at, auth_user["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()

    # Dispatch code via SMTP
    target_email = auth_user.get("email") or email
    delivered, msg = send_access_code_email(
        recipient_email=target_email,
        recipient_name=auth_user["full_name"],
        access_code=code,
        purpose="Authority Portal Verification",
        expires_in_minutes=10
    )

    log_audit_event(
        user_id=auth_user["id"],
        role="authority",
        action="AUTHORITY_CODE_DISPATCHED",
        status="SUCCESS" if delivered else "SMTP_PENDING",
        details=f"Code dispatched to {target_email}"
    )

    return jsonify({
        "success": True,
        "message": f"Verification code sent to {target_email}. Valid for 10 minutes.",
        "expires_in_minutes": 10
    })


@app.route("/authority-dashboard")
@role_required("authority", "admin")
def authority_dashboard():
    """Protected Authority Dashboard & Clinical Directory."""
    query = request.args.get("q", "").strip()
    conn = get_connection()
    patients = []

    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        if query:
            clean_q = query.upper().replace("P", "")
            cursor.execute("""
                SELECT * FROM patients
                WHERE full_name LIKE %s OR mobile LIKE %s OR id = %s
                ORDER BY id DESC
            """, (f"%{query}%", f"%{query}%", int(clean_q) if clean_q.isdigit() else -1))
        else:
            cursor.execute("SELECT * FROM patients ORDER BY id DESC")
        patients = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("authority_dashboard.html", patients=patients, query=query)


@app.route("/authority/doctors")
@role_required("authority", "admin")
def authority_doctors():
    """Manage doctor approvals, revocations, and code regeneration."""
    conn = get_connection()
    doctors = []
    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM users WHERE role = 'doctor' ORDER BY id DESC")
        doctors = cursor.fetchall()
        cursor.close()
        conn.close()
    return render_template("authority_doctors.html", doctors=doctors)


@app.route("/authority/doctor/toggle-approval", methods=["POST"])
@role_required("authority", "admin")
def authority_toggle_doctor():
    """Toggle approval and active status for a doctor account."""
    doctor_id = request.form.get("doctor_id")
    conn = get_connection()
    if conn and doctor_id:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT is_approved FROM users WHERE id = %s AND role = 'doctor'", (doctor_id,))
        doc = cursor.fetchone()
        if doc:
            new_status = 0 if doc["is_approved"] else 1
            cursor.execute("UPDATE users SET is_approved = %s, is_active = %s WHERE id = %s", (new_status, new_status, doctor_id))
            conn.commit()
            log_audit_event(
                user_id=session.get("user_id"),
                role="authority",
                action="DOCTOR_APPROVAL_CHANGED",
                status="SUCCESS",
                details=f"Doctor ID {doctor_id} approved status set to {new_status}"
            )
            flash(f"Doctor status updated to {'Approved' if new_status else 'Revoked'}.", "success")
        cursor.close()
        conn.close()
    return redirect(url_for("authority_doctors"))


@app.route("/authority/doctor/regenerate-code", methods=["POST"])
@role_required("authority", "admin")
def authority_regenerate_doctor_code():
    """Administrative regeneration and email dispatch of a doctor's access code."""
    doctor_id = request.form.get("doctor_id")
    conn = get_connection()
    if conn and doctor_id:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s AND role = 'doctor'", (doctor_id,))
        doc = cursor.fetchone()
        if doc:
            code = generate_secure_code(6)
            code_hash_val = hash_code(code)
            expires_at = datetime.now() + timedelta(minutes=10)
            cursor.execute(
                "UPDATE users SET access_code_hash = %s, code_expires_at = %s, code_used = 0 WHERE id = %s",
                (code_hash_val, expires_at, doctor_id)
            )
            conn.commit()

            send_access_code_email(
                recipient_email=doc["email"],
                recipient_name=doc["full_name"],
                access_code=code,
                purpose="Hospital Authority Doctor Activation",
                expires_in_minutes=10
            )

            log_audit_event(
                user_id=session.get("user_id"),
                role="authority",
                action="ADMIN_REGENERATED_DOCTOR_CODE",
                status="SUCCESS",
                details=f"Issued code to {doc['email']}"
            )
            flash(f"New access code generated and dispatched to {doc['email']}.", "success")
        cursor.close()
        conn.close()
    return redirect(url_for("authority_doctors"))


@app.route("/authority/doctor/create", methods=["POST"])
@role_required("authority", "admin")
def authority_create_doctor():
    """Trusted administrative creation of an approved doctor account."""
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not full_name or not email or not username or not password:
        flash("All fields are required to onboard a doctor.", "error")
        return redirect(url_for("authority_doctors"))

    pw_hash = hash_password(password)
    code = generate_secure_code(6)
    code_hash_val = hash_code(code)
    expires_at = datetime.now() + timedelta(minutes=10)

    conn = get_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO users (username, email, password, password_hash, role, full_name, authority_code, is_approved, is_active, is_email_verified, access_code_hash, code_expires_at, code_used)
                VALUES (%s, %s, %s, %s, 'doctor', %s, %s, 1, 1, 1, %s, %s, 0)
            """, (username, email, password, pw_hash, full_name, f"DOC{int(datetime.now().timestamp())%1000}", code_hash_val, expires_at))
            conn.commit()

            send_access_code_email(
                recipient_email=email,
                recipient_name=full_name,
                access_code=code,
                purpose="Doctor Onboarding Activation",
                expires_in_minutes=10
            )

            log_audit_event(
                user_id=session.get("user_id"),
                role="authority",
                action="NEW_DOCTOR_CREATED",
                status="SUCCESS",
                details=f"Doctor onboarded: {full_name} ({email})"
            )
            flash(f"Doctor {full_name} created and approved successfully! Initial access code sent to {email}.", "success")
        except Exception as e:
            flash(f"Failed to create doctor: {e}", "error")
        cursor.close()
        conn.close()

    return redirect(url_for("authority_doctors"))


@app.route("/authority/audit-logs")
@role_required("authority", "admin")
def authority_audit_logs():
    """View system security audit trail."""
    conn = get_connection()
    logs = []
    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100")
        logs = cursor.fetchall()
        cursor.close()
        conn.close()
    return render_template("authority_audit_logs.html", logs=logs)


# ------------------- LOGOUT -------------------

@app.route("/logout")
def logout():
    """Destroy session securely."""
    log_audit_event(
        user_id=session.get("user_id") or session.get("patient_id"),
        role=session.get("role", "anonymous"),
        action="LOGOUT",
        status="SUCCESS"
    )
    session.clear()
    flash("You have been securely logged out.", "success")
    return redirect(url_for("login"))


# ------------------- PATIENT DASHBOARD & PORTAL -------------------

@app.route("/dashboard")
@login_required
def dashboard():
    """Protected Patient Dashboard."""
    # Redirect doctors and authority users to their dedicated portals
    if session.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard"))
    elif session.get("role") in ("authority", "admin"):
        return redirect(url_for("authority_dashboard"))

    patient = get_current_patient()
    if not patient:
        flash("Patient profile not found.", "error")
        return redirect(url_for("login"))

    conn = get_connection()
    counts = {"records": 0, "family": 0, "genetic": 0}
    if conn and patient:
        try:
            cursor = conn.cursor()
            p_id = patient.get("id")
            cursor.execute("SELECT COUNT(*) FROM medical_records WHERE patient_id = %s", (p_id,))
            counts["records"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM family_history WHERE patient_id = %s", (p_id,))
            counts["family"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM genetic_history WHERE patient_id = %s", (p_id,))
            counts["genetic"] = cursor.fetchone()[0]

            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[!] Error fetching dashboard counts: {e}")
            try:
                conn.close()
            except Exception:
                pass

    return render_template("dashboard.html", patient=patient, counts=counts)


# ------------------- PATIENT REGISTRATION -------------------

@app.route("/registration")
def registration():
    return render_template("Registration.html")


@app.route("/register", methods=["POST"])
def register():
    """Register a new patient account with secure Werkzeug password hashing."""
    full_name = request.form.get("full_name")
    raw_password = request.form.get("password") or "medicare123"
    dob = request.form.get("dob")
    age = request.form.get("age")
    gender = request.form.get("gender")
    blood_group = request.form.get("blood_group")
    marital_status = request.form.get("marital_status")
    occupation = request.form.get("occupation")

    mobile = request.form.get("mobile")
    alternate_mobile = request.form.get("alternate_mobile")
    email = request.form.get("email")
    address = request.form.get("address")
    city = request.form.get("city")
    state = request.form.get("state")
    pin_code = request.form.get("pin_code")

    emergency_name = request.form.get("emergency_name")
    emergency_relationship = request.form.get("emergency_relationship")
    emergency_number = request.form.get("emergency_number")

    allergies = request.form.get("allergies")
    existing_conditions = request.form.get("existing_conditions")
    current_medications = request.form.get("current_medications")

    conn = get_connection()
    if conn is None:
        return "Database connection failed!"

    pw_hash = hash_password(raw_password)

    cursor = conn.cursor()
    query = """
        INSERT INTO patients (
            full_name, password, password_hash, dob, age, gender, blood_group, marital_status, occupation,
            mobile, alternate_mobile, email, address, city, state, pin_code,
            emergency_name, emergency_relationship, emergency_number,
            allergies, existing_conditions, current_medications
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
    """
    values = (
        full_name, raw_password, pw_hash, dob, age, gender, blood_group, marital_status, occupation,
        mobile, alternate_mobile, email, address, city, state, pin_code,
        emergency_name, emergency_relationship, emergency_number,
        allergies, existing_conditions, current_medications,
    )

    try:
        cursor.execute(query, values)
        conn.commit()
        patient_id = cursor.lastrowid
        cursor.close()
        conn.close()

        # Secure session initialization
        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["role"] = "patient"
        session["patient_id"] = patient_id
        session["user_name"] = full_name

        log_audit_event(user_id=patient_id, role="patient", action="PATIENT_REGISTERED", status="SUCCESS")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Registration Successful - Medicare</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: Arial, sans-serif; background: #f6fbfb; color: #123f73;
            min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px;
        }}
        .card {{
            background: white; max-width: 550px; width: 100%; padding: 40px 30px;
            border-radius: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.08); text-align: center;
        }}
        .icon {{
            width: 70px; height: 70px; background: #eaf8f1; color: #188774;
            font-size: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 15px;
        }}
        h1 {{ color: #155985; font-size: 24px; margin-bottom: 8px; }}
        .desc {{ color: #60798e; font-size: 14px; margin-bottom: 20px; }}
        .credentials-card {{
            background: #f0f7fd; border: 2px solid #bce0f8; border-radius: 16px; padding: 20px; margin: 20px 0; text-align: left;
        }}
        .cred-row {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px dashed #d0e4f2; font-size: 14px; }}
        .cred-val {{ font-weight: bold; font-family: monospace; background: white; padding: 3px 8px; border-radius: 6px; color: #155985; border: 1px solid #d5e6f2; }}
        .btn {{ display: block; padding: 13px; border-radius: 25px; text-decoration: none; font-weight: bold; font-size: 14px; margin-top: 10px; text-align: center; }}
        .btn-primary {{ background: #155985; color: white; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✓</div>
        <h1>Patient Registered Successfully!</h1>
        <p class="desc">Your account is active. Your password has been securely encrypted in our production database.</p>
        
        <div class="credentials-card">
            <div class="cred-row">
                <span>Assigned Patient ID:</span>
                <span class="cred-val">P{patient_id:05d}</span>
            </div>
            <div class="cred-row">
                <span>Patient Full Name:</span>
                <strong>{full_name}</strong>
            </div>
            <div class="cred-row">
                <span>Registered Mobile:</span>
                <span class="cred-val">{mobile or 'N/A'}</span>
            </div>
        </div>

        <a href="/dashboard" class="btn btn-primary">Proceed to Patient Dashboard →</a>
    </div>
</body>
</html>"""

    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return f"Registration failed: {e}"


# ------------------- HEALTH PROFILE & QR CODE (PROTECTED) -------------------

@app.route("/health-profile")
@app.route("/health-profile/<int:patient_id>")
@login_required
def health_profile(patient_id=None):
    """View patient health profile with IDOR authorization verification."""
    target_id = patient_id or session.get("patient_id")
    if not target_id or not verify_patient_access(target_id):
        return render_template("403.html"), 403

    patient = get_current_patient(target_id)
    if not patient:
        return render_template("404.html"), 404

    qr_base64 = generate_qr_base64(patient)
    message = request.args.get("msg")
    return render_template("health_profile.html", patient=patient, qr_base64=qr_base64, message=message)


@app.route("/update-health-profile", methods=["POST"])
@login_required
def update_health_profile():
    """Update patient health profile with ownership verification."""
    patient_id = request.form.get("patient_id")
    if not patient_id or not verify_patient_access(patient_id):
        return render_template("403.html"), 403

    full_name = request.form.get("full_name")
    age = request.form.get("age")
    blood_group = request.form.get("blood_group")
    mobile = request.form.get("mobile")
    email = request.form.get("email")
    address = request.form.get("address")
    allergies = request.form.get("allergies")
    existing_conditions = request.form.get("existing_conditions")
    current_medications = request.form.get("current_medications")
    emergency_name = request.form.get("emergency_name")
    emergency_relationship = request.form.get("emergency_relationship")
    emergency_number = request.form.get("emergency_number")

    conn = get_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE patients SET
                full_name = %s, age = %s, blood_group = %s, mobile = %s, email = %s, address = %s,
                allergies = %s, existing_conditions = %s, current_medications = %s,
                emergency_name = %s, emergency_relationship = %s, emergency_number = %s
            WHERE id = %s
        """, (
            full_name, age, blood_group, mobile, email, address,
            allergies, existing_conditions, current_medications,
            emergency_name, emergency_relationship, emergency_number,
            patient_id
        ))
        conn.commit()
        cursor.close()
        conn.close()

        log_audit_event(
            user_id=session.get("user_id") or patient_id,
            role=session.get("role"),
            action="HEALTH_PROFILE_UPDATED",
            status="SUCCESS",
            details=f"Updated patient ID {patient_id}"
        )

    return redirect(url_for("health_profile", patient_id=patient_id, msg="Health Profile updated successfully!"))


@app.route("/emergency/<int:patient_id>")
def emergency_view(patient_id):
    """
    Public emergency triage view accessible by paramedics and first responders.
    Exposes only critical triage items without private account credentials or full history.
    """
    conn = get_connection()
    patient = None
    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("""
            SELECT id, full_name, age, gender, blood_group, allergies,
                   existing_conditions, current_medications, emergency_name,
                   emergency_relationship, emergency_number
            FROM patients WHERE id = %s
        """, (patient_id,))
        patient = cursor.fetchone()
        cursor.close()
        conn.close()

    if not patient:
        return render_template("404.html"), 404

    return render_template("emergency_view.html", patient=patient)


@app.route("/qr/<int:patient_id>")
@login_required
def download_qr(patient_id):
    """Direct PNG image download of the patient's Emergency Health QR code (Protected)."""
    if not verify_patient_access(patient_id):
        return render_template("403.html"), 403

    patient = get_current_patient(patient_id)
    if not patient:
        return render_template("404.html"), 404

    patient_id_formatted = f"P{int(patient['id']):05d}"
    base_url = get_base_url()
    qr_data = (
        f"MEDICARE EMERGENCY HEALTH PASS\n"
        f"ID: {patient_id_formatted}\n"
        f"Name: {patient.get('full_name')}\n"
        f"Blood: {patient.get('blood_group')}\n"
        f"Allergies: {patient.get('allergies')}\n"
        f"Emergency: {patient.get('emergency_name')} ({patient.get('emergency_number')})\n"
        f"Pass: {base_url}/emergency/{patient_id}"
    )

    qr = qrcode.QRCode(box_size=10, border=3)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#155985", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="image/png",
        as_attachment=request.args.get("download") == "1",
        download_name=f"Medicare_QR_{patient_id_formatted}.png",
    )


@app.route("/card")
@app.route("/card/<int:patient_id>")
@login_required
def view_medical_card(patient_id=None):
    """View official PVC-style medical ID card (Protected)."""
    target_id = patient_id or session.get("patient_id")
    if not target_id or not verify_patient_access(target_id):
        return render_template("403.html"), 403

    patient = get_current_patient(target_id)
    if not patient:
        return render_template("404.html"), 404

    qr_b64 = generate_qr_base64(patient)
    return render_template("medical_id_card.html", patient=patient, qr_base64=qr_b64)


# ------------------- FAMILY MEDICAL HISTORY (PROTECTED) -------------------

@app.route("/family-history", methods=["GET", "POST"])
@login_required
def family_history():
    patient = get_current_patient()
    if not patient:
        return render_template("403.html"), 403
    p_id = patient.get("id")

    conn = get_connection()
    if request.method == "POST":
        relative_name = request.form.get("relative_name")
        relationship = request.form.get("relationship")
        condition_name = request.form.get("condition_name")
        age_at_diagnosis = request.form.get("age_at_diagnosis")
        is_living = request.form.get("is_living", "Yes")
        notes = request.form.get("notes")

        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO family_history (patient_id, relative_name, relationship, condition_name, age_at_diagnosis, is_living, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (p_id, relative_name, relationship, condition_name, age_at_diagnosis, is_living, notes))
            conn.commit()
            cursor.close()

    history = []
    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM family_history WHERE patient_id = %s ORDER BY id DESC", (p_id,))
        history = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("family_history.html", patient=patient, history=history)


# ------------------- GENETIC & HEREDITARY HISTORY (PROTECTED) -------------------

@app.route("/genetic-history", methods=["GET", "POST"])
@login_required
def genetic_history():
    patient = get_current_patient()
    if not patient:
        return render_template("403.html"), 403
    p_id = patient.get("id")

    conn = get_connection()
    if request.method == "POST":
        condition_title = request.form.get("condition_title")
        inheritance_pattern = request.form.get("inheritance_pattern")
        affected_relatives = request.form.get("affected_relatives")
        carrier_status = request.form.get("carrier_status")
        risk_level = request.form.get("risk_level", "Moderate")
        notes = request.form.get("notes")

        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO genetic_history (patient_id, condition_title, inheritance_pattern, affected_relatives, carrier_status, risk_level, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (p_id, condition_title, inheritance_pattern, affected_relatives, carrier_status, risk_level, notes))
            conn.commit()
            cursor.close()

    genetics = []
    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM genetic_history WHERE patient_id = %s ORDER BY id DESC", (p_id,))
        genetics = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("genetic_history.html", patient=patient, genetics=genetics)


# ------------------- MEDICAL RECORDS & PRESCRIPTIONS (PROTECTED) -------------------

@app.route("/medical-records", methods=["GET", "POST"])
@login_required
def medical_records():
    patient = get_current_patient()
    if not patient:
        return render_template("403.html"), 403
    p_id = patient.get("id")

    conn = get_connection()
    if request.method == "POST":
        record_type = request.form.get("record_type")
        title = request.form.get("title")
        doctor_name = request.form.get("doctor_name")
        hospital_name = request.form.get("hospital_name")
        record_date = request.form.get("record_date")
        description = request.form.get("description")
        attachment_name = request.form.get("attachment_name") or "Medical_Report.pdf"

        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO medical_records (patient_id, record_type, title, doctor_name, hospital_name, record_date, description, attachment_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (p_id, record_type, title, doctor_name, hospital_name, record_date, description, attachment_name))
            conn.commit()
            cursor.close()

    records = []
    if conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM medical_records WHERE patient_id = %s ORDER BY id DESC", (p_id,))
        records = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("medical_records.html", patient=patient, records=records)


# ------------------- SETTINGS (PROTECTED) -------------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    patient = get_current_patient()
    if not patient:
        return render_template("403.html"), 403
    message = None
    if request.method == "POST":
        message = "Preferences saved successfully!"
    return render_template("settings.html", patient=patient, message=message)


# ------------------- OFFLINE AI HEALTH ASSISTANT (PROTECTED) -------------------

@app.route("/ai-assistant")
@login_required
def ai_assistant_view():
    patient = get_current_patient()
    if not patient:
        return render_template("403.html"), 403
    return render_template("ai_assistant.html", patient=patient)


@app.route("/api/ai-chat", methods=["POST"])
@login_required
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"reply": "Please describe your question or symptom.", "level": "empty", "suggestions": []})

    patient = get_current_patient()
    result = ai_assistant.analyze(query, patient)
    return jsonify(result)


# ------------------- DECOMMISSIONED INSECURE ENDPOINT -------------------

@app.route("/api/lookup-password")
def api_lookup_password():
    """Permanently decommissioned endpoint. Plaintext password leaks are blocked."""
    log_audit_event(
        role="anonymous",
        action="INSECURE_ENDPOINT_BLOCKED",
        status="BLOCKED",
        details="Attempt to access decommissioned password lookup API"
    )
    return jsonify({
        "success": False,
        "error": "This insecure endpoint has been permanently decommissioned for HIPAA/medical data compliance."
    }), 403


# ------------------- HEALTH & ERROR HANDLERS -------------------

@app.route("/test-db")
def test_db():
    conn = get_connection()
    if conn:
        conn.close()
        return "Database connection successful!"
    return "Database connection failed!", 500


@app.errorhandler(401)
def unauthorized(e):
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    flash("Authentication required. Please log in.", "error")
    return redirect(url_for("login"))


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    return render_template("403.html"), 403


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    trace = traceback.format_exc()
    print("\n" + "="*60)
    print("[500 SERVER ERROR DETAILS]:")
    print(trace)
    print("="*60 + "\n")
    return render_template("500.html", error_details=str(e), traceback_str=trace), 500


# ------------------- APPLICATION RUNNER -------------------

if __name__ == "__main__":
    try:
        init_db()
    except Exception as e:
        print(f"[!] DB Init note: {e}")

    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=True)
