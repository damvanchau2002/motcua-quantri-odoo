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
    
    print("=== FINDING RULE-GROUP TABLES ===")
    
    # Check what tables exist for rule-group relationships
    cur.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_name LIKE '%rule%' OR table_name LIKE '%group%'
        ORDER BY table_name
    """)
    tables = cur.fetchall()
    print("Tables containing 'rule' or 'group':")
    for table in tables:
        print(f"  - {table[0]}")
    
    print("\n=== CHECKING SPECIFIC RULE-GROUP TABLES ===")
    
    # Check specific tables that might contain rule-group relationships
    possible_tables = ['ir_rule_group_rel', 'res_groups_ir_rule_rel', 'rule_group_rel']
    
    for table_name in possible_tables:
        try:
            cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}' ORDER BY ordinal_position")
            columns = cur.fetchall()
            if columns:
                print(f"\nTable '{table_name}' columns:")
                for col in columns:
                    print(f"  - {col[0]}")
                
                # Check if this table has any data
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cur.fetchone()[0]
                print(f"  Records: {count}")
                
                if count > 0:
                    # Show sample data
                    cur.execute(f"SELECT * FROM {table_name} LIMIT 5")
                    sample_data = cur.fetchall()
                    print(f"  Sample data: {sample_data}")
            else:
                print(f"\nTable '{table_name}' does not exist")
        except Exception as e:
            print(f"\nError checking table '{table_name}': {e}")
    
    print("\n=== CHECKING IR_RULE TABLE STRUCTURE ===")
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'ir_rule' ORDER BY ordinal_position")
    ir_rule_columns = cur.fetchall()
    print("ir_rule table columns:")
    for col in ir_rule_columns:
        print(f"  - {col[0]}")
    
    # Check if ir_rule has groups field
    cur.execute("SELECT id, name, groups FROM ir_rule WHERE id = 139")
    admin_rule = cur.fetchone()
    if admin_rule:
        print(f"\nAdmin rule (ID: 139):")
        print(f"  Name: {admin_rule[1]}")
        print(f"  Groups: {admin_rule[2]}")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)