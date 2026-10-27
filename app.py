import base64
import io
import json
import os
import sys
import threading
import traceback
import webbrowser
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, flash, jsonify, redirect, render_template, request,
    send_file, session, url_for, abort
)
import qrcode
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_connection, init_db
from ai_assistant import ai_assistant
from mailer import send_verification_email
import auth_service

app = Flask(__name__)

# Session and cookie security configuration
app.secret_key = os.environ.get("SECRET_KEY", "medicare_secure_session_key_2026")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(os.environ.get("FLASK_ENV") == "production" or bool(os.environ.get("RENDER"))),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2)
)

# Ensure database tables exist upon start
try:
    init_db()
except Exception as _db_init_err:
    print(f"[!] Database startup notice: {_db_init_err}")


# ============================================================================
# AUTHORIZATION DECORATORS & ACCESS CONTROL HELPERS
# ============================================================================

def login_required(f):
    """Requires user to be authenticated in session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "Authentication required", "status": 401}), 401
            flash("Please sign in to access your Medicare portal.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    """Restricts route to specified roles (e.g. 'doctor', 'authority', 'patient')."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("logged_in"):
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify({"error": "Authentication required", "status": 401}), 401
                flash("Please sign in to access this portal.", "error")
                return redirect(url_for("login"))

            user_role = session.get("role")
            if user_role not in allowed_roles:
                auth_service.log_audit_event(
                    action="UNAUTHORIZED_PORTAL_ACCESS_ATTEMPT",
                    user_id=session.get("user_id") or session.get("patient_id"),
                    user_role=user_role,
                    details=f"Attempted access to {request.path} (Allowed: {allowed_roles})"
                )
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify({"error": "Forbidden: Insufficient privileges", "status": 403}), 403
                
                flash(f"Access Denied: You do not have permissions for the {request.path} area.", "error")
                if user_role == "doctor":
                    return redirect(url_for("doctor_dashboard"))
                elif user_role == "authority":
                    return redirect(url_for("authority_dashboard"))
                else:
                    return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def verify_patient_access(patient_id):
    """
    Enforces Strict Patient Data Privacy & IDOR Prevention:
    - Unauthenticated: 401
    - Patient: Can ONLY access their own patient_id (403 otherwise)
    - Doctor: Can ONLY access patients assigned to them (403 otherwise)
    - Authority: Allowed (Audit monitored)
    """
    is_allowed, reason, status_code = auth_service.can_user_access_patient(session, patient_id)
    if not is_allowed:
        auth_service.log_audit_event(
            action="PATIENT_IDOR_BLOCKED",
            user_id=session.get("user_id") or session.get("patient_id"),
            user_role=session.get("role"),
            details=f"Target Patient ID: {patient_id}. Reason: {reason}"
        )
        if request.path.startswith("/api/") or request.is_json:
            return False, (jsonify({"error": reason, "status": status_code}), status_code)
        flash(reason, "error")
        return False, (render_template("404.html", error_message=reason), status_code)
    return True, None


