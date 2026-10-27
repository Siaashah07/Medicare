-- ==============================================================
-- MEDICARE HEALTHCARE MANAGEMENT SYSTEM - POSTGRESQL PRODUCTION DATABASE
-- Database Engine: PostgreSQL 14 / 15 / 16 (Render, Neon, Supabase, AWS RDS)
-- ==============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Patients Table (Demographics, Medical Records, Emergency Profiles)
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    dob DATE NULL,
    age INT NULL,
    gender VARCHAR(20) NULL,
    blood_group VARCHAR(10) NULL,
    marital_status VARCHAR(30) NULL,
    occupation VARCHAR(100) NULL,
    mobile VARCHAR(25) NOT NULL,
    alternate_mobile VARCHAR(25) NULL,
    email VARCHAR(120) NULL,
    address TEXT NULL,
    city VARCHAR(80) NULL,
    state VARCHAR(80) NULL,
    pin_code VARCHAR(20) NULL,
    emergency_name VARCHAR(150) NULL,
    emergency_relationship VARCHAR(50) NULL,
    emergency_number VARCHAR(25) NULL,
    allergies TEXT NULL,
    existing_conditions TEXT NULL,
    current_medications TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patients_mobile ON patients(mobile);
CREATE INDEX IF NOT EXISTS idx_patients_email ON patients(email);

-- 2. Users Table (Role-based Accounts: Doctor, Authority, Admin)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(150) UNIQUE NOT NULL,
    username VARCHAR(80) UNIQUE NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL CHECK (role IN ('doctor', 'authority', 'patient', 'admin')),
    full_name VARCHAR(150) NOT NULL,
    specialization VARCHAR(120) NULL,
    license_number VARCHAR(80) NULL,
    is_approved BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- 3. Verification Codes Table (MFA Short-Lived One-Time Codes)
