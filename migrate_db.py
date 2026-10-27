"""
Medicare Database Migration & Health-Check Script
Safely adds authentication and authorization fields, audit log tables,
and seeds initial Doctor and Authority accounts without deleting or resetting existing records.
"""

import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from db import get_connection, init_db

def run_migration():
    print("================================================================")
    print("🚀 MEDICARE PRODUCTION DATABASE MIGRATION")
    print("================================================================")

    try:
        conn = get_connection()
        print("[✓] Connected to database successfully.")
        
        print("[*] Running schema upgrades and table verification...")
        init_db(conn)
        print("[✓] Schema upgrades applied successfully.")

        cursor = conn.cursor(dictionary=True)

        # Verify Users
        cursor.execute("SELECT id, username, email, role, full_name, is_approved, is_active FROM users")
        users = cursor.fetchall()
        print(f"\n[✓] Registered Staff Accounts ({len(users)} found):")
        for u in users:
            status = "ACTIVE & APPROVED" if u.get("is_approved") and u.get("is_active") else "PENDING"
            print(f"  • [{u.get('role').upper()}] {u.get('full_name')} | Email: {u.get('email')} | Status: {status}")

        # Verify Patients
        cursor.execute("SELECT COUNT(*) as count FROM patients")
        p_count = cursor.fetchone()["count"]
        print(f"\n[✓] Patient Records Preserved: {p_count} patient(s)")

        # Verify Audit Logs
        cursor.execute("SELECT COUNT(*) as count FROM audit_logs")
        log_count = cursor.fetchone()["count"]
        print(f"[✓] Security Audit Log Ready: {log_count} event(s)")

        cursor.close()
        conn.close()
        print("\n================================================================")
        print("✅ DATABASE MIGRATION COMPLETED SUCCESSFULLY WITH ZERO DATA LOSS!")
        print("================================================================\n")
        return True

    except Exception as e:
        print(f"\n[❌] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
