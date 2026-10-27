"""
Medicare Database Connection Layer
Primary: PostgreSQL (Production / Render / Cloud)
Fallback: Local SQLite (Zero-dependency local dev / unit testing if PostgreSQL is unavailable)
"""

import os
import re
import sqlite3
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash

# Load environment variables from .env if available
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path)
except Exception:
    pass

# Try importing PostgreSQL driver
HAS_PSYCOPG2 = False
try:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import Error as PGError
    HAS_PSYCOPG2 = True
except ImportError:
    PGError = Exception


# ============================================================================
# SQLITE COMPATIBILITY WRAPPER (translates %s to ? and provides dict rows)
# ============================================================================
class SQLiteDictCursor:
    def __init__(self, sqlite_cursor):
        self.cursor = sqlite_cursor

    def execute(self, query, params=None):
        # Convert %s placeholders to ? for SQLite
        translated_query = re.sub(r'%s', '?', query)
        # Convert specific PG/MySQL expressions if needed
        translated_query = translated_query.replace('TIMESTAMPTZ', 'TIMESTAMP')
        translated_query = translated_query.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
        if params is None:
            return self.cursor.execute(translated_query)
        return self.cursor.execute(translated_query, params)

    def executemany(self, query, param_seq):
        translated_query = re.sub(r'%s', '?', query)
        return self.cursor.executemany(translated_query, param_seq)

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def close(self):
        self.cursor.close()


class SQLiteConnectionWrapper:
    """Wraps sqlite3.Connection to behave consistently with dictionary=True cursors."""
    def __init__(self, connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row

    def cursor(self, dictionary=True, buffered=True):
        cur = self.connection.cursor()
        return SQLiteDictCursor(cur)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


# ============================================================================
# POSTGRESQL CONNECTION WRAPPER
# ============================================================================
class PGCursorWrapper:
    """Wraps psycopg2 cursor to accept dictionary=True and provide .lastrowid."""
    def __init__(self, pg_cursor):
        self.cursor = pg_cursor
        self._last_id = None

    def execute(self, query, params=None):
        # If it's an INSERT into a table with id, append RETURNING id if not present to support lastrowid
        q_upper = query.strip().upper()
        if q_upper.startswith("INSERT INTO") and "RETURNING" not in q_upper:
            query = query.rstrip("; \t\n") + " RETURNING id;"
            res = self.cursor.execute(query, params)
            try:
                row = self.cursor.fetchone()
                if row and isinstance(row, dict) and "id" in row:
                    self._last_id = row["id"]
                elif row and hasattr(row, "__getitem__"):
                    self._last_id = row[0]
            except Exception:
                pass
            return res

        return self.cursor.execute(query, params)

    def executemany(self, query, params):
        return self.cursor.executemany(query, params)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        return self._last_id

    def close(self):
        self.cursor.close()


class PGConnectionWrapper:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self, dictionary=True, buffered=True):
        cur = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return PGCursorWrapper(cur)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


# ============================================================================
# DATABASE CONNECTION FACTORY
# ============================================================================
def get_db_url():
    """Retrieve full PostgreSQL connection URL or individual environment variables."""
    # Render provides DATABASE_URL
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Render sometimes uses postgres:// which psycopg2 expects as postgresql://
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        return db_url

    host = os.environ.get("PGHOST") or os.environ.get("DB_HOST")
    port = os.environ.get("PGPORT") or os.environ.get("DB_PORT") or "5432"
    dbname = os.environ.get("PGDATABASE") or os.environ.get("DB_NAME") or "medicare"
    user = os.environ.get("PGUSER") or os.environ.get("DB_USER") or "postgres"
    password = os.environ.get("PGPASSWORD") or os.environ.get("DB_PASSWORD") or ""

    if host:
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    return None


_PG_AVAILABLE = None

