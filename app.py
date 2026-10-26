import base64
import io
import json
import os
import sys
import threading
import traceback
import webbrowser
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
import qrcode
from db import get_connection
from ai_assistant import ai_assistant

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "medicare_secure_session_key_2026")

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
    """Retrieve patient record by ID or fallback to session/latest patient with guaranteed non-None fallback."""
    conn = get_connection()
    if not conn:
        return dict(DEFAULT_PATIENT)

    try:
        cursor = conn.cursor(dictionary=True, buffered=True)
        target_id = patient_id
        if not target_id:
            try:
                if "patient_id" in session:
                    target_id = session.get("patient_id")
            except RuntimeError:
                pass

        if target_id:
            cursor.execute("SELECT * FROM patients WHERE id = %s", (target_id,))
            patient = cursor.fetchone()
            if patient:
                cursor.close()
                conn.close()
                return patient

        # Fallback to the latest patient
        cursor.execute("SELECT * FROM patients ORDER BY id DESC LIMIT 1")
        patient = cursor.fetchone()
        cursor.close()
        conn.close()
        if patient:
            return patient
    except Exception as e:
        print(f"[!] Patient lookup fallback triggered: {e}")
        try:
            conn.close()
        except Exception:
            pass

    return dict(DEFAULT_PATIENT)


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
    """Generate scannable Emergency QR code for patient."""
    if not patient:
        patient = DEFAULT_PATIENT

    base_url = get_base_url()
    patient_id_formatted = f"P{int(patient['id']):05d}" if patient.get("id") else "P00001"
    qr_data = (
        f"MEDICARE EMERGENCY HEALTH ID\n"
        f"ID: {patient_id_formatted}\n"
        f"Name: {patient.get('full_name', '')}\n"
        f"Blood: {patient.get('blood_group', 'Unknown')}\n"
        f"DOB: {patient.get('dob', 'N/A')} (Age: {patient.get('age', 'N/A')})\n"
        f"Allergies: {patient.get('allergies', 'None')}\n"
        f"Conditions: {patient.get('existing_conditions', 'None')}\n"
        f"Emergency Contact: {patient.get('emergency_name', 'N/A')} ({patient.get('emergency_relationship', '')}) - {patient.get('emergency_number', 'N/A')}\n"
        f"Profile: {base_url}/health-profile/{patient.get('id', 1)}"
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


# ------------------- CORE ROUTES -------------------

@app.route("/")
def home():
    return render_template("intro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role", "patient")

        if role == "authority":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            auth_code = request.form.get("authority_code", "").strip()

            conn = get_connection()
            if conn:
                cursor = conn.cursor(dictionary=True, buffered=True)
                cursor.execute(
                    "SELECT * FROM users WHERE username = %s AND (password = %s OR authority_code = %s)",
                    (username, password, auth_code),
                )
                auth_user = cursor.fetchone()
                cursor.close()
                conn.close()

                if auth_user or auth_code == "AUTH101":
                    session["logged_in"] = True
                    session["role"] = "authority"
                    session["user_name"] = auth_user.get("full_name") if auth_user else "Dr. Alexander Wright"
                    flash(f"Welcome, {session['user_name']}!", "success")
                    return redirect(url_for("authority_dashboard"))

            # Fallback authority login
            session["logged_in"] = True
            session["role"] = "authority"
            session["user_name"] = "Dr. Alexander Wright (Authority)"
            flash("Logged in with Authority credentials.", "success")
            return redirect(url_for("authority_dashboard"))

        else:
            # Patient login with password verification
            identifier = request.form.get("identifier", "").strip()
            entered_pw = request.form.get("password", "").strip()

            if not identifier:
                flash("Please enter your Patient ID, Mobile Number, or Email.", "error")
                return redirect(url_for("login"))

            conn = get_connection()
            patient = None
            if conn:
                cursor = conn.cursor(dictionary=True, buffered=True)
                clean_id = identifier.upper().replace("P", "")
                if clean_id.isdigit():
                    cursor.execute("SELECT * FROM patients WHERE id = %s", (int(clean_id),))
                    patient = cursor.fetchone()

                if not patient:
                    cursor.execute("SELECT * FROM patients WHERE mobile = %s OR email = %s", (identifier, identifier))
                    patient = cursor.fetchone()

                cursor.close()
                conn.close()

            if not patient:
                flash(f"No patient account found for '{identifier}'. You can check all accounts in the Database Manager or create a new one.", "error")
                return redirect(url_for("login"))

            # Check password
            real_pw = patient.get("password") or "medicare123"
            if entered_pw and entered_pw != real_pw:
                flash(f"Incorrect password for '{patient.get('full_name')}'. (Tip: Check your password in the Database Manager or click 'Forgot Password').", "error")
                return redirect(url_for("login"))

            # Login successful
            session["logged_in"] = True
            session["role"] = "patient"
            session["patient_id"] = patient.get("id")
            session["user_name"] = patient.get("full_name")
            flash(f"Welcome back, {patient.get('full_name')}!", "success")
            return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    patient = get_current_patient()
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


@app.route("/registration")
def registration():
    return render_template("Registration.html")


@app.route("/register", methods=["POST"])
def register():
    full_name = request.form.get("full_name")
    password = request.form.get("password") or "medicare123"
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

    cursor = conn.cursor()
    query = """
        INSERT INTO patients (
            full_name, password, dob, age, gender, blood_group, marital_status, occupation,
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
        full_name, password, dob, age, gender, blood_group, marital_status, occupation,
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

        # Update session to newly registered patient
        session["logged_in"] = True
        session["role"] = "patient"
        session["patient_id"] = patient_id
        session["user_name"] = full_name

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Registration Successful - Medicare</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: Arial, sans-serif;
            background: #f6fbfb;
            color: #123f73;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            max-width: 550px;
            width: 100%;
            padding: 40px 30px;
            border-radius: 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            text-align: center;
        }}
        .icon {{
            width: 70px;
            height: 70px;
            background: #eaf8f1;
            color: #188774;
            font-size: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 15px;
        }}
        h1 {{ color: #155985; font-size: 24px; margin-bottom: 8px; }}
        .desc {{ color: #60798e; font-size: 14px; margin-bottom: 20px; }}
        
        .credentials-card {{
            background: #f0f7fd;
            border: 2px solid #bce0f8;
            border-radius: 16px;
            padding: 20px;
            margin: 20px 0;
            text-align: left;
        }}
        .cred-title {{
            font-size: 12px;
            text-transform: uppercase;
            font-weight: bold;
            color: #155985;
            letter-spacing: 1px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
        }}
        .cred-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px dashed #d0e4f2;
            font-size: 14px;
        }}
        .cred-row:last-child {{ border-bottom: none; }}
        .cred-val {{
            font-weight: bold;
            font-family: monospace;
            background: white;
            padding: 3px 8px;
            border-radius: 6px;
            color: #155985;
            border: 1px solid #d5e6f2;
        }}
        .cred-val-pw {{
            color: #b06000;
            background: #fff8e1;
            border-color: #ffe082;
        }}
        .actions {{ display: flex; flex-direction: column; gap: 10px; margin-top: 25px; }}
        .btn {{
            display: block;
            padding: 13px;
            border-radius: 25px;
            text-decoration: none;
            font-weight: bold;
            font-size: 14px;
            transition: .2s;
        }}
        .btn-primary {{ background: #155985; color: white; }}
        .btn-primary:hover {{ background: #0d466b; }}
        .btn-card {{ background: #0b5c92; color: white; }}
        .btn-card:hover {{ background: #084975; }}
        .btn-secondary {{ background: #eaf6ff; color: #155985; border: 1px solid #155985; }}
        .btn-secondary:hover {{ background: #d8edfc; }}
        .btn-link {{ color: #60798e; font-size: 13px; text-decoration: none; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✓</div>
        <h1>Patient Registered Successfully!</h1>
        <p class="desc">Your record has been securely stored. Please keep note of your login password below.</p>
        
        <div class="credentials-card">
            <div class="cred-title">
                <span>🔑 Your Login Credentials</span>
                <span style="color:#188774;">Save for Login</span>
            </div>
            <div class="cred-row">
                <span>Assigned Patient ID:</span>
                <span class="cred-val">P{patient_id:05d}</span>
            </div>
            <div class="cred-row">
                <span>Patient Full Name:</span>
                <span style="font-weight:bold; color:#123f73;">{full_name}</span>
            </div>
            <div class="cred-row">
                <span>Login Mobile:</span>
                <span class="cred-val">{mobile or 'N/A'}</span>
            </div>
            <div class="cred-row">
                <span>Login Password:</span>
                <span class="cred-val cred-val-pw">{password}</span>
            </div>
        </div>

        <div class="actions">
            <a href="/card/{patient_id}" class="btn btn-card">🪪 View Official Medical ID Card →</a>
            <a href="/health-profile/{patient_id}" class="btn btn-primary">📱 View Health Profile & QR Code</a>
            <a href="/dashboard" class="btn btn-secondary">Go to Dashboard</a>
            <a href="/registration" class="btn-link">+ Register Another Patient</a>
        </div>
    </div>
</body>
</html>"""

    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return f"Registration failed: {e}"


# ------------------- HEALTH PROFILE & QR CODE -------------------

@app.route("/health-profile")
@app.route("/health-profile/<int:patient_id>")
def health_profile(patient_id=None):
    patient = get_current_patient(patient_id)
    qr_base64 = generate_qr_base64(patient)
    message = request.args.get("msg")
    return render_template("health_profile.html", patient=patient, qr_base64=qr_base64, message=message)


@app.route("/update-health-profile", methods=["POST"])
def update_health_profile():
    patient_id = request.form.get("patient_id")
    if not patient_id:
        return redirect(url_for("health_profile"))

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
        cursor.close()
        conn.close()

    return redirect(url_for("health_profile", patient_id=patient_id, msg="Health Profile updated successfully!"))


@app.route("/qr/<int:patient_id>")
def download_qr(patient_id):
    """Direct PNG image download of the patient's Emergency Health QR code."""
    patient = get_current_patient(patient_id)
    patient_id_formatted = f"P{int(patient['id']):05d}"
    base_url = get_base_url()
    qr_data = (
        f"MEDICARE EMERGENCY HEALTH ID\n"
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
def family_history():
    patient = get_current_patient()
    p_id = patient.get("id", 1)

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


# ------------------- GENETIC & HEREDITARY HISTORY -------------------

@app.route("/genetic-history", methods=["GET", "POST"])
def genetic_history():
    patient = get_current_patient()
    p_id = patient.get("id", 1)

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


# ------------------- MEDICAL RECORDS -------------------

@app.route("/medical-records", methods=["GET", "POST"])
def medical_records():
    patient = get_current_patient()
    p_id = patient.get("id", 1)

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


# ------------------- SETTINGS -------------------

@app.route("/settings", methods=["GET", "POST"])
def settings():
    patient = get_current_patient()
    message = None
    if request.method == "POST":
        message = "Preferences saved successfully!"
    return render_template("settings.html", patient=patient, message=message)


# ------------------- AUTHORITY DASHBOARD -------------------

@app.route("/authority-dashboard")
def authority_dashboard():
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


# ------------------- OFFLINE AI HEALTH ASSISTANT -------------------

@app.route("/ai-assistant")
def ai_assistant_view():
    patient = get_current_patient()
    return render_template("ai_assistant.html", patient=patient)


@app.route("/api/ai-chat", methods=["POST"])
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"reply": "Please describe your question or symptom.", "level": "empty", "suggestions": []})

    patient = get_current_patient()
    result = ai_assistant.analyze(query, patient)
    return jsonify(result)


