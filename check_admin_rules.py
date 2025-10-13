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
    
    print("=== CHECKING ADMIN RECORD RULES ===")
    
    # Check admin rule for student.service.request
    cur.execute("""
        SELECT ir.id, ir.name, ir.domain_force, ir.perm_read, ir.perm_write, ir.perm_create, ir.perm_unlink
        FROM ir_rule ir
        JOIN ir_model im ON ir.model_id = im.id
        WHERE im.model = 'student.service.request' AND ir.name LIKE '%Admin%'
    """)
    admin_rules = cur.fetchall()
    
    print(f"Found {len(admin_rules)} admin rules for student.service.request:")
    for rule in admin_rules:
        print(f"  - Rule ID: {rule[0]}")
        print(f"    Name: {rule[1]}")
        print(f"    Domain: {rule[2]}")
        print(f"    Permissions: read={rule[3]}, write={rule[4]}, create={rule[5]}, unlink={rule[6]}")
    
    print("\n=== CHECKING RULE-GROUP RELATIONSHIPS ===")
    
    if admin_rules:
        admin_rule_id = admin_rules[0][0]
        
        # Check rule_group_rel table with correct column names
        cur.execute("""
            SELECT rg.id, rg.name FROM res_groups rg
            JOIN rule_group_rel rgr ON rg.id = rgr.group_id
            WHERE rgr.rule_group_id = %s
        """, (admin_rule_id,))
        rule_groups = cur.fetchall()
        
        print(f"Admin rule (ID: {admin_rule_id}) applies to groups:")
        if rule_groups:
            for group in rule_groups:
                print(f"  - ID: {group[0]}, Name: {group[1]}")
        else:
            print("  - NO GROUPS ASSIGNED! This is the problem!")
    
    print("\n=== CHECKING MITCHELL ADMIN GROUPS ===")
    # Check Mitchell Admin's groups
    cur.execute("""
        SELECT rg.id, rg.name FROM res_groups rg
        JOIN res_groups_users_rel rgur ON rg.id = rgur.gid
        WHERE rgur.uid = 2 AND rg.id IN (4, 7)
        ORDER BY rg.name
    """)
    admin_groups = cur.fetchall()
    
    print(f"Mitchell Admin's admin groups (Settings & Technical):")
    for group in admin_groups:
        print(f"  - ID: {group[0]}, Name: {group[1]}")
    
    print("\n=== SOLUTION: ASSIGN ADMIN RULE TO SETTINGS GROUP ===")
    
    # Check if the assignment already exists
    if admin_rules:
        admin_rule_id = admin_rules[0][0]
        cur.execute("SELECT COUNT(*) FROM rule_group_rel WHERE rule_group_id = %s AND group_id = 4", (admin_rule_id,))
        exists = cur.fetchone()[0]
        
        if exists == 0:
            print("Inserting admin rule assignment to Settings group (ID: 4)...")
            cur.execute("INSERT INTO rule_group_rel (rule_group_id, group_id) VALUES (%s, %s)", (admin_rule_id, 4))
            conn.commit()
            print("✓ Admin rule successfully assigned to Settings group!")
        else:
            print("Admin rule is already assigned to Settings group.")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)