def get_connection():
    """
    Establish database connection.
    Attempts PostgreSQL first if configured. If PostgreSQL is unavailable or not running,
    gracefully connects to local SQLite fallback with matching dictionary-cursor interface.
    """
    global _PG_AVAILABLE
    db_url = get_db_url()

    # If DATABASE_URL is set (Render/Cloud) or PG is verified available
    if HAS_PSYCOPG2 and db_url and _PG_AVAILABLE is not False:
        try:
            raw_conn = psycopg2.connect(db_url, connect_timeout=1)
            _PG_AVAILABLE = True
            return PGConnectionWrapper(raw_conn)
        except Exception as e:
            _PG_AVAILABLE = False
            # Only print notice once
            if os.environ.get("FLASK_ENV") != "testing":
                print(f"[!] PostgreSQL connection notice ({e}). Falling back to local engine...")

    # Fallback to persistent SQLite database with WAL mode for concurrency
    sqlite_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "medicare_local.db")
    raw_sqlite = sqlite3.connect(sqlite_db_path, timeout=30, check_same_thread=False)
    raw_sqlite.execute("PRAGMA journal_mode=WAL;")
    raw_sqlite.execute("PRAGMA busy_timeout=15000;")
    wrapped = SQLiteConnectionWrapper(raw_sqlite)
    return wrapped