CREATE TABLE IF NOT EXISTS verification_codes (
    id SERIAL PRIMARY KEY,
    user_id INT NULL REFERENCES users(id) ON DELETE CASCADE,
    email VARCHAR(150) NOT NULL,
    code_hash VARCHAR(255) NOT NULL,
    purpose VARCHAR(50) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    is_used BOOLEAN NOT NULL DEFAULT FALSE,
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_codes_email_purpose ON verification_codes(email, purpose, is_used);

-- 4. Doctor-Patient Assignments (IDOR Scoping)
CREATE TABLE IF NOT EXISTS doctor_patient_assignments (
    id SERIAL PRIMARY KEY,
    doctor_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id INT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    assigned_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    notes TEXT NULL,
    CONSTRAINT uq_doctor_patient UNIQUE (doctor_id, patient_id)
);

CREATE INDEX IF NOT EXISTS idx_dpa_doctor ON doctor_patient_assignments(doctor_id);
CREATE INDEX IF NOT EXISTS idx_dpa_patient ON doctor_patient_assignments(patient_id);

-- 5. Security Audit Logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INT NULL,
    user_role VARCHAR(40) NULL,
    action VARCHAR(120) NOT NULL,
    ip_address VARCHAR(45) NULL,
    details TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(created_at DESC);

-- 6. Medical Records & Prescriptions
CREATE TABLE IF NOT EXISTS medical_records (
    id SERIAL PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    record_type VARCHAR(80) NOT NULL,
    title VARCHAR(200) NOT NULL,
    doctor_name VARCHAR(150) NULL,
    hospital_name VARCHAR(200) NULL,
    record_date DATE NULL,
    description TEXT NULL,
    attachment_name VARCHAR(255) DEFAULT 'Medical_Report.pdf',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rec_patient ON medical_records(patient_id);

-- 7. Family Medical History
CREATE TABLE IF NOT EXISTS family_history (
    id SERIAL PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    relative_name VARCHAR(150) NOT NULL,
    relationship VARCHAR(50) NOT NULL,
    condition_name VARCHAR(200) NOT NULL,
    age_at_diagnosis INT NULL,
    is_living VARCHAR(10) DEFAULT 'Yes',
    notes TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fam_patient ON family_history(patient_id);

-- 8. Genetic & Hereditary History
CREATE TABLE IF NOT EXISTS genetic_history (
    id SERIAL PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    condition_title VARCHAR(200) NOT NULL,
    inheritance_pattern VARCHAR(100) NULL,
    affected_relatives TEXT NULL,
    carrier_status VARCHAR(50) NULL,
    risk_level VARCHAR(30) DEFAULT 'Moderate',
    notes TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gen_patient ON genetic_history(patient_id);

-- ==============================================================
-- INITIAL SEED DATA
-- Default Passwords (pre-hashed with pbkdf2:sha256):
-- Authority: admin@medicare.io / AdminSecure@2026!
-- Doctor:    dr.ananya@medicare.io / DoctorSecure@2026!
-- Patient:   eleanor.vance@medicare.io / password123
-- ==============================================================

-- Seed Authority
INSERT INTO users (username, email, password_hash, role, full_name, is_approved, is_active)
VALUES (
    'admin',
    'admin@medicare.io',
    'scrypt:32768:8:1$1u5K7eZc0XlY$37189178ad996d99ab92823616238b1f7f02d4b96ae6fae4da0d85942f7d3a863b9000a94fb21a37a918a554238e55e4e815664177d61c0d484784a9531ca87d',
    'authority',
    'Dr. Alexander Wright (Chief Medical Officer)',
    TRUE,
    TRUE
) ON CONFLICT (email) DO NOTHING;

-- Seed Doctor
INSERT INTO users (username, email, password_hash, role, full_name, specialization, license_number, is_approved, is_active)
VALUES (
    'dr_ananya',
    'dr.ananya@medicare.io',
    'scrypt:32768:8:1$K1m9g6YqV7zL$5519e49c755f111a4325a62e0887e14853e839e11593c6df6baeb57404e9c7ea019a32c2538cbfa09ba3a79d39e802bb04351659a45e2ec989c02aa004246830',
    'doctor',
    'Dr. Ananya Sen',
    'Cardiology',
    'MCI-CARD-9082',
    TRUE,
    TRUE
) ON CONFLICT (email) DO NOTHING;

-- Seed Sample Patient (Eleanor Vance)
INSERT INTO patients (
    id, full_name, password_hash, dob, age, gender, blood_group, marital_status, occupation,
    mobile, alternate_mobile, email, address, city, state, pin_code,
    emergency_name, emergency_relationship, emergency_number,
    allergies, existing_conditions, current_medications
) VALUES (
    1,
    'Eleanor Vance',
    'scrypt:32768:8:1$x8N4p2Z9qL1m$bf211f32a76f2355dd181e14e7a68fbf120d53531bcfbb96e572e90c885faee9cfa3928a478be32a2ef11904e28eefd79eec58f4a3bc6eb9e7f41a86241b3a1a',
    '1994-08-14',
    32,
    'Female',
    'O+',
    'Married',
    'Software Engineer',
    '+91 98765 43210',
    '+91 91234 56789',
    'eleanor.vance@medicare.io',
    '42 Evergreen Heights, Sector 15',
    'Bengaluru',
    'Karnataka',
    '560001',
    'Thomas Vance',
    'Spouse',
    '+91 99887 76655',
    'Penicillin (Moderate rash), Peanuts (Severe anaphylaxis risk)',
    'Mild Bronchial Asthma, Type-2 Diabetes (Controlled)',
    'Metformin 500mg (Daily), Salbutamol Inhaler (PRN / As needed)'
) ON CONFLICT (id) DO NOTHING;

-- Seed Doctor-Patient Assignment (Dr. Ananya assigned to Eleanor Vance)
INSERT INTO doctor_patient_assignments (doctor_id, patient_id, notes)
SELECT u.id, 1, 'Primary cardiologist for cardiovascular wellness'
FROM users u
WHERE u.email = 'dr.ananya@medicare.io'
ON CONFLICT (doctor_id, patient_id) DO NOTHING;
