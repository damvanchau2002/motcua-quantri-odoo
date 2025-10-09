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
            
            print("=== KIỂM TRA VÀ GÁN QUYỀN ADMIN ===")
            print(f"Admin user: {admin_user.name} (login: {admin_user.login})")
            print(f"Manager group: {manager_group.name}")
            print()
            
            # Check if admin already has the group
            if manager_group not in admin_user.groups_id:
                admin_user.write({'groups_id': [(4, manager_group.id)]})
                print('✅ Đã gán quyền Student Request Manager cho user admin')
            else:
                print('✅ User admin đã có quyền Student Request Manager')
            
            # Kiểm tra tổng quan quyền
            print()
            print("=== TỔNG QUAN QUYỀN DUYỆT ===")
            users_with_permission = env['res.users'].search([
                ('groups_id', 'in', [manager_group.id]),
                ('active', '=', True)
            ])
            
            print(f"Số user có quyền duyệt: {len(users_with_permission)}")
            for user in users_with_permission:
                print(f"  - {user.name} (login: {user.login})")
            
            print()
            print("=== LƯU Ý ===")
            print("• Nút duyệt chỉ hiển thị cho user có quyền 'Student Request Manager'")
            print("• Nếu bạn đăng nhập bằng user khác, nút duyệt sẽ không hiển thị")
            print("• Để gán quyền cho user khác, chạy: python assign_user_permissions.py <login>")
                
            cr.commit()
            
        except Exception as e:
            print(f'✗ Lỗi: {e}')
            cr.rollback()

if __name__ == '__main__':
    assign_admin_permissions()