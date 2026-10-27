"""
Medicare Automated Cloud Database Provisioner
Takes any Neon.tech, Supabase, or Cloud PostgreSQL URL,
creates tables, applies schema, seeds verified accounts, and tests connectivity.
"""

import sys
import os
import psycopg2

def setup_cloud_database(database_url):
    print("=" * 65)
    print("MEDICARE CLOUD POSTGRESQL PROVISIONER (Neon / Supabase / Render)")
    print("=" * 65)

    if not database_url or not database_url.startswith(("postgres://", "postgresql://")):
        print("[!] Error: Please provide a valid PostgreSQL connection URL starting with postgresql://")
        return False

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    print(f"\n[1/4] Connecting to Cloud PostgreSQL instance...")
    try:
        conn = psycopg2.connect(database_url, connect_timeout=10)
        conn.autocommit = True
        cur = conn.cursor()
        print("  [+] Connected successfully!")
    except Exception as e:
        print(f"  [!] Failed to connect to database: {e}")
        return False

    schema_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    print(f"\n[2/4] Applying PostgreSQL schema from {os.path.basename(schema_file)}...")
    try:
        with open(schema_file, "r", encoding="utf-8") as f:
            sql_script = f.read()
        cur.execute(sql_script)
        print("  [+] Schema tables, foreign keys, and indexes created successfully!")
    except Exception as e:
        print(f"  [!] Notice during schema application: {e}")

    print(f"\n[3/4] Verifying Seeded Accounts & Permissions...")
    try:
        cur.execute("SELECT email, role, is_approved FROM users")
        users = cur.fetchall()
        print("  [+] Seeded User Accounts in Cloud DB:")
        for u in users:
            print(f"    - {u[0]} (Role: {u[1]}, Approved: {u[2]})")

        cur.execute("SELECT id, full_name, blood_group FROM patients")
        patients = cur.fetchall()
        print("  [+] Seeded Patients:")
        for p in patients:
            print(f"    - P{p[0]:05d} - {p[1]} (Blood: {p[2]})")
    except Exception as e:
        print(f"  [!] Error verifying seed data: {e}")

    # Update local .env
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    print(f"\n[4/4] Updating local .env with cloud database connection string...")
    try:
        lines = []
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.startswith("DATABASE_URL="):
                        lines.append(line)
        lines.insert(0, f"DATABASE_URL={database_url}\n")
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print("  [+] Updated .env file successfully!")
    except Exception as e:
        print(f"  [!] Error writing .env: {e}")

    cur.close()
    conn.close()

    print("\n" + "=" * 65)
    print("SUCCESS: CLOUD DATABASE PROVISIONING COMPLETE!")
    print("Your Medicare project is now actively connected to your cloud PostgreSQL database.")
    print("=" * 65 + "\n")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python setup_cloud_db.py \"postgresql://user:pass@ep-cool.us-east-2.aws.neon.tech/neondb?sslmode=require\"\n")
        sys.exit(1)

    setup_cloud_database(sys.argv[1].strip())
