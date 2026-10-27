import os
import sqlite3
import re
from urllib.parse import urlparse

# Load environment variables from .env
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path)
except Exception:
    pass

# Import MySQL connector
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    mysql = None
    MySQLError = Exception


class SQLiteCursorAdapter:
    """Adapts an SQLite cursor to emulate mysql-connector dictionary & buffered behavior."""
    def __init__(self, cursor, as_dict=False):
        self._cursor = cursor
        self.as_dict = as_dict
        self.lastrowid = None
        self.rowcount = -1

    def execute(self, query, params=None):
        # Convert %s placeholder used in MySQL queries to SQLite ? placeholder
        sqlite_query = query.replace("%s", "?")
        if params is None:
            self._cursor.execute(sqlite_query)
        else:
            self._cursor.execute(sqlite_query, params)
        self.lastrowid = self._cursor.lastrowid
        self.rowcount = self._cursor.rowcount
        return self

    def executemany(self, query, param_seq):
        sqlite_query = query.replace("%s", "?")
        self._cursor.executemany(sqlite_query, param_seq)
        self.rowcount = self._cursor.rowcount
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self.as_dict:
            cols = [d[0] for d in self._cursor.description]
            return dict(zip(cols, row))
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        if self.as_dict:
            cols = [d[0] for d in self._cursor.description]
            return [dict(zip(cols, r)) for r in rows]
        return rows

    def close(self):
        self._cursor.close()

    @property
    def description(self):
        return self._cursor.description


class SQLiteConnectionAdapter:
    """Wraps an SQLite connection to provide an interface identical to mysql-connector."""
    def __init__(self, db_path):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def cursor(self, dictionary=False, buffered=False):
        raw_cursor = self._conn.cursor()
        return SQLiteCursorAdapter(raw_cursor, as_dict=dictionary)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def is_connected(self):
        return True


def get_db_config():
    """Retrieve database connection settings from environment variables with safe defaults."""
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("MYSQL_URL") or os.environ.get("JAWSDB_URL")
    if db_url and "mysql" in db_url:
        try:
            parsed = urlparse(db_url)
            return {
                "host": parsed.hostname or "127.0.0.1",
                "port": parsed.port or 3306,
                "user": parsed.username or "root",
                "password": parsed.password or "",
                "database": parsed.path.lstrip("/") or "medicare"
            }
        except Exception:
            pass

    host = os.environ.get("DB_HOST") or os.environ.get("MYSQL_HOST") or os.environ.get("MYSQLHOST") or "127.0.0.1"
    port_str = os.environ.get("DB_PORT") or os.environ.get("MYSQL_PORT") or os.environ.get("MYSQLPORT") or "3306"
    try:
        port = int(port_str)
    except ValueError:
        port = 3306

    user = os.environ.get("DB_USER") or os.environ.get("MYSQL_USER") or os.environ.get("MYSQLUSER") or "root"
    password = os.environ.get("DB_PASSWORD") or os.environ.get("MYSQL_PASSWORD") or os.environ.get("MYSQLPASSWORD") or ""
    database = os.environ.get("DB_NAME") or os.environ.get("MYSQL_DB") or os.environ.get("MYSQLDATABASE") or "medicare"

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database
    }


def get_connection():
    """
    Connect to the primary MySQL database using environment configuration.
    Falls back gracefully to SQLite when MySQL is not available or unreachable.
    """
    # 1. Attempt MySQL connection
    if mysql is not None:
        cfg = get_db_config()
        try:
            conn = mysql.connector.connect(
                host=cfg["host"],
                port=cfg["port"],
                user=cfg["user"],
                password=cfg["password"],
                database=cfg["database"],
                autocommit=False,
                connect_timeout=3
            )
            return conn
        except MySQLError as err:
            # Auto-create database if unknown database (errno 1049)
            if getattr(err, "errno", None) == 1049:
                try:
                    temp_conn = mysql.connector.connect(
                        host=cfg["host"],
                        port=cfg["port"],
                        user=cfg["user"],
                        password=cfg["password"],
                        connect_timeout=3
                    )
                    cur = temp_conn.cursor()
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                    cur.close()
                    temp_conn.close()

                    conn = mysql.connector.connect(
                        host=cfg["host"],
                        port=cfg["port"],
                        user=cfg["user"],
                        password=cfg["password"],
                        database=cfg["database"],
                        connect_timeout=3
                    )
                    init_db(conn)
                    return conn
                except Exception:
                    pass
            pass
        except Exception:
            pass

    # 2. Resilient SQLite fallback
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "medicare.db")
    conn = SQLiteConnectionAdapter(db_path)
    init_db(conn)
    return conn


