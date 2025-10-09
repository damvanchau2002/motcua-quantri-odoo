import psycopg2
import sys

try:
    # Connect to database
    conn = psycopg2.connect(
        host='localhost',
        database='odoo_db',
        user='odoo',
        password='odoo123',
        port=5432
    )
    cur = conn.cursor()
    
    print("=== FIXING RULE CONFLICTS FOR MITCHELL ADMIN ===")
    
    # Check current groups
    cur.execute("""
        SELECT rg.id, rg.name FROM res_groups rg
        JOIN res_groups_users_rel rgur ON rg.id = rgur.gid
        WHERE rgur.uid = 2
        ORDER BY rg.name
    """)
    current_groups = cur.fetchall()
    print(f"\nCurrent groups for Mitchell Admin:")
    for group in current_groups:
        print(f"   - ID: {group[0]}, Name: {group[1]}")
    
    # Find the Student Request User group (ID 52)
    student_user_group_id = None
    for group in current_groups:
        if 'Student Request User' in str(group[1]):
            student_user_group_id = group[0]
            break
    
    if student_user_group_id:
        print(f"\nFound Student Request User group: ID {student_user_group_id}")
        
        # Remove Mitchell Admin from Student Request User group
        print("Removing Mitchell Admin from Student Request User group...")
        cur.execute("""
            DELETE FROM res_groups_users_rel 
            WHERE uid = 2 AND gid = %s
        """, (student_user_group_id,))
        
        rows_affected = cur.rowcount
        print(f"Removed {rows_affected} group membership(s)")
        
        # Commit the change
        conn.commit()
        
        # Verify the change
        cur.execute("""
            SELECT rg.id, rg.name FROM res_groups rg
            JOIN res_groups_users_rel rgur ON rg.id = rgur.gid
            WHERE rgur.uid = 2
            ORDER BY rg.name
        """)
        new_groups = cur.fetchall()
        print(f"\nNew groups for Mitchell Admin:")
        for group in new_groups:
            print(f"   - ID: {group[0]}, Name: {group[1]}")
        
        print("\n✓ Successfully removed Mitchell Admin from Student Request User group")
        print("This should resolve the rule conflict and allow admin access.")
        
    else:
        print("\nStudent Request User group not found in Mitchell Admin's groups")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)