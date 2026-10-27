# Medicare -- Smart Healthcare Management System

A modern, production-ready healthcare management web application with role-based access control, two-factor email authentication, and cloud PostgreSQL.

## Key Features

- **Digital Health ID Cards** with dynamic scannable emergency QR codes
- **Offline AI Health Assistant** -- 100% local clinical symptom triage (zero API costs)
- **Role-Based Access Control** -- Patient, Doctor, and Authority portals with strict authorization
- **Two-Factor Authentication (2FA)** -- Email verification codes for Doctor and Authority logins
- **IDOR Protection** -- Patients can only access their own records; doctors see only assigned patients
- **Family Medical History** and multi-generational tracking
- **Genetic and Hereditary Risk Assessment**
- **Medical Records and Prescription Archiving**
- **Cloud PostgreSQL Database** powered by Neon.tech

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python Flask |
| Database | PostgreSQL (Neon.tech cloud) with SQLite local fallback |
| Auth | Werkzeug scrypt hashing + SHA-256 2FA codes + rate limiting |
| Email | SMTP (configurable provider) |
| Deployment | Vercel (serverless) |
| AI | Offline clinical decision engine (no external APIs) |

---

## Quick Start (Local Development)

### 1. Clone the repository

```bash
git clone https://github.com/Siaashah07/Medicare.git
cd Medicare
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Required variables in `.env`:

```env
DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require
SECRET_KEY=your-secret-key
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-email@gmail.com
```

### 4. Run development server

```bash
python run.py
```

Browser opens automatically at `http://127.0.0.1:5000/`.

---

## Production Deployment

### Vercel (Recommended)

1. Push to GitHub
2. Import the repo on [vercel.com](https://vercel.com)
3. Set environment variables (`DATABASE_URL`, `SECRET_KEY`, `SMTP_*`)
4. Deploy -- Vercel uses `vercel.json` and `wsgi.py` automatically

### WSGI Server (VPS/VM)

```bash
python wsgi.py
```

Uses Waitress (Windows) or Gunicorn (Linux) for production-grade serving.

---

## Security Architecture

### Authentication Flow

1. **Patients** -- Standard login with email/mobile + password
2. **Doctors** -- Password login triggers 2FA email verification code (10-min expiry, single-use)
3. **Authorities** -- Password login triggers 2FA email verification code (10-min expiry, single-use)

### Protections

- **Rate limiting** -- 5 failed login attempts triggers 15-minute account lockout
- **IDOR prevention** -- `verify_patient_access()` ensures patients only see their own data
- **Doctor scoping** -- Doctors only see patients assigned to them via `doctor_patient_assignments`
- **Role decorators** -- `@login_required` and `@role_required` on all protected routes
- **Password hashing** -- Werkzeug scrypt with automatic hash verification
- **2FA codes** -- Cryptographically random, SHA-256 hashed, 10-minute expiry, single-use
- **Audit logging** -- All sensitive actions logged to `audit_logs` table

---

## Database Schema

The PostgreSQL schema (`schema.sql`) includes:

| Table | Purpose |
|-------|---------|
| `users` | All user accounts (patients, doctors, authorities) with roles |
| `patients` | Patient demographic and health profile data |
| `verification_codes` | 2FA email verification codes (hashed) |
| `doctor_patient_assignments` | Maps doctors to their authorized patients |
| `audit_logs` | Security event logging |
| `medical_records` | Prescriptions, lab reports, documents |
| `family_history` | Multi-generational family medical history |
| `genetic_history` | Genetic and hereditary condition tracking |

---

## Default Accounts

| Role | Email | Password |
|------|-------|----------|
| Authority (Admin) | `admin@medicare.io` | `Admin@2024secure` |
| Doctor | `dr.ananya@medicare.io` | `Doctor@2024secure` |
| Patient | `eleanor.vance@medicare.io` | `password123` |

> **Note:** Doctor and Authority logins require a 2FA email verification code after password entry. In development mode (no SMTP configured), codes are printed to the console.

---

## Project Structure

```
Medicare/
├── app.py                  # Flask routes, sessions, auth, and APIs
├── auth_service.py         # 2FA codes, rate limiting, IDOR authorization
├── ai_assistant.py         # Offline AI clinical decision engine
├── db.py                   # PostgreSQL (Neon) + SQLite fallback wrapper
├── mailer.py               # SMTP email delivery for 2FA codes
├── wsgi.py                 # Production WSGI entrypoint
├── run.py                  # Development server with auto-browser launch
├── schema.sql              # PostgreSQL database schema
├── requirements.txt        # Python dependencies
├── vercel.json             # Vercel deployment configuration
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
├── README.md               # This file
└── templates/
    ├── intro.html              # Public landing page
    ├── login.html              # 3-tab login (Patient/Doctor/Authority)
    ├── Registration.html       # Patient registration
    ├── verify_code.html        # 2FA code entry page
    ├── dashboard.html          # Patient dashboard
    ├── doctor_dashboard.html   # Doctor portal (assigned patients only)
    ├── doctor_registration.html # Doctor credential application
    ├── authority_dashboard.html # Authority admin panel
    ├── health_profile.html     # Patient health profile + QR generator
    ├── medical_id_card.html    # Printable medical ID card
    ├── medical_records.html    # Prescriptions and lab reports
    ├── family_history.html     # Family medical history
    ├── genetic_history.html    # Genetic condition tracking
    ├── ai_assistant.html       # AI health assistant chat
    ├── settings.html           # Emergency contacts and notifications
    ├── 404.html                # Page not found
    └── 500.html                # Internal server error
```

---

## License

Open source for educational and healthcare management development.
