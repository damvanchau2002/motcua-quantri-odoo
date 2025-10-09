#!/usr/bin/env python3
import sys
import os

# Add Odoo to path
sys.path.append(os.path.dirname(__file__))

import odoo
from odoo import api, SUPERUSER_ID

def assign_user_permissions(user_login=None):
    # Parse config
    odoo.tools.config.parse_config(['-c', 'odoo.cfg'])
    db_name = odoo.tools.config['db_name']
    
    # Get registry and cursor
    registry = odoo.registry(db_name)
    
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        
        try:
            manager_group = env.ref('student_request.group_student_request_manager')
            
            if user_login:
                # Gán quyền cho user cụ thể
                user = env['res.users'].search([('login', '=', user_login)], limit=1)
                if not user:
                    print(f'✗ Không tìm thấy user với login: {user_login}')
                    return
                
                if manager_group not in user.groups_id:
                    user.write({'groups_id': [(4, manager_group.id)]})
                    print(f'✓ Đã gán quyền Student Request Manager cho user: {user.name} ({user.login})')
                else:
                    print(f'✓ User {user.name} ({user.login}) đã có quyền Student Request Manager')
            else:
                # Hiển thị danh sách user để chọn
                users = env['res.users'].search([('active', '=', True)])
                print("=== DANH SÁCH USER ===")
                for user in users:
                    has_permission = "✅" if manager_group in user.groups_id else "❌"
                    print(f"{has_permission} {user.name} (login: {user.login})")
                
                print("\n=== HƯỚNG DẪN ===")
                print("Để gán quyền cho user cụ thể, chạy:")
                print("python assign_user_permissions.py <login_user>")
                print("\nVí dụ:")
                print("python assign_user_permissions.py dvchau@ktxhcm.edu.vn")
                print("python assign_user_permissions.py damvanchau2002@gmail.com")
                
            cr.commit()
            
        except Exception as e:
            print(f'✗ Lỗi: {e}')
            cr.rollback()

if __name__ == '__main__':
    user_login = sys.argv[1] if len(sys.argv) > 1 else None
    assign_user_permissions(user_login)