#!/usr/bin/env python3
import sys
import os

# Add Odoo to path
sys.path.append(os.path.dirname(__file__))

import odoo
from odoo import api, SUPERUSER_ID

def assign_admin_permissions():
    # Parse config
    odoo.tools.config.parse_config(['-c', 'odoo.cfg'])
    db_name = odoo.tools.config['db_name']
    
    # Get registry and cursor
    registry = odoo.registry(db_name)
    
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        
        try:
            # Get admin user and manager group
            admin_user = env.ref('base.user_admin')
            manager_group = env.ref('student_request.group_student_request_manager')
            
            # Check if admin already has the group
            if manager_group not in admin_user.groups_id:
                admin_user.write({'groups_id': [(4, manager_group.id)]})
                print('✓ Đã gán quyền Student Request Manager cho user admin')
            else:
                print('✓ User admin đã có quyền Student Request Manager')
                
            cr.commit()
            
        except Exception as e:
            print(f'✗ Lỗi: {e}')
            cr.rollback()

if __name__ == '__main__':
    assign_admin_permissions()