def upgrade_schema(connection):
    """Safely apply non-destructive schema migrations to add security columns without deleting data."""
    cursor = connection.cursor()
    is_sqlite = isinstance(connection, SQLiteConnectionAdapter)

    def add_col_if_missing(table, column, col_def_mysql, col_def_sqlite):
        try:
            if is_sqlite:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cursor.fetchall()]
                if column not in cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def_sqlite}")
                    connection.commit()
            else:
                cursor.execute(f"""
                    SELECT COUNT(*) FROM information_schema.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}' AND COLUMN_NAME = '{column}'
                """)
                count = cursor.fetchone()[0]
                if count == 0:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def_mysql}")
                    connection.commit()
        except Exception:
            pass

    # 1. Enhance users table
    add_col_if_missing("users", "email", "VARCHAR(255) NULL", "TEXT")
    add_col_if_missing("users", "password_hash", "VARCHAR(255) NULL", "TEXT")
    add_col_if_missing("users", "is_approved", "TINYINT(1) DEFAULT 0", "INTEGER DEFAULT 0")
    add_col_if_missing("users", "is_active", "TINYINT(1) DEFAULT 1", "INTEGER DEFAULT 1")
    add_col_if_missing("users", "is_email_verified", "TINYINT(1) DEFAULT 0", "INTEGER DEFAULT 0")
    add_col_if_missing("users", "access_code_hash", "VARCHAR(255) NULL", "TEXT")
    add_col_if_missing("users", "code_expires_at", "DATETIME NULL", "TEXT")
    add_col_if_missing("users", "code_used", "TINYINT(1) DEFAULT 0", "INTEGER DEFAULT 0")
    add_col_if_missing("users", "failed_login_attempts", "INT DEFAULT 0", "INTEGER DEFAULT 0")
    add_col_if_missing("users", "locked_until", "DATETIME NULL", "TEXT")
    add_col_if_missing("users", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "TEXT")

    # 2. Enhance patients table
    add_col_if_missing("patients", "password_hash", "VARCHAR(255) NULL", "TEXT")
    add_col_if_missing("patients", "failed_login_attempts", "INT DEFAULT 0", "INTEGER DEFAULT 0")
    add_col_if_missing("patients", "locked_until", "DATETIME NULL", "TEXT")

    cursor.close()


