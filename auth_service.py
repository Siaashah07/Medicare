"""
Medicare Authentication & Authorization Core Service
Implements multi-factor verification, rate limiting, secure password hashing,
and strict Role-Based Access Control (RBAC).
"""

import hashlib
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_connection
from mailer import send_verification_email


# ============================================================================
# AUDIT LOGGING
# ============================================================================
def log_audit_event(action, user_id=None, user_role=None, ip_address=None, details=None):
    """Safely record security-sensitive events in audit_logs."""
    conn = get_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_logs (user_id, user_role, action, ip_address, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, user_role, action, ip_address, details))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[!] Audit logging error: {e}")
        try:
            conn.close()
        except Exception:
            pass


# ============================================================================
# VERIFICATION CODES (Doctor & Authority Portals)
# ============================================================================
def generate_and_dispatch_code(user, purpose):
    """
    Generate a cryptographically secure 6-digit access code.
    Stores the SHA-256 hash in database with a 10-minute expiration.
    Dispatches the code to user's registered email.
    Returns (success: bool, error_message: str).
    """
    conn = get_connection()
    if not conn:
        return False, "Database connection unavailable."

    # Invalidate previous unused codes for this user & purpose
    cur = conn.cursor()
    cur.execute("""
        UPDATE verification_codes 
        SET is_used = TRUE 
        WHERE email = %s AND purpose = %s AND is_used = FALSE
    """, (user["email"], purpose))

    # Generate 6-digit random code
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Insert new code record
    cur.execute("""
        INSERT INTO verification_codes (user_id, email, code_hash, purpose, expires_at, is_used, attempts)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user.get("id"), user["email"], code_hash, purpose, expires_at.strftime("%Y-%m-%d %H:%M:%S"), False, 0))
    conn.commit()
    cur.close()
    conn.close()

    # Send code to registered email
    sent, msg = send_verification_email(
        recipient_email=user["email"],
        code=code,
        purpose_label=purpose,
        recipient_name=user.get("full_name") or "Medical User"
    )

    log_audit_event(
        action=f"VERIFICATION_CODE_GENERATED:{purpose}",
        user_id=user.get("id"),
        user_role=user.get("role"),
        details=f"Email delivery status: {sent} ({msg})"
    )

    return sent, msg


def verify_submitted_code(email, raw_code, purpose):
    """
    Validate a submitted verification code against stored SHA-256 hash.
    Enforces expiration, single-use, and attempt limiting (max 5 attempts).
    Returns (valid: bool, error_reason: str).
    """
    if not raw_code or len(raw_code.strip()) != 6:
        return False, "Please enter a valid 6-digit verification code."

    conn = get_connection()
    if not conn:
        return False, "Database unavailable."

    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM verification_codes
        WHERE email = %s AND purpose = %s AND is_used = FALSE
        ORDER BY id DESC LIMIT 1
    """, (email, purpose))
    record = cur.fetchone()

    if not record:
        cur.close()
        conn.close()
        return False, "No active verification code found or code has already been used. Please request a new code."

    # Check attempt limit
    attempts = record.get("attempts", 0) + 1
    if attempts > 5:
        cur.execute("UPDATE verification_codes SET is_used = TRUE WHERE id = %s", (record["id"],))
        conn.commit()
        cur.close()
        conn.close()
        return False, "Too many failed code attempts. This code has been invalidated for security. Please request a new code."

    cur.execute("UPDATE verification_codes SET attempts = %s WHERE id = %s", (attempts, record["id"]))
    conn.commit()

    # Check expiration
    expires_at_val = record.get("expires_at")
    if isinstance(expires_at_val, str):
        try:
            expires_dt = datetime.strptime(expires_at_val.split(".")[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            expires_dt = datetime.now(timezone.utc) + timedelta(minutes=1)
    elif isinstance(expires_at_val, datetime):
        expires_dt = expires_at_val if expires_at_val.tzinfo else expires_at_val.replace(tzinfo=timezone.utc)
    else:
        expires_dt = datetime.now(timezone.utc)

    if datetime.now(timezone.utc) > expires_dt:
        cur.execute("UPDATE verification_codes SET is_used = TRUE WHERE id = %s", (record["id"],))
        conn.commit()
        cur.close()
        conn.close()
        return False, "Verification code has expired. Please request a new code."

    # Compare hashes constant-time
    submitted_hash = hashlib.sha256(raw_code.strip().encode("utf-8")).hexdigest()
    if not secrets.compare_digest(record["code_hash"], submitted_hash):
        cur.close()
        conn.close()
        remaining = 5 - attempts
        return False, f"Incorrect verification code. ({remaining} attempts remaining before code expires)."

    # Code is valid - mark as used immediately
    cur.execute("UPDATE verification_codes SET is_used = TRUE WHERE id = %s", (record["id"],))
    conn.commit()
    cur.close()
    conn.close()
    return True, "Code successfully verified."


# ============================================================================
# ACCOUNT AUTHENTICATION & LOCKOUT
# ============================================================================
def check_user_lockout(user):
    """Check if account is temporarily locked due to repeated failed attempts."""
    locked_until = user.get("locked_until")
    if not locked_until:
        return False, None

    if isinstance(locked_until, str):
        try:
            lock_dt = datetime.strptime(locked_until.split(".")[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return False, None
    elif isinstance(locked_until, datetime):
        lock_dt = locked_until if locked_until.tzinfo else locked_until.replace(tzinfo=timezone.utc)
    else:
        return False, None

    now = datetime.now(timezone.utc)
    if now < lock_dt:
        minutes_left = int((lock_dt - now).total_seconds() // 60) + 1
        return True, f"Account is temporarily locked due to excessive failed attempts. Please try again in {minutes_left} minute(s)."

    return False, None


def record_failed_login(user_id, table="users"):
    """Increment failed login attempts and trigger 15-minute lockout if attempts >= 5."""
    conn = get_connection()
    if not conn:
        return
    cur = conn.cursor()
    cur.execute(f"SELECT failed_login_attempts FROM {table} WHERE id = %s", (user_id,))
    row = cur.fetchone()
    current_fails = (row.get("failed_login_attempts", 0) if row else 0) + 1

    if current_fails >= 5:
        lock_time = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(f"UPDATE {table} SET failed_login_attempts = %s, locked_until = %s WHERE id = %s", (current_fails, lock_time, user_id))
    else:
        cur.execute(f"UPDATE {table} SET failed_login_attempts = %s WHERE id = %s", (current_fails, user_id))
    conn.commit()
    cur.close()
    conn.close()


def reset_failed_login(user_id, table="users"):
    """Clear failed login attempts upon successful authentication."""
    conn = get_connection()
    if not conn:
        return
    cur = conn.cursor()
    cur.execute(f"UPDATE {table} SET failed_login_attempts = 0, locked_until = NULL WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def authenticate_user_credentials(email, password, required_role):
    """
    Authenticate email & password for Doctor or Authority users.
    Returns (user_dict or None, error_message or None).
    """
    conn = get_connection()
    if not conn:
        return None, "Database connection error."

    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email.strip().lower(),))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if not user:
        return None, "Invalid email address or password."

    # Verify role
    if user.get("role") != required_role and not (required_role == "authority" and user.get("role") == "admin"):
        return None, f"Unauthorized: Account does not have {required_role} credentials."

    # Check approval status
    if not user.get("is_approved", True):
        return None, "Your account is pending administrative verification. Please contact Hospital Administration."

    # Check active status
    if not user.get("is_active", True):
        return None, "Your account has been deactivated. Please contact the security administrator."

    # Check lockout
    is_locked, lock_msg = check_user_lockout(user)
    if is_locked:
        return None, lock_msg

    # Verify password hash
    stored_hash = user.get("password_hash")
    valid_password = False

    if stored_hash and check_password_hash(stored_hash, password):
        valid_password = True
    elif user.get("password") and user.get("password") == password:
        # Transparently upgrade legacy plaintext password to secure hash
        valid_password = True
        new_hash = generate_password_hash(password)
        conn = get_connection()
        if conn:
            c = conn.cursor()
            c.execute("UPDATE users SET password_hash = %s, password = NULL WHERE id = %s", (new_hash, user["id"]))
            conn.commit()
            c.close()
            conn.close()

    if not valid_password:
        record_failed_login(user["id"], table="users")
        log_audit_event("FAILED_LOGIN_PASSWORD", user_id=user["id"], user_role=user.get("role"))
        return None, "Invalid email address or password."

    return user, None


# ============================================================================
# AUTHORIZATION & PATIENT DATA ACCESS PERMISSIONS
# ============================================================================
def can_doctor_access_patient(doctor_id, patient_id):
    """Verify if doctor is authorized to view this specific patient's records."""
    if not doctor_id or not patient_id:
        return False

    conn = get_connection()
    if not conn:
        return False

    cur = conn.cursor()
    # Check assignment table
    cur.execute("""
        SELECT id FROM doctor_patient_assignments 
        WHERE doctor_id = %s AND patient_id = %s
    """, (doctor_id, patient_id))
    assignment = cur.fetchone()

    # Also check if doctor has treated the patient in medical_records
    if not assignment:
        cur.execute("""
            SELECT id FROM medical_records
            WHERE patient_id = %s AND doctor_name LIKE %s
        """, (patient_id, f"%{doctor_id}%"))
        treated = cur.fetchone()
        cur.close()
        conn.close()
        return bool(treated)

    cur.close()
    conn.close()
    return bool(assignment)


def can_user_access_patient(session, requested_patient_id):
    """
    Strict authorization matrix:
    1. Unauthenticated: FALSE (401)
    2. Patient: TRUE only if session['patient_id'] == requested_patient_id (Prevents IDOR)
    3. Doctor: TRUE only if assigned to doctor
    4. Authority: TRUE (Audit monitored)
    """
    if not session.get("logged_in"):
        return False, "Unauthenticated access. Please sign in.", 401

    role = session.get("role")
    
    if role == "authority":
        return True, "Authorized as Hospital Authority.", 200

    if role == "patient":
        user_p_id = session.get("patient_id")
        if user_p_id and int(user_p_id) == int(requested_patient_id):
            return True, "Authorized patient access.", 200
        return False, "Forbidden: Patients can only access their own medical records.", 403

    if role == "doctor":
        doc_id = session.get("user_id")
        if can_doctor_access_patient(doc_id, requested_patient_id):
            return True, "Authorized assigned doctor access.", 200
        return False, "Forbidden: Doctor is not assigned to this patient's medical profile.", 403

    return False, "Unauthorized role.", 403
