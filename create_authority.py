"""
Medicare Administrative CLI Account Creator
Usage:
  python create_authority.py --email admin@hospital.org --name "Dr. Alexander Wright" --password "SecureAdminPassword!" [--role authority|doctor]
"""

import argparse
import sys
from werkzeug.security import generate_password_hash
from db import get_connection, init_db


def main():
    parser = argparse.ArgumentParser(description="Create Medicare Doctor or Authority Accounts")
    parser.add_argument("--email", required=True, help="Official Email Address")
    parser.add_argument("--name", required=True, help="Full Name (e.g. 'Dr. John Doe')")
    parser.add_argument("--password", required=True, help="Account Password")
    parser.add_argument("--role", default="authority", choices=["authority", "doctor"], help="User role (authority or doctor)")
    parser.add_argument("--specialization", default="General Medicine", help="Doctor Specialization (if role is doctor)")
    parser.add_argument("--license", default="MCI-VERIFIED", help="Medical License Number (if role is doctor)")

    args = parser.parse_args()

    init_db()
    conn = get_connection()
    if not conn:
        print("[!] Error connecting to database.")
        sys.exit(1)

    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (args.email.strip().lower(),))
    if cur.fetchone():
        print(f"[!] User with email '{args.email}' already exists.")
        cur.close()
        conn.close()
        sys.exit(1)

    pw_hash = generate_password_hash(args.password)
    cur.execute("""
        INSERT INTO users (email, password_hash, role, full_name, specialization, license_number, is_approved, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (args.email.strip().lower(), pw_hash, args.role, args.name.strip(), args.specialization, args.license, True, True))
    conn.commit()
    cur.close()
    conn.close()

    print("\n" + "=" * 65)
    print(f" Successfully created approved {args.role.upper()} account!")
    print(f" Name:     {args.name}")
    print(f" Email:    {args.email}")
    print(f" Role:     {args.role}")
    print(f" Status:   Active & Approved")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