def init_db(connection=None):
    """Ensure all required tables, security columns, and approved staff accounts exist."""
    close_when_done = False
    if connection is None:
        connection = get_connection()
        close_when_done = True

    cursor = connection.cursor()
    is_sqlite = isinstance(connection, SQLiteConnectionAdapter)

    auto_inc = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "INT AUTO_INCREMENT PRIMARY KEY"
    char_suffix = "" if is_sqlite else " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

    # 1. Patients Table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS patients (
            id {auto_inc},
            full_name VARCHAR(255) NOT NULL,
            password VARCHAR(255) DEFAULT 'medicare123',
            password_hash VARCHAR(255) NULL,
            dob VARCHAR(50),
            age INT,
            gender VARCHAR(50),
            blood_group VARCHAR(20),
            marital_status VARCHAR(50),
            occupation VARCHAR(255),
            mobile VARCHAR(50),
            alternate_mobile VARCHAR(50),
            email VARCHAR(255),
            address TEXT,
            city VARCHAR(100),
            state VARCHAR(100),
            pin_code VARCHAR(20),
            emergency_name VARCHAR(255),
            emergency_relationship VARCHAR(100),
            emergency_number VARCHAR(50),
            allergies TEXT,
            existing_conditions TEXT,
            current_medications TEXT,
            failed_login_attempts INT DEFAULT 0,
            locked_until DATETIME NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ){char_suffix}
    """)

    # 2. Users Table (Authority, Doctor, Staff)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id {auto_inc},
            username VARCHAR(100) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE,
            password VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NULL,
            role VARCHAR(50) DEFAULT 'patient',
            full_name VARCHAR(255) NOT NULL,
            authority_code VARCHAR(100) NULL,
            is_approved TINYINT(1) DEFAULT 0,
            is_active TINYINT(1) DEFAULT 1,
            is_email_verified TINYINT(1) DEFAULT 0,
            access_code_hash VARCHAR(255) NULL,
            code_expires_at DATETIME NULL,
            code_used TINYINT(1) DEFAULT 0,
            failed_login_attempts INT DEFAULT 0,
            locked_until DATETIME NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ){char_suffix}
    """)

    # 3. Medical Records Table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS medical_records (
            id {auto_inc},
            patient_id INT NOT NULL,
            record_type VARCHAR(100),
            title VARCHAR(255),
            doctor_name VARCHAR(255),
            hospital_name VARCHAR(255),
            record_date VARCHAR(50),
            description TEXT,
            attachment_name VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ){char_suffix}
    """)

    # 4. Family History Table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS family_history (
            id {auto_inc},
            patient_id INT NOT NULL,
            relative_name VARCHAR(255),
            relationship VARCHAR(100),
            condition_name VARCHAR(255),
            age_at_diagnosis INT,
            is_living VARCHAR(10) DEFAULT 'Yes',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ){char_suffix}
    """)

    # 5. Genetic History Table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS genetic_history (
            id {auto_inc},
            patient_id INT NOT NULL,
            condition_title VARCHAR(255),
            inheritance_pattern VARCHAR(100),
            affected_relatives TEXT,
            carrier_status VARCHAR(100),
            risk_level VARCHAR(50),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ){char_suffix}
    """)

    # 6. Audit Logs Table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id {auto_inc},
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INT NULL,
            user_role VARCHAR(50) NULL,
            action VARCHAR(100) NOT NULL,
            ip_address VARCHAR(100) NULL,
            status VARCHAR(20) NOT NULL,
            details TEXT NULL
        ){char_suffix}
    """)

    connection.commit()

    # Apply schema migrations to update any existing tables
    upgrade_schema(connection)

    # Seed or upgrade official Doctor & Authority accounts
    seed_authorized_staff(connection)

    cursor.close()
    if close_when_done:
        connection.close()