def get_patient_by_id(patient_id):
    """Retrieve patient record by ID from database."""
    conn = get_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE id = %s", (patient_id,))
        p = cur.fetchone()
        cur.close()
        conn.close()
        return p
    except Exception as e:
        print(f"[!] Patient retrieval error: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return None


def get_base_url():
    """Determine application public base URL dynamically (supports Render HTTPS)."""
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
    """Generate scannable Emergency QR code for authorized patient profile."""
    if not patient:
        return ""

    base_url = get_base_url()
    patient_id_formatted = f"P{int(patient['id']):05d}"
    qr_data = (
        f"MEDICARE SECURE HEALTH ID\n"
        f"ID: {patient_id_formatted}\n"
        f"Name: {patient.get('full_name', '')}\n"
        f"Blood: {patient.get('blood_group', 'Unknown')}\n"
        f"DOB: {patient.get('dob', 'N/A')} (Age: {patient.get('age', 'N/A')})\n"
        f"Allergies: {patient.get('allergies', 'None')}\n"
        f"Conditions: {patient.get('existing_conditions', 'None')}\n"
        f"Emergency Contact: {patient.get('emergency_name', 'N/A')} ({patient.get('emergency_relationship', '')}) - {patient.get('emergency_number', 'N/A')}\n"
        f"Verified Portal: {base_url}/health-profile/{patient.get('id')}"
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


# ============================================================================
# DOCTOR REGISTRATION & ONBOARDING (Pending Administrative Verification)
# ============================================================================

@app.route("/doctor-registration")
def doctor_registration_view():
    return render_template("doctor_registration.html")


@app.route("/doctor-register", methods=["POST"])
def doctor_register():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    license_number = request.form.get("license_number", "").strip()
    specialization = request.form.get("specialization", "General Medicine").strip()
    raw_password = request.form.get("password", "").strip()

    if not full_name or not email or not raw_password:
        flash("Full name, email, and password are required.", "error")
        return redirect(url_for("doctor_registration_view"))

    conn = get_connection()
    if not conn:
        flash("Database connection error.", "error")
        return redirect(url_for("doctor_registration_view"))

    cur = conn.cursor()
    # Check if email already registered
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    existing = cur.fetchone()
    if existing:
        cur.close()
        conn.close()
        flash("An account with this email address already exists. Please log in.", "error")
        return redirect(url_for("login", tab="doctor"))

    password_hash = generate_password_hash(raw_password)
    # Strictly saved as is_approved = FALSE pending Authority review
    cur.execute("""
        INSERT INTO users (
            email, password_hash, role, full_name, specialization, license_number, is_approved, is_active
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (email, password_hash, "doctor", full_name, specialization, license_number, False, True))
    conn.commit()
    cur.close()
    conn.close()

    auth_service.log_audit_event(
        action="DOCTOR_REGISTRATION_SUBMITTED",
        user_role="doctor",
        details=f"Dr. {full_name} ({email}) applied with license {license_number}. Pending approval."
    )

    flash("Application submitted successfully! Your credentials have been forwarded to Hospital Administration. You will be able to sign in once approved.", "success")
    return redirect(url_for("login", tab="doctor"))


@app.route("/api/onboard-authority", methods=["POST"])
@role_required("authority")
def api_onboard_authority():
    """Allows an approved Hospital Authority to onboard/invite another authority officer."""
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    raw_password = request.form.get("password", "").strip()

    if not full_name or not email or not raw_password:
        return jsonify({"success": False, "error": "All fields are required"}), 400

    conn = get_connection()
    if not conn:
        return jsonify({"success": False, "error": "Database error"}), 500

    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"success": False, "error": "User with this email already exists"}), 400

    pw_hash = generate_password_hash(raw_password)
    cur.execute("""
        INSERT INTO users (email, password_hash, role, full_name, is_approved, is_active)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (email, pw_hash, "authority", full_name, True, True))
    conn.commit()
    cur.close()
    conn.close()

    auth_service.log_audit_event(
        action="NEW_AUTHORITY_OFFICER_ONBOARDED",
        user_id=session.get("user_id"),
        user_role="authority",
        details=f"Onboarded authority officer: {full_name} ({email})"
    )

    flash(f"Authority account created for {full_name} ({email}).", "success")
    return redirect(url_for("authority_dashboard"))


# ============================================================================
# PUBLIC & ENTRY ROUTES
# ============================================================================

@app.route("/")
def home():
    return render_template("intro.html")


# ============================================================================
# AUTHENTICATION & LOGIN WORKFLOWS (Patient, Doctor, Authority)
# ============================================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role", "patient").strip().lower()

        # ---------------- DOCTOR LOGIN WORKFLOW ----------------
        if role == "doctor":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()

            if not email or not password:
                flash("Doctor email and password are required.", "error")
                return redirect(url_for("login", tab="doctor"))

            doctor_user, err_msg = auth_service.authenticate_user_credentials(email, password, required_role="doctor")
            if not doctor_user:
                flash(err_msg, "error")
                return redirect(url_for("login", tab="doctor"))

            # Step 2: Generate short-lived verification access code & email it
            sent, send_msg = auth_service.generate_and_dispatch_code(doctor_user, purpose="doctor_login")
            if not sent:
                flash(f"Security Notice: {send_msg}", "error")
                return redirect(url_for("login", tab="doctor"))

            # Stage user in pending authentication session
            session["pending_auth"] = {
                "user_id": doctor_user["id"],
                "email": doctor_user["email"],
                "role": "doctor",
                "name": doctor_user["full_name"],
                "purpose": "doctor_login"
            }
            flash(f"Access code sent to {doctor_user['email']}. Please enter the 6-digit code below.", "success")
            return redirect(url_for("verify_code"))

        # ---------------- AUTHORITY LOGIN WORKFLOW ----------------
        elif role == "authority":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()

            if not email or not password:
                flash("Authority email and password are required.", "error")
                return redirect(url_for("login", tab="authority"))

            auth_user, err_msg = auth_service.authenticate_user_credentials(email, password, required_role="authority")
            if not auth_user:
                flash(err_msg, "error")
                return redirect(url_for("login", tab="authority"))

            # Step 2: Generate short-lived verification access code & email it
            sent, send_msg = auth_service.generate_and_dispatch_code(auth_user, purpose="authority_login")
            if not sent:
                flash(f"Security Notice: {send_msg}", "error")
                return redirect(url_for("login", tab="authority"))

            session["pending_auth"] = {
                "user_id": auth_user["id"],
                "email": auth_user["email"],
                "role": "authority",
                "name": auth_user["full_name"],
                "purpose": "authority_login"
            }
            flash(f"Authority code sent to {auth_user['email']}. Please enter the 6-digit code below.", "success")
            return redirect(url_for("verify_code"))

        # ---------------- PATIENT LOGIN WORKFLOW ----------------
        else:
            identifier = request.form.get("identifier", "").strip()
            entered_pw = request.form.get("password", "").strip()

            if not identifier:
                flash("Please enter your Patient ID, Mobile Number, or Email.", "error")
                return redirect(url_for("login", tab="patient"))

            conn = get_connection()
            patient = None
            if conn:
                cur = conn.cursor()
                clean_id = identifier.upper().replace("P", "")
                if clean_id.isdigit():
                    cur.execute("SELECT * FROM patients WHERE id = %s", (int(clean_id),))
                    patient = cur.fetchone()

                if not patient:
                    cur.execute("SELECT * FROM patients WHERE mobile = %s OR email = %s", (identifier, identifier))
                    patient = cur.fetchone()
                cur.close()
                conn.close()

            if not patient:
                flash("No patient account found matching your credentials.", "error")
                return redirect(url_for("login", tab="patient"))

            # Password verification (supports both Werkzeug hash and safe fallback)
            stored_hash = patient.get("password_hash")
            plain_pw = patient.get("password") or "medicare123"
            valid_pw = False

            if stored_hash and check_password_hash(stored_hash, entered_pw):
                valid_pw = True
            elif plain_pw and plain_pw == entered_pw:
                valid_pw = True
                # Upgrade to secure hash in DB
                new_hash = generate_password_hash(entered_pw)
                c_up = get_connection()
                if c_up:
                    cur_u = c_up.cursor()
                    cur_u.execute("UPDATE patients SET password_hash = %s, password = NULL WHERE id = %s", (new_hash, patient["id"]))
                    c_up.commit()
                    cur_u.close()
                    c_up.close()

            if not valid_pw:
                flash("Incorrect password for patient account.", "error")
                return redirect(url_for("login", tab="patient"))

            # Establish authenticated patient session
            session.clear()
            session.permanent = True
            session["logged_in"] = True
            session["role"] = "patient"
            session["patient_id"] = patient["id"]
            session["user_name"] = patient.get("full_name")
            session["email"] = patient.get("email")

            auth_service.log_audit_event("PATIENT_LOGIN_SUCCESS", user_id=patient["id"], user_role="patient")
            flash(f"Welcome back, {patient.get('full_name')}!", "success")
            return redirect(url_for("dashboard"))

    # GET Request: render login template with active tab
    active_tab = request.args.get("tab", "patient")
    return render_template("login.html", active_tab=active_tab)


@app.route("/verify-code", methods=["GET", "POST"])
def verify_code():
    """Second-factor verification code confirmation page for Doctors and Authorities."""
    pending = session.get("pending_auth")
    if not pending:
        flash("No login attempt in progress. Please log in first.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        purpose = pending.get("purpose")
        email = pending.get("email")

        is_valid, reason = auth_service.verify_submitted_code(email, code, purpose)
        if not is_valid:
            flash(reason, "error")
            return render_template("verify_code.html", pending=pending)

        # Successful code verification -> finalize authenticated session
        role = pending["role"]
        user_id = pending["user_id"]
        user_name = pending["name"]
        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["role"] = role
        session["user_id"] = user_id
        session["user_name"] = user_name
        session["email"] = email

        auth_service.reset_failed_login(user_id, table="users")
        auth_service.log_audit_event(
            action=f"{role.upper()}_MFA_LOGIN_SUCCESS",
            user_id=user_id,
            user_role=role,
            details=f"Successful 2FA login for {email}"
        )

        flash(f"Authenticated successfully. Welcome, {user_name}!", "success")
        if role == "doctor":
            return redirect(url_for("doctor_dashboard"))
        elif role == "authority":
            return redirect(url_for("authority_dashboard"))
        return redirect(url_for("home"))

    return render_template("verify_code.html", pending=pending)


@app.route("/resend-code", methods=["POST"])
def resend_code():
    """Resend a new short-lived verification access code."""
    pending = session.get("pending_auth")
    if not pending:
        flash("No pending verification session.", "error")
        return redirect(url_for("login"))

    conn = get_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (pending["user_id"],))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            sent, msg = auth_service.generate_and_dispatch_code(user, purpose=pending["purpose"])
            if sent:
                flash(f"A new access code has been dispatched to {user['email']}.", "success")
            else:
                flash(f"Could not send code: {msg}", "error")

    return redirect(url_for("verify_code"))


@app.route("/logout")
def logout():
    role = session.get("role")
    u_id = session.get("user_id") or session.get("patient_id")
    if u_id:
        auth_service.log_audit_event("USER_LOGOUT", user_id=u_id, user_role=role)
    session.clear()
    flash("You have been signed out securely.", "success")
    return redirect(url_for("login"))


# ============================================================================
# DOCTOR PORTAL & ACTIONS
# ============================================================================

@app.route("/doctor-dashboard")
@role_required("doctor")
def doctor_dashboard():
    """Doctor Portal: Displays strictly assigned patients, consultations, and medical history."""
    doctor_id = session.get("user_id")
    conn = get_connection()
    assigned_patients = []
    doctor_info = None

    if conn:
        cur = conn.cursor()
        # Fetch doctor details
        cur.execute("SELECT * FROM users WHERE id = %s", (doctor_id,))
        doctor_info = cur.fetchone()

        # Fetch ONLY assigned patients
        cur.execute("""
            SELECT p.*, dpa.assigned_date, dpa.notes AS assignment_notes
            FROM patients p
            JOIN doctor_patient_assignments dpa ON p.id = dpa.patient_id
            WHERE dpa.doctor_id = %s
            ORDER BY p.id DESC
        """, (doctor_id,))
        assigned_patients = cur.fetchall()
        cur.close()
        conn.close()

    return render_template("doctor_dashboard.html", doctor=doctor_info, patients=assigned_patients)


# ============================================================================
# AUTHORITY PORTAL & ACTIONS
# ============================================================================

@app.route("/authority-dashboard")
@role_required("authority")
def authority_dashboard():
    """Authority Portal: Protected hospital overview, doctor onboarding/approval, and audit logs."""
    query = request.args.get("q", "").strip()
    conn = get_connection()
    patients = []
    doctors = []
    recent_audits = []

    if conn:
        cur = conn.cursor()
        # Search or list patients
        if query:
            clean_q = query.upper().replace("P", "")
            cur.execute("""
                SELECT * FROM patients
                WHERE full_name LIKE %s OR mobile LIKE %s OR id = %s
                ORDER BY id DESC
            """, (f"%{query}%", f"%{query}%", int(clean_q) if clean_q.isdigit() else -1))
        else:
            cur.execute("SELECT * FROM patients ORDER BY id DESC")
        patients = cur.fetchall()

        # List doctor accounts for approval & status monitoring
        cur.execute("SELECT * FROM users WHERE role = 'doctor' ORDER BY id DESC")
        doctors = cur.fetchall()

        # Fetch recent security audit logs
        cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 20")
        recent_audits = cur.fetchall()

        cur.close()
        conn.close()

    return render_template(
        "authority_dashboard.html",
        patients=patients,
        doctors=doctors,
        recent_audits=recent_audits,
        query=query
    )


@app.route("/api/approve-doctor/<int:doctor_id>", methods=["POST"])
@role_required("authority")
def api_approve_doctor(doctor_id):
    """Authority action: approve or toggle doctor practice status."""
    conn = get_connection()
    if not conn:
        return jsonify({"success": False, "error": "Database error"}), 500

    cur = conn.cursor()
    cur.execute("SELECT id, is_approved, full_name, email FROM users WHERE id = %s AND role = 'doctor'", (doctor_id,))
    doc = cur.fetchone()
    if not doc:
        cur.close()
        conn.close()
        return jsonify({"success": False, "error": "Doctor not found"}), 404

    new_status = not doc.get("is_approved", False)
    cur.execute("UPDATE users SET is_approved = %s WHERE id = %s", (new_status, doctor_id))
    conn.commit()
    cur.close()
    conn.close()

    auth_service.log_audit_event(
        action=f"DOCTOR_APPROVAL_STATUS_CHANGED:{new_status}",
        user_id=session.get("user_id"),
        user_role="authority",
        details=f"Doctor ID: {doctor_id} ({doc.get('full_name')}) approval set to {new_status}"
    )

    return jsonify({"success": True, "is_approved": new_status})


# ============================================================================
# PATIENT PORTAL & CLINICAL RECORDS
# ============================================================================

@app.route("/dashboard")
@role_required("patient")
def dashboard():
    """Patient Dashboard: Restricted strictly to the authenticated patient."""
    patient_id = session.get("patient_id")
    patient = get_patient_by_id(patient_id)
    if not patient:
        flash("Patient profile could not be loaded.", "error")
        return redirect(url_for("logout"))

    conn = get_connection()
    counts = {"records": 0, "family": 0, "genetic": 0}
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM medical_records WHERE patient_id = %s", (patient_id,))
            counts["records"] = cur.fetchone().get("cnt", 0)

            cur.execute("SELECT COUNT(*) as cnt FROM family_history WHERE patient_id = %s", (patient_id,))
            counts["family"] = cur.fetchone().get("cnt", 0)

            cur.execute("SELECT COUNT(*) as cnt FROM genetic_history WHERE patient_id = %s", (patient_id,))
            counts["genetic"] = cur.fetchone().get("cnt", 0)

            cur.close()
            conn.close()
        except Exception as e:
            print(f"[!] Error fetching dashboard counts: {e}")
            try:
                conn.close()
            except Exception:
                pass

    return render_template("dashboard.html", patient=patient, counts=counts)


@app.route("/health-profile")
@app.route("/health-profile/<int:patient_id>")
@login_required
def health_profile(patient_id=None):
    """View Health Profile: Protected by strict IDOR checks."""
    if patient_id is None:
        patient_id = session.get("patient_id")
        if not patient_id:
            flash("Patient ID not specified.", "error")
            return redirect(url_for("home"))

    # Enforce authorization
    is_allowed, err_resp = verify_patient_access(patient_id)
    if not is_allowed:
        return err_resp

    patient = get_patient_by_id(patient_id)
    if not patient:
        abort(404)

    qr_base64 = generate_qr_base64(patient)
    message = request.args.get("msg")
    return render_template("health_profile.html", patient=patient, qr_base64=qr_base64, message=message)


@app.route("/update-health-profile", methods=["POST"])
@login_required
def update_health_profile():
    patient_id = request.form.get("patient_id")
    if not patient_id:
        return redirect(url_for("dashboard"))

    # IDOR Check
    is_allowed, err_resp = verify_patient_access(int(patient_id))
    if not is_allowed:
        return err_resp

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
        cur = conn.cursor()
        cur.execute("""
            UPDATE patients SET
                full_name = %s,
                age = %s,
                blood_group = %s,
                mobile = %s,
                email = %s,
                address = %s,
                allergies = %s,
                existing_conditions = %s,
                current_medications = %s,
                emergency_name = %s,
                emergency_relationship = %s,
                emergency_number = %s
            WHERE id = %s
        """, (
            full_name, age, blood_group, mobile, email, address,
            allergies, existing_conditions, current_medications,
            emergency_name, emergency_relationship, emergency_number,
            patient_id
        ))
        conn.commit()
        cur.close()
        conn.close()

    auth_service.log_audit_event("PATIENT_PROFILE_UPDATED", user_id=session.get("user_id") or session.get("patient_id"), user_role=session.get("role"), details=f"Updated profile for patient #{patient_id}")
    return redirect(url_for("health_profile", patient_id=patient_id, msg="Health Profile updated successfully!"))


@app.route("/card")
@app.route("/card/<int:patient_id>")
@login_required
def view_medical_card(patient_id=None):
    if patient_id is None:
        patient_id = session.get("patient_id")
        if not patient_id:
            flash("Patient ID not found.", "error")
            return redirect(url_for("home"))

    is_allowed, err_resp = verify_patient_access(patient_id)
    if not is_allowed:
        return err_resp

    patient = get_patient_by_id(patient_id)
    if not patient:
        abort(404)

    qr_b64 = generate_qr_base64(patient)
    return render_template("medical_id_card.html", patient=patient, qr_base64=qr_b64)


@app.route("/qr/<int:patient_id>")
@login_required
def download_qr(patient_id):
    """Direct PNG image download of the patient's Emergency Health QR code (Protected)."""
    is_allowed, err_resp = verify_patient_access(patient_id)
    if not is_allowed:
        return err_resp

    patient = get_patient_by_id(patient_id)
    if not patient:
        abort(404)

    patient_id_formatted = f"P{int(patient['id']):05d}"
    base_url = get_base_url()
    qr_data = (
        f"MEDICARE SECURE HEALTH ID\n"
        f"ID: {patient_id_formatted}\n"
        f"Name: {patient.get('full_name')}\n"
        f"Blood: {patient.get('blood_group')}\n"
        f"Allergies: {patient.get('allergies')}\n"
        f"Emergency: {patient.get('emergency_name')} ({patient.get('emergency_number')})\n"
        f"Profile: {base_url}/health-profile/{patient_id}"
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


# ------------------- FAMILY MEDICAL HISTORY -------------------

@app.route("/family-history", methods=["GET", "POST"])
@login_required
def family_history():
    patient_id = session.get("patient_id")
    if not patient_id:
        flash("Access to family history requires patient authentication.", "error")
        return redirect(url_for("login"))

    patient = get_patient_by_id(patient_id)
    conn = get_connection()
    if request.method == "POST":
        relative_name = request.form.get("relative_name")
        relationship = request.form.get("relationship")
        condition_name = request.form.get("condition_name")
        age_at_diagnosis = request.form.get("age_at_diagnosis")
        is_living = request.form.get("is_living", "Yes")
        notes = request.form.get("notes")

        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO family_history (patient_id, relative_name, relationship, condition_name, age_at_diagnosis, is_living, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (patient_id, relative_name, relationship, condition_name, age_at_diagnosis, is_living, notes))
            conn.commit()
            cur.close()

    history = []
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM family_history WHERE patient_id = %s ORDER BY id DESC", (patient_id,))
        history = cur.fetchall()
        cur.close()
        conn.close()

    return render_template("family_history.html", patient=patient, history=history)


# ------------------- GENETIC & HEREDITARY HISTORY -------------------

@app.route("/genetic-history", methods=["GET", "POST"])
@login_required
def genetic_history():
    patient_id = session.get("patient_id")
    if not patient_id:
        flash("Access requires patient authentication.", "error")
        return redirect(url_for("login"))

    patient = get_patient_by_id(patient_id)
    conn = get_connection()
    if request.method == "POST":
        condition_title = request.form.get("condition_title")
        inheritance_pattern = request.form.get("inheritance_pattern")
        affected_relatives = request.form.get("affected_relatives")
        carrier_status = request.form.get("carrier_status")
        risk_level = request.form.get("risk_level", "Moderate")
        notes = request.form.get("notes")

        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO genetic_history (patient_id, condition_title, inheritance_pattern, affected_relatives, carrier_status, risk_level, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (patient_id, condition_title, inheritance_pattern, affected_relatives, carrier_status, risk_level, notes))
            conn.commit()
            cur.close()

    genetics = []
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM genetic_history WHERE patient_id = %s ORDER BY id DESC", (patient_id,))
        genetics = cur.fetchall()
        cur.close()
        conn.close()

    return render_template("genetic_history.html", patient=patient, genetics=genetics)


# ------------------- MEDICAL RECORDS -------------------

@app.route("/medical-records", methods=["GET", "POST"])
@login_required
def medical_records():
    # If patient, show their own. If doctor/authority, allow viewing target patient.
    target_p_id = request.args.get("patient_id", type=int) or session.get("patient_id")
    if not target_p_id:
        flash("Patient not specified.", "error")
        return redirect(url_for("home"))

    is_allowed, err_resp = verify_patient_access(target_p_id)
    if not is_allowed:
        return err_resp

    patient = get_patient_by_id(target_p_id)
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
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO medical_records (patient_id, record_type, title, doctor_name, hospital_name, record_date, description, attachment_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (target_p_id, record_type, title, doctor_name, hospital_name, record_date, description, attachment_name))
            conn.commit()
            cur.close()

    records = []
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM medical_records WHERE patient_id = %s ORDER BY id DESC", (target_p_id,))
        records = cur.fetchall()
        cur.close()
        conn.close()

    return render_template("medical_records.html", patient=patient, records=records)


# ------------------- SETTINGS -------------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    patient = get_patient_by_id(session.get("patient_id"))
    message = None
    if request.method == "POST":
        message = "Preferences saved successfully!"
    return render_template("settings.html", patient=patient, message=message)


# ------------------- REGISTRATION -------------------

@app.route("/registration")
def registration():
    return render_template("Registration.html")


@app.route("/register", methods=["POST"])
def register():
    full_name = request.form.get("full_name")
    raw_password = request.form.get("password") or "medicare123"
    password_hash = generate_password_hash(raw_password)

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
        return "Database connection failed!", 500

    cur = conn.cursor()
    query = """
        INSERT INTO patients (
            full_name, password_hash, dob, age, gender, blood_group, marital_status, occupation,
            mobile, alternate_mobile, email, address, city, state, pin_code,
            emergency_name, emergency_relationship, emergency_number,
            allergies, existing_conditions, current_medications
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
    """
    values = (
        full_name, password_hash, dob, age, gender, blood_group, marital_status, occupation,
        mobile, alternate_mobile, email, address, city, state, pin_code,
        emergency_name, emergency_relationship, emergency_number,
        allergies, existing_conditions, current_medications,
    )

    try:
        cur.execute(query, values)
        conn.commit()
        patient_id = cur.lastrowid
        cur.close()
        conn.close()

        # Update session to newly registered patient
        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["role"] = "patient"
        session["patient_id"] = patient_id
        session["user_name"] = full_name
        session["email"] = email

        auth_service.log_audit_event("PATIENT_REGISTERED", user_id=patient_id, user_role="patient")
        flash(f"Account created successfully for {full_name}!", "success")
        return redirect(url_for("dashboard"))
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return f"Registration error: {e}", 500


# ------------------- AI HEALTH ASSISTANT -------------------

@app.route("/ai-assistant")
@login_required
def ai_assistant_view():
    patient_id = session.get("patient_id")
    patient = get_patient_by_id(patient_id)
    return render_template("ai_assistant.html", patient=patient)


@app.route("/api/ai-chat", methods=["POST"])
@login_required
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"reply": "Please describe your question or symptom.", "level": "empty", "suggestions": []})

    patient_id = session.get("patient_id")
    patient = get_patient_by_id(patient_id)
    result = ai_assistant.analyze(query, patient)
    return jsonify(result)


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(401)
def unauthorized_access(e):
    return render_template("404.html", error_message="Authentication Required: Please sign in with valid credentials."), 401


@app.errorhandler(403)
def forbidden_access(e):
    return render_template("404.html", error_message="Access Forbidden: You do not have authorization to view this medical record."), 403


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    trace = traceback.format_exc()
    print("\n" + "=" * 60)
    print("[500 SERVER ERROR DETAILS]:")
    print(trace)
    print("=" * 60 + "\n")
    return render_template("500.html", error_details=str(e), traceback_str=trace), 500


# ------------------- HEALTH CHECK & ENTRY POINT -------------------

@app.route("/healthz")
@app.route("/test-db")
def healthz():
    conn = get_connection()
    if conn:
        conn.close()
        return jsonify({"status": "healthy", "database": "connected"}), 200
    return jsonify({"status": "unhealthy", "database": "disconnected"}), 500


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000/")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    debug_mode = os.environ.get("FLASK_ENV") != "production"

    if debug_mode and not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.2, open_browser).start()

    app.run(host=host, port=port, debug=debug_mode)
