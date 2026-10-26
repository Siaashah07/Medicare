-- ==============================================================
-- MEDICARE HEALTHCARE MANAGEMENT SYSTEM - PRODUCTION DATABASE
-- Database: medicare
-- Compatible with MySQL 5.7+, MySQL 8.0+, MariaDB
-- ==============================================================

CREATE DATABASE IF NOT EXISTS `medicare` 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

USE `medicare`;

-- 1. Patients Table
CREATE TABLE IF NOT EXISTS `patients` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `full_name` VARCHAR(150) NOT NULL,
    `password` VARCHAR(255) DEFAULT 'medicare123',
    `dob` DATE NULL,
    `age` INT NULL,
    `gender` VARCHAR(20) NULL,
    `blood_group` VARCHAR(10) NULL,
    `marital_status` VARCHAR(30) NULL,
    `occupation` VARCHAR(100) NULL,
    `mobile` VARCHAR(25) NOT NULL,
    `alternate_mobile` VARCHAR(25) NULL,
    `email` VARCHAR(120) NULL,
    `address` TEXT NULL,
    `city` VARCHAR(80) NULL,
    `state` VARCHAR(80) NULL,
    `pin_code` VARCHAR(20) NULL,
    `emergency_name` VARCHAR(150) NULL,
    `emergency_relationship` VARCHAR(50) NULL,
    `emergency_number` VARCHAR(25) NULL,
    `allergies` TEXT NULL,
    `existing_conditions` TEXT NULL,
    `current_medications` TEXT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Family Medical History
CREATE TABLE IF NOT EXISTS `family_history` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `patient_id` INT NOT NULL,
    `relative_name` VARCHAR(150) NOT NULL,
    `relationship` VARCHAR(50) NOT NULL,
    `condition_name` VARCHAR(200) NOT NULL,
    `age_at_diagnosis` INT NULL,
    `is_living` VARCHAR(10) DEFAULT 'Yes',
    `notes` TEXT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_fam_patient` (`patient_id`),
    CONSTRAINT `fk_fam_patient` FOREIGN KEY (`patient_id`) REFERENCES `patients`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Genetic & Hereditary History
CREATE TABLE IF NOT EXISTS `genetic_history` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `patient_id` INT NOT NULL,
    `condition_title` VARCHAR(200) NOT NULL,
    `inheritance_pattern` VARCHAR(100) NULL,
    `affected_relatives` VARCHAR(255) NULL,
    `carrier_status` VARCHAR(50) NULL,
    `risk_level` VARCHAR(30) DEFAULT 'Moderate',
    `notes` TEXT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_gen_patient` (`patient_id`),
    CONSTRAINT `fk_gen_patient` FOREIGN KEY (`patient_id`) REFERENCES `patients`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Medical Records & Prescriptions
CREATE TABLE IF NOT EXISTS `medical_records` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `patient_id` INT NOT NULL,
    `record_type` VARCHAR(80) NOT NULL,
    `title` VARCHAR(200) NOT NULL,
    `doctor_name` VARCHAR(150) NULL,
    `hospital_name` VARCHAR(200) NULL,
    `record_date` DATE NULL,
    `description` TEXT NULL,
    `attachment_name` VARCHAR(255) DEFAULT 'Medical_Report.pdf',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_rec_patient` (`patient_id`),
    CONSTRAINT `fk_rec_patient` FOREIGN KEY (`patient_id`) REFERENCES `patients`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Authorized Users & Staff
CREATE TABLE IF NOT EXISTS `users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(80) NOT NULL UNIQUE,
    `password` VARCHAR(255) NOT NULL,
    `role` VARCHAR(40) DEFAULT 'authority',
    `full_name` VARCHAR(150) NULL,
    `authority_code` VARCHAR(50) NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ==============================================================
-- DEMO SEED DATA
-- ==============================================================

-- Seed Sample Authority
INSERT IGNORE INTO `users` (`username`, `password`, `role`, `full_name`, `authority_code`)
VALUES ('admin', 'admin123', 'authority', 'Dr. Alexander Wright', 'AUTH101');

-- Seed Sample Patient
INSERT INTO `patients` (
    `id`, `full_name`, `dob`, `age`, `gender`, `blood_group`, `marital_status`, `occupation`,
    `mobile`, `alternate_mobile`, `email`, `address`, `city`, `state`, `pin_code`,
    `emergency_name`, `emergency_relationship`, `emergency_number`,
    `allergies`, `existing_conditions`, `current_medications`
) VALUES (
    1, 'Eleanor Vance', '1994-08-14', 32, 'Female', 'O+', 'Married', 'Software Engineer',
    '+91 98765 43210', '+91 91234 56789', 'eleanor.vance@medicare.io',
    '42 Evergreen Heights, Sector 15', 'Bengaluru', 'Karnataka', '560001',
    'Thomas Vance', 'Spouse', '+91 99887 76655',
    'Penicillin (Moderate rash), Peanuts (Severe anaphylaxis risk)',
    'Mild Bronchial Asthma, Type-2 Diabetes (Controlled)',
    'Metformin 500mg (Daily), Salbutamol Inhaler (PRN / As needed)'
) ON DUPLICATE KEY UPDATE `full_name` = VALUES(`full_name`);

-- Seed Family History
INSERT INTO `family_history` (`patient_id`, `relative_name`, `relationship`, `condition_name`, `age_at_diagnosis`, `is_living`, `notes`)
VALUES 
    (1, 'Robert Vance', 'Father', 'Hypertension & Type-2 Diabetes', 52, 'Yes', 'Managed with oral medication and diet.'),
    (1, 'Martha Vance', 'Mother', 'Thyroid Disorders (Hypothyroidism)', 46, 'Yes', 'Takes daily levothyroxine.');

-- Seed Genetic History
INSERT INTO `genetic_history` (`patient_id`, `condition_title`, `inheritance_pattern`, `affected_relatives`, `carrier_status`, `risk_level`, `notes`)
VALUES 
    (1, 'Familial Hypercholesterolemia', 'Autosomal Dominant', 'Paternal Grandfather, Father', 'Not Screened', 'Moderate', 'Recommended yearly lipid profiling.');

-- Seed Medical Records
INSERT INTO `medical_records` (`patient_id`, `record_type`, `title`, `doctor_name`, `hospital_name`, `record_date`, `description`, `attachment_name`)
VALUES 
    (1, 'Prescription', 'Annual Health Checkup & Vitals', 'Dr. A. Sharma', 'Medicare Central Hospital', '2026-08-10', 'Blood sugar stable (HbA1c 6.2%). Blood pressure 120/80 mmHg. Advised active cardio.', 'Prescription_Aug2026.pdf');