# ============================================================================
# SCHEMA INITIALIZATION & MIGRATIONS
# ============================================================================
def init_db(conn=None):
    """Ensure all required tables, constraints, and initial seed records exist."""
    close_when_done = False
    if conn is None:
        conn = get_connection()
        close_when_done = True

    cur = conn.cursor()

    # 1. Patients Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(150) NOT NULL,
            password VARCHAR(255) DEFAULT 'medicare123',
            password_hash VARCHAR(255) NULL,
            dob VARCHAR(50),
            age INT,
            gender VARCHAR(50),
            blood_group VARCHAR(20),
            marital_status VARCHAR(50),
            occupation VARCHAR(150),
            mobile VARCHAR(50) NOT NULL,
            alternate_mobile VARCHAR(50),
            email VARCHAR(150),
            address TEXT,
            city VARCHAR(100),
            state VARCHAR(100),
            pin_code VARCHAR(20),
            emergency_name VARCHAR(150),
            emergency_relationship VARCHAR(100),
            emergency_number VARCHAR(50),
            allergies TEXT,
            existing_conditions TEXT,
            current_medications TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Users Table (Role-based access: Doctor, Authority, Patient)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NULL,
            email VARCHAR(150) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL,
            full_name VARCHAR(150) NOT NULL,
            specialization VARCHAR(150) NULL,
            license_number VARCHAR(100) NULL,
            is_approved BOOLEAN DEFAULT TRUE,
            is_active BOOLEAN DEFAULT TRUE,
            failed_login_attempts INT DEFAULT 0,
            locked_until TIMESTAMP NULL,
            authority_code VARCHAR(100) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Verification Codes Table (Short-lived email login access codes)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS verification_codes (
            id SERIAL PRIMARY KEY,
            user_id INT NULL,
            email VARCHAR(150) NOT NULL,
            code_hash VARCHAR(255) NOT NULL,
            purpose VARCHAR(50) NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            is_used BOOLEAN DEFAULT FALSE,
            attempts INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. Doctor-Patient Assignments (Strict IDOR authorization mapping)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS doctor_patient_assignments (
            id SERIAL PRIMARY KEY,
            doctor_id INT NOT NULL,
            patient_id INT NOT NULL,
            assigned_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT NULL
        );
    """)

    # 5. Audit Logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            user_id INT NULL,
            user_role VARCHAR(50) NULL,
            action VARCHAR(120) NOT NULL,
            ip_address VARCHAR(50) NULL,
            details TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 6. Medical Records
    cur.execute("""
        CREATE TABLE IF NOT EXISTS medical_records (
            id SERIAL PRIMARY KEY,
            patient_id INT NOT NULL,
            record_type VARCHAR(100),
            title VARCHAR(200),
            doctor_name VARCHAR(150),
            hospital_name VARCHAR(200),
            record_date VARCHAR(50),
            description TEXT,
            attachment_name VARCHAR(255) DEFAULT 'Medical_Report.pdf',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 7. Family Medical History
    cur.execute("""
        CREATE TABLE IF NOT EXISTS family_history (
            id SERIAL PRIMARY KEY,
            patient_id INT NOT NULL,
            relative_name VARCHAR(150),
            relationship VARCHAR(100),
            condition_name VARCHAR(200),
            age_at_diagnosis INT,
            is_living VARCHAR(10) DEFAULT 'Yes',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 8. Genetic & Hereditary History
    cur.execute("""
        CREATE TABLE IF NOT EXISTS genetic_history (
            id SERIAL PRIMARY KEY,
            patient_id INT NOT NULL,
            condition_title VARCHAR(200),
            inheritance_pattern VARCHAR(100),
            affected_relatives TEXT,
            carrier_status VARCHAR(100),
            risk_level VARCHAR(50) DEFAULT 'Moderate',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()

    # Seed initial test accounts if empty
    seed_initial_accounts(conn)

    cur.close()
    if close_when_done:
        conn.close()


def seed_initial_accounts(conn):
    """Seed initial verified, approved accounts with secure password hashes."""
    cur = conn.cursor()

    # Seed Authority Account
    cur.execute("SELECT id FROM users WHERE email = %s", ("admin@medicare.io",))
    if not cur.fetchone():
        auth_pw_hash = generate_password_hash("AdminSecure@2026!")
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, full_name, is_approved, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, ("admin", "admin@medicare.io", auth_pw_hash, "authority", "Dr. Alexander Wright (Chief Medical Officer)", True, True))

    # Seed Doctor Account
    cur.execute("SELECT id FROM users WHERE email = %s", ("dr.ananya@medicare.io",))
    if not cur.fetchone():
        doc_pw_hash = generate_password_hash("DoctorSecure@2026!")
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, full_name, specialization, license_number, is_approved, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, ("dr_ananya", "dr.ananya@medicare.io", doc_pw_hash, "doctor", "Dr. Ananya Sen", "Cardiology", "MCI-CARD-9082", True, True))

    # Seed Sample Patient (Eleanor Vance)
    cur.execute("SELECT id FROM patients WHERE id = %s", (1,))
    if not cur.fetchone():
        patient_pw_hash = generate_password_hash("password123")
        cur.execute("""
            INSERT INTO patients (
                id, full_name, password, password_hash, dob, age, gender, blood_group, marital_status, occupation,
                mobile, alternate_mobile, email, address, city, state, pin_code, emergency_name, emergency_relationship, emergency_number,
                allergies, existing_conditions, current_medications
            ) VALUES (
                1, 'Eleanor Vance', 'password123', %s, '1994-08-14', 32, 'Female', 'O+', 'Married', 'Software Engineer',
                '+91 98765 43210', '+91 91234 56789', 'eleanor.vance@medicare.io', '42 Evergreen Heights, Sector 15', 'Bengaluru', 'Karnataka', '560001',
                'Thomas Vance', 'Spouse', '+91 99887 76655',
                'Penicillin (Moderate rash), Peanuts (Severe anaphylaxis risk)',
                'Mild Bronchial Asthma, Type-2 Diabetes (Controlled)',
                'Metformin 500mg (Daily), Salbutamol Inhaler (PRN / As needed)'
            )
        """, (patient_pw_hash,))

    # Ensure Doctor-Patient Assignment exists between Dr. Ananya and Patient 1
    cur.execute("SELECT id FROM users WHERE email = %s", ("dr.ananya@medicare.io",))
    doc_row = cur.fetchone()
    if doc_row:
        doc_id = doc_row["id"]
        cur.execute("SELECT id FROM doctor_patient_assignments WHERE doctor_id = %s AND patient_id = %s", (doc_id, 1))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO doctor_patient_assignments (doctor_id, patient_id, notes)
                VALUES (%s, %s, %s)
            """, (doc_id, 1, "Primary cardiologist for cardiovascular care and hypertension monitoring."))

    conn.commit()
    cur.close()
