
from odoo import api, SUPERUSER_ID
import sys

def run(env):
    print("--- CHECKING DATA ---")
    
    # Check Services
    service_count = env['student.service'].search_count([])
    print(f"Total Services: {service_count}")
    
    # Check Requests
    request_count = env['student.service.request'].search_count([])
    print(f"Total Requests: {request_count}")
    
    # Check Stats View
    try:
        stats = env['student.request.stats.service'].search([])
        print(f"Total Stats Rows: {len(stats)}")
        for stat in stats:
            print(f"  Service: {stat.service_id.name}, Created: {stat.created_requests}, New: {stat.new_requests}, Overdue: {stat.overdue_requests}")
    except Exception as e:
        print(f"Error querying stats view: {e}")

    # Check if View exists in DB
    env.cr.execute("SELECT count(*) FROM information_schema.views WHERE table_name = 'student_request_stats_service'")
    view_exists = env.cr.fetchone()[0]
    print(f"SQL View exists in information_schema: {view_exists}")
    
    # Test SQL directly
    try:
        env.cr.execute("SELECT * FROM student_request_stats_service LIMIT 5")
        rows = env.cr.fetchall()
        print(f"Direct SQL fetch (first 5): {rows}")
    except Exception as e:
        print(f"Direct SQL error: {e}")

if __name__ == '__main__':
    # This part is handled by odoo shell, we just need the function content basically if we were pasting
    # But for script execution via < input, we need to setup env if not provided or just rely on shell's locals
    # Odoo shell provides 'env'
    run(env)
