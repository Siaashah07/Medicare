import hashlib
import os
import secrets
import string
from datetime import datetime, timedelta
from functools import wraps
from flask import abort, jsonify, redirect, request, session, url_for, flash, render_template
from werkzeug.security import generate_password_hash, check_password_hash

# ----------------- PASSWORD SECURITY -----------------

def hash_password(password: str) -> str:
    """Hash password using Werkzeug's secure hashing algorithm."""
    if not password:
        return ""
    return generate_password_hash(password)

def verify_password(plain_password: str, stored_hash: str) -> tuple[bool, bool]:
    """
    Verify password against stored hash.
    Supports backwards compatibility for legacy plaintext during migration.
    Returns: (is_valid: bool, needs_rehash: bool)
    """
    if not plain_password or not stored_hash:
        return False, False

    # Check if stored_hash is a valid werkzeug hash (e.g. scrypt: or pbkdf2:)
    if stored_hash.startswith(("scrypt:", "pbkdf2:")):
        try:
            valid = check_password_hash(stored_hash, plain_password)
            return valid, False
        except Exception:
            return False, False

    # Fallback comparison for legacy plaintext passwords
    is_plain_match = secrets.compare_digest(plain_password, stored_hash)
    if is_plain_match:
        # Needs rehash to upgrade database to secure hash
        return True, True

    return False, False


# ----------------- ACCESS & VERIFICATION CODES -----------------

def generate_secure_code(length: int = 6) -> str:
    """Generate a cryptographically secure numeric verification code."""
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length))

def hash_code(code: str) -> str:
    """Generate a SHA-256 hash of a verification code for secure database storage."""
    if not code:
        return ""
    salt = os.environ.get("CODE_SALT", "medicare_salt_2026")
    return hashlib.sha256(f"{salt}:{code.strip()}".encode("utf-8")).hexdigest()

def verify_code(entered_code: str, stored_hash: str) -> bool:
    """Verify an entered code against its stored SHA-256 hash using constant-time comparison."""
    if not entered_code or not stored_hash:
        return False
    computed = hash_code(entered_code)
    return secrets.compare_digest(computed, stored_hash)


# ----------------- RATE LIMITING & LOCKOUT -----------------

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

def is_account_locked(failed_attempts: int, locked_until) -> tuple[bool, int]:
    """
    Check if an account is currently locked out.
    Returns (is_locked: bool, remaining_minutes: int).
    """
    if not locked_until:
        return False, 0

    now = datetime.now()
    if isinstance(locked_until, str):
        try:
            locked_until = datetime.fromisoformat(locked_until.replace("Z", ""))
        except Exception:
            return False, 0

    if now < locked_until:
        remaining_seconds = (locked_until - now).total_seconds()
        remaining_minutes = max(1, int(remaining_seconds // 60) + 1)
        return True, remaining_minutes

    return False, 0

def calculate_lockout_time() -> datetime:
    """Calculate the expiration time for a new account lockout."""
    return datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)


# ----------------- AUDIT LOGGING -----------------

def log_audit_event(user_id=None, role="system", action="SECURITY_EVENT", status="SUCCESS", details=None):
    """
    Safely record security-critical events (logins, failed attempts, access code requests).
    Does not crash if database is temporarily unavailable.
    """
    from db import get_connection
    ip_addr = request.remote_addr if request else "127.0.0.1"
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_logs (user_id, user_role, action, ip_address, status, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, role, action, ip_addr, status, str(details or "")[:500]))
            conn.commit()
            cursor.close()
            conn.close()
    except Exception as e:
        print(f"[!] Audit log write failure: {e}")


# ----------------- AUTHORIZATION DECORATORS -----------------

def login_required(f):
    """Ensure user has an active authenticated session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"success": False, "error": "Authentication required. Please log in."}), 401
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    """Ensure authenticated user holds one of the specified roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("logged_in"):
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify({"success": False, "error": "Authentication required."}), 401
                flash("Authentication required.", "error")
                return redirect(url_for("login"))

            user_role = session.get("role")
            # Allow access if user's role is in the allowed list, or if user is an admin
            if user_role not in allowed_roles and user_role != "admin":
                log_audit_event(
                    user_id=session.get("user_id") or session.get("patient_id"),
                    role=user_role,
                    action="UNAUTHORIZED_ROLE_ACCESS",
                    status="BLOCKED",
                    details=f"Attempted to access {request.path} requiring roles: {allowed_roles}"
                )
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify({"success": False, "error": "Forbidden: Insufficient permissions."}), 403
                return render_template("404.html"), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def verify_patient_access(target_patient_id: int) -> bool:
    """
    Verify whether the currently authenticated session is authorized to view or edit target_patient_id.
    - Role 'patient': only authorized if session['patient_id'] == target_patient_id
    - Role 'doctor': authorized to view/add records
    - Role 'authority': authorized for clinical oversight
    - Role 'admin': authorized
    """
    if not session.get("logged_in"):
        return False

    role = session.get("role")
    if role in ("doctor", "authority", "admin"):
        return True

    if role == "patient":
        current_p_id = session.get("patient_id")
        try:
            return int(current_p_id) == int(target_patient_id)
        except (ValueError, TypeError):
            return False

    return False