def seed_authorized_staff(connection):
    """Seed or upgrade official Doctor and Authority accounts with secure Werkzeug password hashes."""
    from security import hash_password

    cursor = connection.cursor(dictionary=True)

    # 1. Seed / Upgrade Authority User (Dr. Alexander Wright)
    cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", ("admin", "admin@medicare.io"))
    admin_user = cursor.fetchone()

    auth_pw_hash = hash_password("admin123")
    if not admin_user:
        cursor.execute("""
            INSERT INTO users (username, email, password, password_hash, role, full_name, authority_code, is_approved, is_active, is_email_verified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, 1)
        """, ("admin", "admin@medicare.io", "admin123", auth_pw_hash, "authority", "Dr. Alexander Wright", "AUTH101"))
        connection.commit()
    else:
        cursor.execute("""
            UPDATE users SET
                email = COALESCE(email, %s),
                password_hash = COALESCE(password_hash, %s),
                role = 'authority',
                is_approved = 1,
                is_active = 1
            WHERE id = %s
        """, ("admin@medicare.io", auth_pw_hash, admin_user["id"]))
        connection.commit()

    # 2. Seed / Upgrade Authorized Doctor (Dr. A. Sharma)
    cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", ("dr.sharma", "dr.sharma@medicare.io"))
    doc_user = cursor.fetchone()

    doc_pw_hash = hash_password("doctor123")
    if not doc_user:
        cursor.execute("""
            INSERT INTO users (username, email, password, password_hash, role, full_name, authority_code, is_approved, is_active, is_email_verified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, 1)
        """, ("dr.sharma", "dr.sharma@medicare.io", "doctor123", doc_pw_hash, "doctor", "Dr. A. Sharma", "DOC201"))
        connection.commit()
    else:
        cursor.execute("""
            UPDATE users SET
                email = COALESCE(email, %s),
                password_hash = COALESCE(password_hash, %s),
                role = 'doctor',
                is_approved = 1,
                is_active = 1
            WHERE id = %s
        """, ("dr.sharma@medicare.io", doc_pw_hash, doc_user["id"]))
        connection.commit()

    # 3. Seed original demo patients if the table is empty
    try:
        cursor.execute("SELECT COUNT(*) as cnt FROM patients")
        row = cursor.fetchone()
        patient_count = row.get("cnt", 0) if isinstance(row, dict) else row[0]
        if patient_count == 0:
            demo_patients = [
                ("Eleanor Vance", "password123", "1994-08-14", 32, "Female", "O+", "Married",
                 "Software Engineer", "+91 98765 43210", "+91 91234 56789", "eleanor.vance@medicare.io",
                 "42 Evergreen Heights, Sector 15", "Bengaluru", "Karnataka", "560001",
                 "Thomas Vance", "Spouse", "+91 99887 76655",
                 "Penicillin (Moderate rash), Peanuts (Severe anaphylaxis risk)",
                 "Mild Bronchial Asthma, Type-2 Diabetes (Controlled)",
                 "Metformin 500mg (Daily), Salbutamol Inhaler (PRN / As needed)"),
                ("Siya Shah", "siya123", "2000-03-22", 26, "Female", "A+", "Single",
                 "Student", "9876543210", "", "siya.shah@test.io",
                 "101 Park Lane", "Mumbai", "Maharashtra", "400001",
                 "Ravi Shah", "Father", "9876540000",
                 "None", "None", "None"),
                ("Anushka Wankhede", "anushka123", "1999-07-10", 27, "Female", "B+", "Single",
                 "Developer", "7890123456", "", "anushka.w@test.io",
                 "55 Tech Park Road", "Pune", "Maharashtra", "411001",
                 "Meera Wankhede", "Mother", "7890120000",
                 "Dust", "None", "None"),
                ("Kumkum Wadile", "kumkum123", "1998-12-05", 28, "Female", "AB+", "Single",
                 "Designer", "8788625747", "", "kumkum.w@test.io",
                 "32 Garden Avenue", "Nagpur", "Maharashtra", "440001",
                 "Priya Wadile", "Sister", "8788620000",
                 "None", "Mild Anemia", "Iron supplements"),
            ]
            for p in demo_patients:
                pw_hash = hash_password(p[1])
                cursor.execute("""
                    INSERT INTO patients (
                        full_name, password, password_hash, dob, age, gender, blood_group, marital_status,
                        occupation, mobile, alternate_mobile, email, address, city, state, pin_code,
                        emergency_name, emergency_relationship, emergency_number,
                        allergies, existing_conditions, current_medications
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (p[0], p[1], pw_hash, *p[2:]))
            connection.commit()
    except Exception as e:
        print(f"[!] Patient seeding note: {e}")

    # 4. Ensure all existing patients have secure password hashes
    try:
        cursor.execute("SELECT id, password, password_hash FROM patients WHERE password_hash IS NULL OR password_hash = ''")
        unhashed_patients = cursor.fetchall()
        for p in unhashed_patients:
            plain = p.get("password") or "medicare123"
            p_hash = hash_password(plain)
            cursor.execute("UPDATE patients SET password_hash = %s WHERE id = %s", (p_hash, p["id"]))
        connection.commit()
    except Exception:
        pass

    cursor.close()
