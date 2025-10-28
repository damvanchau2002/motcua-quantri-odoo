#!/usr/bin/env python3
"""
Script to fix notification_type constraint violation in res.users
"""
import configparser
import psycopg2

def fix_notification_constraint():
    # Read Odoo configuration
    cfg_path = r"d:\motcua-quantri-odoo\odoo.cfg"
    config = configparser.ConfigParser()
    config.read(cfg_path)
    opts = config["options"]

    # Database connection parameters
    host = opts.get("db_host", "localhost")
    port = int(opts.get("db_port", "5432"))
    user = opts.get("db_user", "odoo")
    password = opts.get("db_password", "odoo123")
    dbname = opts.get("db_name", "odoo_db")

    print(f"Connecting to database {dbname} as {user}@{host}:{port}...")
    
    try:
        conn = psycopg2.connect(
            host=host, 
            port=port, 
            user=user, 
            password=password, 
            dbname=dbname
        )
        conn.autocommit = True
        cur = conn.cursor()

        # Check current state
        print("Checking current notification_type values...")
        cur.execute("""
            SELECT id, login, share, notification_type 
            FROM res_users 
            WHERE notification_type IS NULL OR 
                  (share = TRUE AND notification_type = 'inbox') OR
                  (share = FALSE AND notification_type IS NULL)
            ORDER BY id;
        """)
        
        problematic_users = cur.fetchall()
        if problematic_users:
            print(f"Found {len(problematic_users)} users with notification_type issues:")
            for user in problematic_users:
                print(f"  User ID {user[0]} ({user[1]}): share={user[2]}, notification_type={user[3]}")
        else:
            print("No problematic users found.")
            return

        # Fix 1: Set notification_type = 'email' for all share users (portal/public users)
        print("\nFixing share users (setting notification_type = 'email')...")
        cur.execute("""
            UPDATE res_users 
            SET notification_type = 'email' 
            WHERE share = TRUE AND (notification_type IS NULL OR notification_type != 'email');
        """)
        affected = cur.rowcount
        print(f"Updated {affected} share users to notification_type='email'")

        # Fix 2: Set notification_type = 'email' for internal users that have NULL notification_type
        print("\nFixing internal users with NULL notification_type...")
        cur.execute("""
            UPDATE res_users 
            SET notification_type = 'email' 
            WHERE share = FALSE AND notification_type IS NULL;
        """)
        affected = cur.rowcount
        print(f"Updated {affected} internal users to notification_type='email'")

        # Verify the fix
        print("\nVerifying constraint compliance...")
        cur.execute("""
            SELECT COUNT(*) 
            FROM res_users 
            WHERE (share = TRUE AND notification_type = 'inbox') OR 
                  notification_type IS NULL;
        """)
        
        remaining_issues = cur.fetchone()[0]
        if remaining_issues == 0:
            print("✅ All notification_type constraint violations have been fixed!")
        else:
            print(f"⚠️  Still {remaining_issues} users with constraint violations")

        # Show summary of current state
        print("\nCurrent notification_type distribution:")
        cur.execute("""
            SELECT 
                CASE WHEN share THEN 'Share User' ELSE 'Internal User' END as user_type,
                notification_type,
                COUNT(*) as count
            FROM res_users 
            WHERE active = TRUE
            GROUP BY share, notification_type 
            ORDER BY share, notification_type;
        """)
        
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]} = {row[2]} users")

        cur.close()
        conn.close()
        print("\n✅ Database connection closed successfully.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("=== Fixing notification_type constraint violations ===")
    success = fix_notification_constraint()
    if success:
        print("\n🎉 Fix completed successfully! You can now start Odoo.")
    else:
        print("\n💥 Fix failed. Please check the error messages above.")