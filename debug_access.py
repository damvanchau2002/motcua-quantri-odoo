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
    
    print("=== COMPREHENSIVE ACCESS DEBUG FOR MITCHELL ADMIN ===")
    
    # 1. Check Mitchell Admin user details
    cur.execute("SELECT id, login, active FROM res_users WHERE id = 2")
    user_info = cur.fetchone()
    print(f"\n1. Mitchell Admin User Info:")
    if user_info:
        print(f"   ID: {user_info[0]}, Login: {user_info[1]}, Active: {user_info[2]}")
    else:
        print("   ERROR: Mitchell Admin user not found!")
        sys.exit(1)
    
    # 2. Check all groups Mitchell Admin belongs to
    cur.execute("""
        SELECT rg.id, rg.name, rg.category_id FROM res_groups rg
        JOIN res_groups_users_rel rgur ON rg.id = rgur.gid
        WHERE rgur.uid = 2
        ORDER BY rg.name
    """)
    user_groups = cur.fetchall()
    print(f"\n2. Mitchell Admin belongs to {len(user_groups)} groups:")
    for group in user_groups:
        print(f"   - ID: {group[0]}, Name: {group[1]}, Category: {group[2]}")
    
    # 3. Check all rules for student.service.request
    cur.execute("""
        SELECT ir.id, ir.name, ir.domain_force, ir.perm_read, ir.perm_write, ir.perm_create, ir.perm_unlink, ir.active
        FROM ir_rule ir
        JOIN ir_model im ON ir.model_id = im.id
        WHERE im.model = 'student.service.request'
        ORDER BY ir.id
    """)
    all_rules = cur.fetchall()
    print(f"\n3. Found {len(all_rules)} rules for student.service.request:")
    for rule in all_rules:
        print(f"   - Rule ID: {rule[0]}")
        print(f"     Name: {rule[1]}")
        print(f"     Domain: {rule[2]}")
        print(f"     Permissions: read={rule[3]}, write={rule[4]}, create={rule[5]}, unlink={rule[6]}")
        print(f"     Active: {rule[7]}")
        
        # Check which groups this rule applies to
        cur.execute("""
            SELECT rg.id, rg.name FROM res_groups rg
            JOIN rule_group_rel rgr ON rg.id = rgr.group_id
            WHERE rgr.rule_group_id = %s
        """, (rule[0],))
        rule_groups = cur.fetchall()
        if rule_groups:
            print(f"     Applies to groups:")
            for rg in rule_groups:
                print(f"       - ID: {rg[0]}, Name: {rg[1]}")
        else:
            print(f"     WARNING: No groups assigned to this rule!")
        print()
    
    # 4. Check which rules Mitchell Admin should have access to
    print("4. Rules that Mitchell Admin should have access to:")
    mitchell_group_ids = [g[0] for g in user_groups]
    applicable_rules = []
    
    for rule in all_rules:
        cur.execute("""
            SELECT COUNT(*) FROM rule_group_rel rgr
            WHERE rgr.rule_group_id = %s AND rgr.group_id = ANY(%s)
        """, (rule[0], mitchell_group_ids))
        has_access = cur.fetchone()[0] > 0
        
        if has_access:
            applicable_rules.append(rule)
            print(f"   ✓ Rule ID {rule[0]}: {rule[1]}")
        else:
            print(f"   ✗ Rule ID {rule[0]}: {rule[1]} (No access)")
    
    # 5. Check if there are any conflicting rules
    print(f"\n5. Conflict Analysis:")
    if len(applicable_rules) > 1:
        print("   Multiple rules apply to Mitchell Admin:")
        for rule in applicable_rules:
            print(f"   - {rule[1]}: Domain {rule[2]}")
    elif len(applicable_rules) == 1:
        print(f"   Only one rule applies: {applicable_rules[0][1]}")
        print(f"   Domain: {applicable_rules[0][2]}")
    else:
        print("   ERROR: No rules apply to Mitchell Admin!")
    
    # 6. Check student.service.request records
    cur.execute("SELECT COUNT(*) FROM student_service_request")
    record_count = cur.fetchone()[0]
    print(f"\n6. Total student.service.request records in database: {record_count}")
    
    if record_count > 0:
        cur.execute("SELECT id, name FROM student_service_request LIMIT 5")
        sample_records = cur.fetchall()
        print("   Sample records:")
        for record in sample_records:
            print(f"   - ID: {record[0]}, Name: {record[1]}")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)