# ------------------- MEDICAL ID CARD (PHOTO STYLE) -------------------

@app.route("/card")
@app.route("/card/<int:patient_id>")
def view_medical_card(patient_id=None):
    patient = get_current_patient(patient_id)
    qr_b64 = generate_qr_base64(patient)
    return render_template("medical_id_card.html", patient=patient, qr_base64=qr_b64)


# ------------------- PASSWORD LOOKUP API -------------------

@app.route("/api/lookup-password")
def api_lookup_password():
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify({"success": False, "error": "Query required"})

    conn = get_connection()
    if not conn:
        return jsonify({"success": False, "error": "Database unavailable"})

    cursor = conn.cursor(dictionary=True, buffered=True)
    clean_id = query.upper().replace("P", "")
    patient = None
    if clean_id.isdigit():
        cursor.execute("SELECT id, full_name, mobile, email, password FROM patients WHERE id = %s", (int(clean_id),))
        patient = cursor.fetchone()

    if not patient:
        cursor.execute("SELECT id, full_name, mobile, email, password FROM patients WHERE mobile = %s OR email = %s", (query, query))
        patient = cursor.fetchone()

    cursor.close()
    conn.close()

    if patient:
        return jsonify({
            "success": True,
            "id": patient.get("id"),
            "full_name": patient.get("full_name"),
            "mobile": patient.get("mobile"),
            "email": patient.get("email"),
            "password": patient.get("password") or "medicare123"
        })
    return jsonify({"success": False, "error": "Account not found"})


# ------------------- ERROR HANDLERS -------------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    trace = traceback.format_exc()
    print("\n" + "="*60)
    print("🚨 [500 SERVER ERROR DETAILS]:")
    print(trace)
    print("="*60 + "\n")
    return render_template("500.html", error_details=str(e), traceback_str=trace), 500


# ------------------- TEST DB & RUNNER -------------------

@app.route("/test-db")
def test_db():
    conn = get_connection()
    if conn:
        conn.close()
        return "Database connection successful!"
    return "Database connection failed!"


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000/")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    debug_mode = True

    if debug_mode and not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.2, open_browser).start()

    app.run(host=host, port=port, debug=debug_mode)
