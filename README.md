# 🏥 Medicare — Smart Healthcare Management System & Offline AI

A modern, production-ready healthcare management web application featuring:
- 📱 **Digital Health ID Cards with Dynamic Scannable Emergency QR Codes**
- 🤖 **100% Offline Clinical AI Health Assistant & Symptom Triage** (Zero external API costs)
- 👨‍👩‍👧‍👦 **Family Medical History & Multi-Generational Tracking**
- 🧬 **Genetic & Hereditary Risk Assessment**
- 📋 **Medical Records & Prescription Archiving**
- 🏥 **Hospital Authority & Clinical Lookup Portal**
- 🛡️ **Dual-Engine Resilient Database** (MySQL with zero-config SQLite automatic fallback)

---

## 🌟 Key Features

### 1. Dynamic Emergency QR Health Card Generator
- Encodes critical first-responder data: Blood group, severe allergies, chronic illnesses, and emergency contacts.
- Includes a realistic digital smart health pass mockup with instant **PNG Download** and browser **Print Layout**.
- Scan-to-view paramedic emergency summary without login requirement.

### 2. Offline AI Health Assistant
- Operates 100% locally with zero external API dependencies or fees.
- **Personal Profile Context Aware**: Knows the logged-in patient's recorded allergies (e.g. alerts against Penicillin if contraindicated).
- **Red-Flag Emergency Triage**: Detects stroke signs, chest pain, and critical respiratory distress, immediately triggering emergency contact protocols.
- **First Aid & Condition Guidance**: Immediate step-by-step guidance for burns, CPR, diabetes care, and blood pressure monitoring.

### 3. Dual-Database Architecture
- **Primary**: MySQL (`medicare`) with configurable environment variables.
- **Automated Fallback**: Seamless local SQLite (`medicare.db`) that initializes automatically if MySQL is unavailable, ensuring zero downtime.

---

## 🚀 Quick Start (Local Run)

### 1. Clone / Open Project
```powershell
cd "C:\Users\shahs\OneDrive\Desktop\Medicare"
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Run Development Server
```powershell
python run.py
```
Your browser will open automatically at `http://127.0.0.1:5000/`.

---

## 🌐 Production WSGI Serving (Windows & Linux)

For production, run using the multi-threaded WSGI server without debug overhead:

```powershell
python wsgi.py
```
* On Windows, this launches high-concurrency **Waitress**.
* On Linux/Mac, this serves with **Gunicorn** or Waitress.

---

## ☁️ Cloud Deployment Options

### Option A: Deploy to Render (Recommended Free Cloud)
1. Push your project to GitHub.
2. Log into [Render.com](https://render.com) and click **New + > Web Service**.
3. Select your repository.
4. Render will auto-detect Python:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn wsgi:app`
5. Click **Deploy Web Service** — your app is live!

### Option B: Deploy to Railway
1. Install Railway CLI or connect via GitHub on [railway.app](https://railway.app).
2. Railway will automatically pick up the included `Procfile` (`web: gunicorn wsgi:app`).
3. (Optional) Add a MySQL database in Railway; set `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB` in environment variables.

### Option C: Containerized Deployment (Docker)
Build and run anywhere with Docker:

```bash
# Build Docker image
docker build -t medicare-app .

# Run container
docker run -d -p 5000:5000 --name medicare medicare-app
```
Access at `http://localhost:5000`.

---

## 🗄️ MySQL Database Setup (Optional)

If you wish to use your local MySQL server (XAMPP / WAMP / MySQL Workbench):

1. Open your MySQL client (e.g., phpMyAdmin).
2. Create database and tables by importing `schema.sql`:
   ```sql
   SOURCE schema.sql;
   ```
3. Update connection settings in `.env` or set environment variables:
   ```env
   MYSQL_HOST=localhost
   MYSQL_PORT=3306
   MYSQL_USER=root
   MYSQL_PASSWORD=your_password
   MYSQL_DB=medicare
   ```

*Note: If no MySQL credentials are provided, Medicare automatically falls back to `medicare.db`.*

---

## 🔑 Registered Accounts & Passwords

| Role | Name | Patient ID / Mobile / Email | Password |
| :--- | :--- | :--- | :--- |
| **Patient** | Kumkum Ganesh Wadile | `8788625747` (or `P00004`) | `kumkum123` |
| **Patient** | Siya Shah | `8793373606` (or `P00002`) | `siya123` |
| **Patient** | Anushka Satish Wankhede | `9518995318` (or `P00003`) | `anushka123` |
| **Patient** | Eleanor Vance | `eleanor.vance@medicare.io` (or `P00001`) | `password123` |
| **Authority** | Dr. Alexander Wright | `admin` | `admin123` (Code: `AUTH101`) |

> 💡 **Built-in Database Manager**: Visit **`http://127.0.0.1:5000/database`** anytime to view and edit all tables, accounts, and passwords in real-time right from your browser!

---

## 🪪 Official Physical-Style Medical ID Card

Medicare generates a standardized PVC Medical ID Card format matching clinical standards:
- **Direct View & Print URL**: `http://127.0.0.1:5000/card/<patient_id>`
- Features: Top blue banner (`MEDICAL ID CARD - Access My Health Record`), medical cross emblem, profile link, patient demographics, and high-density scannable QR code with bold `SCAN` badge.

---

## 📁 Project Structure

```
Medicare/
├── app.py                  # Core Flask routing, sessions, auth, and APIs
├── ai_assistant.py         # Offline AI clinical decision engine
├── db.py                   # Dual-database connection & automatic fallback
├── wsgi.py                 # Production WSGI entrypoint (Waitress / Gunicorn)
├── run.py                  # Development runner with auto-browser launch
├── test_suite.py           # Automated unit & integration test suite
├── schema.sql              # MySQL production database schema script
├── requirements.txt        # Production dependencies list
├── Procfile                # Render / Railway / Heroku deployment config
├── Dockerfile              # Container deployment recipe
├── .dockerignore           # Container ignore rules
├── .env.example            # Environment variables template
├── templates/
│   ├── intro.html          # Public landing page
│   ├── login.html          # Secure login with 1-click accounts & password recovery
│   ├── Registration.html   # Registration with password creation & validation
│   ├── database_manager.html # Built-in web database explorer & password manager
│   ├── medical_id_card.html# Official printable photo-style Medical ID Card
│   ├── dashboard.html      # Main patient dashboard with AI trigger & ID card
│   ├── health_profile.html # Profile with Emergency QR generator & PVC ID card
│   ├── ai_assistant.html   # Offline AI Health Assistant chat interface
│   ├── family_history.html # Family medical tracking
│   ├── genetic_history.html# Genetic condition risk mapper
│   ├── medical_records.html# Prescriptions and lab reports archive
│   ├── authority_dashboard.html # Hospital clinical lookup directory
│   ├── settings.html       # Emergency SMS and notification settings
│   ├── 404.html            # Error page: Page Not Found
│   └── 500.html            # Error page: Internal Server Error
└── README.md               # Complete documentation
```

---

## 📄 License
Open source for educational and healthcare management development.
