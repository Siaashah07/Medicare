import os
import sqlite3

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
    raise ImportError("mysql-connector-python is required. Install it using: pip install mysql-connector-python")


def get_db_config():
    """Retrieve database connection settings from environment variables with safe defaults."""
    # Prioritize standard DB_* variables, then MYSQL_* aliases
    host = os.environ.get("DB_HOST") or os.environ.get("MYSQL_HOST") or "127.0.0.1"
    port_str = os.environ.get("DB_PORT") or os.environ.get("MYSQL_PORT") or "3306"
    try:
        port = int(port_str)
    except ValueError:
        port = 3306
    user = os.environ.get("DB_USER") or os.environ.get("MYSQL_USER") or "root"
    password = os.environ.get("DB_PASSWORD") or os.environ.get("MYSQL_PASSWORD") or ""
    database = os.environ.get("DB_NAME") or os.environ.get("MYSQL_DB") or "medicare"

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database
    }


def get_connection():
    """Connect to the primary MySQL database using environment configuration."""
    cfg = get_db_config()
    try:
        conn = mysql.connector.connect(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            autocommit=False,
            connect_timeout=5
        )
        return conn
    except MySQLError as err:
        # If database 'medicare' doesn't exist yet, attempt auto-creation
        if err.errno == 1049:  # Unknown database
            try:
                temp_conn = mysql.connector.connect(
                    host=cfg["host"],
                    port=cfg["port"],
                    user=cfg["user"],
                    password=cfg["password"],
                    connect_timeout=5
                )
                cur = temp_conn.cursor()
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                cur.close()
                temp_conn.close()

                # Reconnect to newly created database
                conn = mysql.connector.connect(
                    host=cfg["host"],
                    port=cfg["port"],
                    user=cfg["user"],
                    password=cfg["password"],
                    database=cfg["database"],
                    connect_timeout=5
                )
                init_db(conn)
                return conn
            except Exception as create_err:
                print(f"[!] Error creating MySQL database: {create_err}")
                raise create_err

        print(f"[!] MySQL Connection Error ({cfg['host']}:{cfg['port']}, user: {cfg['user']}): {err}")
        raise err


def init_db(connection=None):
    """Ensure all required tables and schema exist in MySQL without deleting existing data."""
    close_when_done = False
    if connection is None:
        connection = get_connection()
        close_when_done = True

    cursor = connection.cursor()

    # 1. Patients Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL,
            password VARCHAR(255) DEFAULT 'medicare123',
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # 2. Users Table (Authority & Staff)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'patient',
            full_name VARCHAR(255) NOT NULL,
            authority_code VARCHAR(100)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # 3. Medical Records Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medical_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            patient_id INT NOT NULL,
            record_type VARCHAR(100),
            title VARCHAR(255),
            doctor_name VARCHAR(255),
            hospital_name VARCHAR(255),
            record_date VARCHAR(50),
            description TEXT,
            attachment_name VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # 4. Family History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            patient_id INT NOT NULL,
            relative_name VARCHAR(255),
            relationship VARCHAR(100),
            condition_name VARCHAR(255),
            age_at_diagnosis INT,
            is_living VARCHAR(10) DEFAULT 'Yes',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # 5. Genetic History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS genetic_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            patient_id INT NOT NULL,
            condition_title VARCHAR(255),
            inheritance_pattern VARCHAR(100),
            affected_relatives TEXT,
            carrier_status VARCHAR(100),
            risk_level VARCHAR(50),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    connection.commit()

    # Migrate existing data from SQLite if MySQL tables are currently empty
    migrate_existing_data(connection)

    cursor.close()
    if close_when_done:
        connection.close()


def migrate_existing_data(mysql_conn):
    """Safely migrate existing patient records from local SQLite into MySQL without duplicating."""
    cursor = mysql_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patients")
    p_count = cursor.fetchone()[0]

    sqlite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "medicare.db")

    if p_count == 0 and os.path.exists(sqlite_path):
        try:
            print("[*] Migrating existing patient data from SQLite into MySQL...")
            s_conn = sqlite3.connect(sqlite_path)
            s_cursor = s_conn.cursor()

            # Migrate Patients
            s_cursor.execute("""
                SELECT id, full_name, dob, age, gender, blood_group, marital_status, occupation,
                       mobile, alternate_mobile, email, address, city, state, pin_code, emergency_name,
                       emergency_relationship, emergency_number, allergies, existing_conditions, current_medications, password
                FROM patients
            """)
            patients = s_cursor.fetchall()
            for p in patients:
                cursor.execute("""
                    INSERT INTO patients (
                        id, full_name, dob, age, gender, blood_group, marital_status, occupation,
                        mobile, alternate_mobile, email, address, city, state, pin_code, emergency_name,
                        emergency_relationship, emergency_number, allergies, existing_conditions, current_medications, password
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, p)
            mysql_conn.commit()

            # Migrate Users
            s_cursor.execute("SELECT id, username, password, role, full_name, authority_code FROM users")
            users = s_cursor.fetchall()
            for u in users:
                cursor.execute("""
                    INSERT IGNORE INTO users (id, username, password, role, full_name, authority_code)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, u)
            mysql_conn.commit()

            # Migrate Medical Records
            s_cursor.execute("""
                SELECT id, patient_id, record_type, title, doctor_name, hospital_name, record_date, description, attachment_name, created_at
                FROM medical_records
            """)
            records = s_cursor.fetchall()
            for r in records:
                cursor.execute("""
                    INSERT INTO medical_records (id, patient_id, record_type, title, doctor_name, hospital_name, record_date, description, attachment_name, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, r)
            mysql_conn.commit()

            # Migrate Family History
            s_cursor.execute("""
                SELECT id, patient_id, relative_name, relationship, condition_name, age_at_diagnosis, is_living, notes, created_at
                FROM family_history
            """)
            fam = s_cursor.fetchall()
            for f in fam:
                cursor.execute("""
                    INSERT INTO family_history (id, patient_id, relative_name, relationship, condition_name, age_at_diagnosis, is_living, notes, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, f)
            mysql_conn.commit()

            # Migrate Genetic History
            s_cursor.execute("""
                SELECT id, patient_id, condition_title, inheritance_pattern, affected_relatives, carrier_status, risk_level, notes, created_at
                FROM genetic_history
            """)
            gen = s_cursor.fetchall()
            for g in gen:
                cursor.execute("""
                    INSERT INTO genetic_history (id, patient_id, condition_title, inheritance_pattern, affected_relatives, carrier_status, risk_level, notes, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, g)
            mysql_conn.commit()

            s_cursor.close()
            s_conn.close()
            print(f"[✓] Successfully migrated {len(patients)} patient record(s) into MySQL!")
        except Exception as e:
            print(f"[!] Migration note: {e}")
            mysql_conn.commit()

    # Ensure at least admin user exists
    cursor.execute("SELECT COUNT(*) FROM users")
    u_count = cursor.fetchone()[0]
    if u_count == 0:
        cursor.execute("""
            INSERT INTO users (username, password, role, full_name, authority_code)
            VALUES (%s, %s, %s, %s, %s)
        """, ("admin", "admin123", "authority", "Dr. Alexander Wright", "AUTH101"))
        mysql_conn.commit()

    cursor.close()
